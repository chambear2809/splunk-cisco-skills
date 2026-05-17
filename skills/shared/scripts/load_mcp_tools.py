#!/usr/bin/env python3
"""Load legacy MCP tool JSON through the supported Splunk MCP REST contract."""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

LIB_DIR = Path(__file__).resolve().parents[1] / "lib"
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

from mcp_tooling import (  # noqa: E402
    ManifestError,
    infer_external_app_id,
    read_json,
    rest_batch_payload,
    rest_tool_id,
    validate_legacy_doc,
)


LEGACY_FALLBACK_STATUSES = {404, 405, 501}


class HTTPFailure(RuntimeError):
    def __init__(self, status: int, body: Any, raw: str) -> None:
        super().__init__(f"HTTP {status}: {raw[:500]}")
        self.status = status
        self.body = body
        self.raw = raw


def ssl_context_from_env() -> ssl.SSLContext:
    tls_mode = os.environ.pop("__SPLUNK_TLS_MODE", "verify")
    tls_ca_cert = os.environ.pop("__SPLUNK_TLS_CA_CERT", "")
    if tls_mode == "ca-cert":
        return ssl.create_default_context(cafile=tls_ca_cert)
    if tls_mode == "verify":
        return ssl.create_default_context()
    return ssl._create_unverified_context()


def request_json(
    url: str,
    *,
    method: str,
    session_key: str,
    ctx: ssl.SSLContext,
    payload: dict[str, Any] | None = None,
) -> tuple[int, Any, str]:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Splunk {session_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=60) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return response.status, parse_json_body(raw), raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise HTTPFailure(exc.code, parse_json_body(raw), raw) from exc


def parse_json_body(raw: str) -> Any:
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def endpoint(base_uri: str, app_context: str, path: str) -> str:
    return (
        f"{base_uri.rstrip('/')}/servicesNS/nobody/"
        f"{urllib.parse.quote(app_context, safe='')}/{path.lstrip('/')}"
    )


def load_via_rest_batch(
    *,
    legacy_doc: dict[str, Any],
    splunk_uri: str,
    app_context: str,
    session_key: str,
    ctx: ssl.SSLContext,
    override_collisions: bool,
) -> None:
    payload = rest_batch_payload(legacy_doc)
    external_app_id = payload["external_app_id"]
    tool_ids = [rest_tool_id(tool, external_app_id) for tool in payload["tools"]]
    legacy_tool_ids = [
        str(tool.get("_key", "")).strip()
        for tool in legacy_doc.get("tools", [])
        if isinstance(tool, dict) and str(tool.get("_key", "")).strip()
    ]
    stale_legacy_tool_ids = sorted(set(legacy_tool_ids) - set(tool_ids))

    collisions_status, collisions_payload, _ = request_json(
        endpoint(splunk_uri, app_context, "mcp_tools/collisions"),
        method="POST",
        session_key=session_key,
        ctx=ctx,
        payload={"tool_ids": tool_ids},
    )
    if collisions_status != 200:
        raise HTTPFailure(collisions_status, collisions_payload, json.dumps(collisions_payload))

    collisions = {}
    if isinstance(collisions_payload, dict):
        raw_collisions = collisions_payload.get("collisions", {})
        if isinstance(raw_collisions, dict):
            collisions = {key: value for key, value in raw_collisions.items() if value}
    if collisions and not override_collisions:
        raise ManifestError(
            "MCP tool collisions detected; rerun with --override-collisions after review: "
            + json.dumps(collisions, sort_keys=True)
        )

    status, batch_response, _ = request_json(
        endpoint(splunk_uri, app_context, "mcp_tools"),
        method="POST",
        session_key=session_key,
        ctx=ctx,
        payload=payload,
    )
    if status != 200:
        raise HTTPFailure(status, batch_response, json.dumps(batch_response))
    registered = batch_response.get("registered_count") if isinstance(batch_response, dict) else "?"
    deleted = batch_response.get("deleted_count") if isinstance(batch_response, dict) else "?"
    print(f"REST batch registered {registered} tools for {external_app_id}; deleted stale tools: {deleted}")

    cleanup_stale_legacy_keys(
        stale_legacy_tool_ids,
        splunk_uri=splunk_uri,
        app_context=app_context,
        session_key=session_key,
        ctx=ctx,
    )

    enabled = 0
    for rest_tool in payload["tools"]:
        tool_id = rest_tool_id(rest_tool, external_app_id)
        tool_name = rest_tool["name"]
        status, enable_response, _ = request_json(
            endpoint(splunk_uri, app_context, "mcp_tools"),
            method="POST",
            session_key=session_key,
            ctx=ctx,
            payload={
                "tool_id": tool_id,
                "tool_name": tool_name,
                "enabled": True,
                "override": override_collisions,
            },
        )
        if status != 200:
            raise HTTPFailure(status, enable_response, json.dumps(enable_response))
        enabled += 1
        print(f"  ENABLED: {tool_name} ({tool_id})")
    print(f"Summary: {len(payload['tools'])} tools loaded, {enabled} tools enabled")


def cleanup_stale_legacy_keys(
    stale_legacy_tool_ids: list[str],
    *,
    splunk_uri: str,
    app_context: str,
    session_key: str,
    ctx: ssl.SSLContext,
) -> None:
    for tool_id in stale_legacy_tool_ids:
        try:
            request_json(
                endpoint(splunk_uri, app_context, "mcp_tools"),
                method="DELETE",
                session_key=session_key,
                ctx=ctx,
                payload={"tool_id": tool_id},
            )
            print(f"  REMOVED LEGACY KEY: {tool_id}")
        except HTTPFailure as exc:
            if exc.status == 404:
                continue
            raise


def load_via_legacy_kv(
    *,
    legacy_doc: dict[str, Any],
    splunk_uri: str,
    app_context: str,
    session_key: str,
    ctx: ssl.SSLContext,
) -> None:
    tools = legacy_doc.get("tools", [])
    loaded = 0
    enabled = 0
    for tool in tools:
        key = str(tool.get("_key", "")).strip()
        name = str(tool.get("name", "")).strip()
        if not key or not name:
            print("  SKIP: tool missing _key or name")
            continue

        key_path = urllib.parse.quote(key, safe="")
        try:
            request_json(
                endpoint(splunk_uri, app_context, f"storage/collections/data/mcp_tools/{key_path}"),
                method="POST",
                session_key=session_key,
                ctx=ctx,
                payload=tool,
            )
            print(f"  UPDATED: {name} ({key})")
            loaded += 1
        except HTTPFailure as exc:
            if exc.status != 404:
                raise
            try:
                request_json(
                    endpoint(splunk_uri, app_context, "storage/collections/data/mcp_tools"),
                    method="POST",
                    session_key=session_key,
                    ctx=ctx,
                    payload=tool,
                )
                print(f"  INSERTED: {name} ({key})")
                loaded += 1
            except HTTPFailure as insert_exc:
                if insert_exc.status == 409:
                    print(f"  EXISTS: {name} ({key})")
                    loaded += 1
                else:
                    raise

        name_path = urllib.parse.quote(name, safe="")
        enable_payload = {"_key": name, "tool_id": key}
        try:
            request_json(
                endpoint(splunk_uri, app_context, f"storage/collections/data/mcp_tools_enabled/{name_path}"),
                method="POST",
                session_key=session_key,
                ctx=ctx,
                payload=enable_payload,
            )
            print(f"  ENABLED: {name}")
            enabled += 1
        except HTTPFailure as exc:
            if exc.status != 404:
                raise
            try:
                request_json(
                    endpoint(splunk_uri, app_context, "storage/collections/data/mcp_tools_enabled"),
                    method="POST",
                    session_key=session_key,
                    ctx=ctx,
                    payload=enable_payload,
                )
                print(f"  ENABLED: {name}")
                enabled += 1
            except HTTPFailure as insert_exc:
                if insert_exc.status == 409:
                    print(f"  ALREADY ENABLED: {name}")
                    enabled += 1
                else:
                    raise
    print(f"Summary: {loaded}/{len(tools)} tools loaded, {enabled}/{len(tools)} tools enabled via legacy KV")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tools-json", required=True, help="legacy mcp_tools.json path")
    parser.add_argument("--splunk-uri", required=True, help="Splunk management URI")
    parser.add_argument("--app-context", default="Splunk_MCP_Server")
    parser.add_argument(
        "--allow-legacy-kv",
        action="store_true",
        help="fallback to direct KV Store writes when the REST batch endpoint is unavailable",
    )
    parser.add_argument(
        "--override-collisions",
        action="store_true",
        help="enable tools even when the collision endpoint reports conflicts",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    session_key = os.environ.pop("__SPLUNK_SK", "")
    if not session_key:
        print("ERROR: __SPLUNK_SK is required.", file=sys.stderr)
        return 1

    tools_path = Path(args.tools_json)
    legacy_doc = read_json(tools_path)
    enforce_generated = tools_path.with_name("mcp_tools.source.yaml").exists()
    errors = validate_legacy_doc(
        legacy_doc,
        source=str(tools_path),
        enforce_generated_rules=enforce_generated,
    )
    if errors:
        print("ERROR: MCP tools JSON failed validation:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    ctx = ssl_context_from_env()
    try:
        app_id = infer_external_app_id(legacy_doc)
        print(f"Loading MCP tools for external_app_id={app_id} from {tools_path}")
        load_via_rest_batch(
            legacy_doc=legacy_doc,
            splunk_uri=args.splunk_uri,
            app_context=args.app_context,
            session_key=session_key,
            ctx=ctx,
            override_collisions=args.override_collisions,
        )
        return 0
    except ManifestError as exc:
        print(f"ERROR: REST MCP tool load failed: {exc}", file=sys.stderr)
        return 1
    except HTTPFailure as exc:
        if not args.allow_legacy_kv or exc.status not in LEGACY_FALLBACK_STATUSES:
            print(f"ERROR: REST MCP tool load failed: {exc}", file=sys.stderr)
            print("Use --allow-legacy-kv only when an older Splunk MCP Server app lacks the REST batch endpoint.", file=sys.stderr)
            return 1
        print(f"WARNING: REST MCP tool load failed; falling back to legacy KV mode: {exc}", file=sys.stderr)
        load_via_legacy_kv(
            legacy_doc=legacy_doc,
            splunk_uri=args.splunk_uri,
            app_context=args.app_context,
            session_key=session_key,
            ctx=ctx,
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
