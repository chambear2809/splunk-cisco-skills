#!/usr/bin/env python3
"""Attach Luna/SLM-backed Galileo scorers to a log stream.

The script uses Galileo's documented v2 scorer and metric-settings APIs. It is
secret-file based and never prints the API key.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib import error, request


DEFAULT_REPLACEMENTS = [
    {"from": "correctness", "to": "correctness_luna"},
    {"from": "completeness", "to": "completeness_luna"},
    {"from": "instruction_adherence", "to": "instruction_adherence_luna"},
    {"from": "tool_selection_quality", "to": "tool_selection_quality_luna"},
    {"from": "tool_error_rate", "to": "tool_error_rate_luna"},
    {"from": "agent_efficiency", "to": "agent_efficiency_luna"},
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--galileo-api-key-file", required=True)
    parser.add_argument("--api-base", default="https://api.galileo.ai")
    parser.add_argument("--project-id", default="")
    parser.add_argument("--log-stream-id", default="")
    parser.add_argument("--lifecycle-result", default="")
    parser.add_argument("--scorer-map", default="")
    parser.add_argument("--output", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--list-only", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--recompute", action="store_true")
    parser.add_argument("--recompute-limit", type=int, default=100)
    return parser.parse_args(argv)


def read_secret_file(path: str) -> str:
    secret_path = Path(path).expanduser()
    if not secret_path.is_file():
        raise SystemExit(f"ERROR: Galileo API key file is not readable: {secret_path}")
    value = secret_path.read_text(encoding="utf-8").strip()
    if not value:
        raise SystemExit(f"ERROR: Galileo API key file is empty: {secret_path}")
    return value


def load_json_file(path: str) -> dict[str, Any]:
    if not path:
        return {}
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        raise SystemExit(f"ERROR: Scorer map file not found: {file_path}")
    data = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("ERROR: Scorer map must be a JSON object")
    return data


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def normalize_replacements(config: dict[str, Any]) -> list[dict[str, Any]]:
    raw = config.get("replacements") or config.get("scorers") or DEFAULT_REPLACEMENTS
    replacements: list[dict[str, Any]] = []
    if isinstance(raw, dict):
        raw = [{"from": key, "to": value} for key, value in raw.items()]
    if not isinstance(raw, list):
        raise SystemExit("ERROR: Scorer replacements must be a list or mapping")
    for item in raw:
        if not isinstance(item, dict):
            raise SystemExit("ERROR: Each scorer replacement must be an object")
        source = str(item.get("from") or item.get("source") or item.get("name") or "").strip()
        target = str(item.get("to") or item.get("target") or item.get("to_name") or "").strip()
        target_id = str(item.get("to_id") or item.get("target_id") or item.get("id") or "").strip()
        if not source:
            raise SystemExit("ERROR: Scorer replacement is missing a from/source name")
        if not target and not target_id and not truthy(item.get("remove", False)):
            raise SystemExit(f"ERROR: Scorer replacement for {source} is missing to/to_id")
        normalized = dict(item)
        normalized["from"] = source
        if truthy(item.get("remove", False)):
            normalized["remove"] = True
        if target:
            normalized["to"] = target
        if target_id:
            normalized["to_id"] = target_id
        replacements.append(normalized)
    for item in config.get("custom_luna_scorer_ids") or []:
        if not isinstance(item, dict):
            raise SystemExit("ERROR: custom_luna_scorer_ids entries must be objects")
        if not str(item.get("to_id") or item.get("target_id") or item.get("id") or "").strip():
            continue
        source = str(item.get("from") or item.get("source") or item.get("name") or "").strip()
        if not source:
            raise SystemExit("ERROR: custom_luna_scorer_ids entry is missing from/source")
        normalized = dict(item)
        normalized["from"] = source
        normalized["to_id"] = str(item.get("to_id") or item.get("target_id") or item.get("id")).strip()
        normalized.setdefault("scorer_type", "luna")
        normalized.setdefault("model_type", "slm")
        replacements.append(normalized)
    return replacements


class GalileoClient:
    def __init__(self, api_base: str, api_key: str) -> None:
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key

    def request_json(self, method: str, path: str, body: Any | None = None) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = request.Request(
            self.api_base + path,
            method=method,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Galileo-API-Key": self.api_key,
            },
        )
        try:
            with request.urlopen(req, timeout=60) as response:
                text = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} failed with HTTP {exc.code}: {detail}") from exc
        if not text:
            return {}
        return json.loads(text)

    def metric_settings(self, project_id: str, log_stream_id: str) -> dict[str, Any]:
        return self.request_json(
            "GET",
            f"/v2/projects/{project_id}/log_streams/{log_stream_id}/metric_settings",
        )

    def patch_metric_settings(
        self,
        project_id: str,
        log_stream_id: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        return self.request_json(
            "PATCH",
            f"/v2/projects/{project_id}/log_streams/{log_stream_id}/metric_settings",
            body,
        )

    def list_scorers(self, filters: list[dict[str, Any]]) -> list[dict[str, Any]]:
        payload = {"filters": filters}
        response = self.request_json("POST", "/v2/scorers/list", payload)
        scorers = response.get("scorers", [])
        if not isinstance(scorers, list):
            raise RuntimeError("Unexpected scorer list response shape")
        return [item for item in scorers if isinstance(item, dict)]

    def recompute_metrics(
        self,
        project_id: str,
        log_stream_id: str,
        scorer_ids: list[str],
        limit: int,
    ) -> Any:
        return self.request_json(
            "POST",
            f"/v2/projects/{project_id}/recompute-metrics",
            {
                "log_stream_id": log_stream_id,
                "scorer_ids": scorer_ids,
                "limit": limit,
                "starting_token": 0,
            },
        )


def scorer_identity(scorer: dict[str, Any]) -> dict[str, Any]:
    latest = scorer.get("latest_version") or {}
    default = scorer.get("default_version") or {}
    return {
        "id": scorer.get("id"),
        "name": scorer.get("name"),
        "label": scorer.get("label"),
        "scorer_type": scorer.get("scorer_type"),
        "model_type": scorer.get("model_type"),
        "input_type": scorer.get("input_type") or latest.get("input_type") or default.get("input_type"),
        "output_type": scorer.get("output_type") or latest.get("output_type") or default.get("output_type"),
        "default_version_id": scorer.get("default_version_id"),
        "latest_version_id": latest.get("id"),
    }


def index_scorers_by_name(client: GalileoClient, target_names: list[str]) -> dict[str, dict[str, Any]]:
    if not target_names:
        return {}
    scorers = client.list_scorers(
        [
            {
                "name": "name",
                "operator": "one_of",
                "value": sorted(set(target_names)),
            }
        ]
    )
    return {str(scorer.get("name")): scorer for scorer in scorers if scorer.get("name")}


def slm_inventory(client: GalileoClient) -> list[dict[str, Any]]:
    return [
        scorer_identity(item)
        for item in client.list_scorers([{"name": "model_type", "operator": "eq", "value": "slm"}])
    ]


def scorer_config_from_target(
    current: dict[str, Any],
    replacement: dict[str, Any],
    target: dict[str, Any] | None,
) -> dict[str, Any]:
    target_id = replacement.get("to_id") or (target or {}).get("id")
    if not target_id:
        raise RuntimeError(f"Replacement target for {replacement['from']} has no scorer id")

    config: dict[str, Any] = {
        "id": target_id,
        "scorer_type": replacement.get("scorer_type") or (target or {}).get("scorer_type") or "preset",
    }
    optional_fields = [
        "filters",
        "cot_enabled",
        "num_judges",
        "scoreable_node_types",
        "roll_up_method",
    ]
    for field in optional_fields:
        value = replacement.get(field)
        if value is None:
            value = (target or {}).get(field)
        if value is None:
            value = current.get(field)
        if value is not None:
            config[field] = value

    name = replacement.get("to") or replacement.get("to_name") or (target or {}).get("name")
    if name:
        config["name"] = name
    model_type = replacement.get("model_type") or (target or {}).get("model_type") or "slm"
    if model_type:
        config["model_type"] = model_type
    output_type = replacement.get("output_type") or (target or {}).get("output_type") or current.get("output_type")
    if output_type:
        config["output_type"] = output_type
    input_type = replacement.get("input_type") or (target or {}).get("input_type") or current.get("input_type")
    if input_type:
        config["input_type"] = input_type
    model_name = replacement.get("model_name") or (target or {}).get("model_name")
    if model_name:
        config["model_name"] = model_name
    return config


def build_metric_settings_plan(
    settings: dict[str, Any],
    replacements: list[dict[str, Any]],
    targets_by_name: dict[str, dict[str, Any]],
    strict: bool,
) -> dict[str, Any]:
    current_scorers = [item for item in settings.get("scorers", []) if isinstance(item, dict)]
    replacements_by_source = {item["from"]: item for item in replacements}
    new_scorers: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    preserved: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for scorer in current_scorers:
        name = str(scorer.get("name") or "")
        replacement = replacements_by_source.get(name)
        if not replacement:
            preserved.append(scorer_identity(scorer))
            scorer_id = str(scorer.get("id") or "")
            if scorer_id and scorer_id not in seen_ids:
                new_scorers.append(scorer)
                seen_ids.add(scorer_id)
            continue

        if replacement.get("remove"):
            applied.append(
                {
                    "from": scorer_identity(scorer),
                    "to": None,
                    "status": "removed",
                }
            )
            continue

        target = targets_by_name.get(str(replacement.get("to") or ""))
        if not target and not replacement.get("to_id"):
            unavailable.append(
                {
                    "from": name,
                    "requested_target": replacement.get("to"),
                    "reason": "target_scorer_not_found",
                }
            )
            preserved.append(scorer_identity(scorer))
            scorer_id = str(scorer.get("id") or "")
            if scorer_id and scorer_id not in seen_ids:
                new_scorers.append(scorer)
                seen_ids.add(scorer_id)
            continue

        next_config = scorer_config_from_target(scorer, replacement, target)
        next_id = str(next_config.get("id") or "")
        if next_id in seen_ids:
            applied.append(
                {
                    "from": scorer_identity(scorer),
                    "to": scorer_identity(target or next_config),
                    "status": "deduplicated_target_already_enabled",
                }
            )
            continue
        new_scorers.append(next_config)
        seen_ids.add(next_id)
        applied.append(
            {
                "from": scorer_identity(scorer),
                "to": scorer_identity(target or next_config),
                "status": "planned",
            }
        )

    errors = []
    if strict and unavailable:
        errors.append("strict mode requested but one or more Luna scorer targets were not found")

    patch_body = {
        "scorers": new_scorers,
        "segment_filters": settings.get("segment_filters"),
    }
    return {
        "patch_body": patch_body,
        "applied": applied,
        "unavailable": unavailable,
        "preserved": preserved,
        "errors": errors,
    }


def write_result(path: str, payload: dict[str, Any]) -> None:
    output = Path(path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def resolve_ids(args: argparse.Namespace) -> tuple[str, str]:
    project_id = str(args.project_id or "").strip()
    log_stream_id = str(args.log_stream_id or "").strip()
    if project_id and log_stream_id:
        return project_id, log_stream_id
    if args.lifecycle_result:
        path = Path(args.lifecycle_result).expanduser()
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            project = data.get("project") or {}
            log_stream = data.get("log_stream") or {}
            project_id = project_id or str(project.get("id") or "").strip()
            log_stream_id = log_stream_id or str(log_stream.get("id") or "").strip()
    missing = []
    if not project_id:
        missing.append("project_id")
    if not log_stream_id:
        missing.append("log_stream_id")
    if missing:
        raise SystemExit(
            "ERROR: Missing "
            + ", ".join(missing)
            + ". Pass --project-id/--log-stream-id or --lifecycle-result from object-lifecycle."
        )
    return project_id, log_stream_id


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    map_config = load_json_file(args.scorer_map)
    replacements = normalize_replacements(map_config)
    strict = args.strict or truthy(map_config.get("strict", False))
    list_only = args.list_only or truthy(map_config.get("list_only", False))
    recompute = args.recompute or truthy(map_config.get("recompute", False))
    api_key = read_secret_file(args.galileo_api_key_file)
    client = GalileoClient(args.api_base, api_key)
    project_id, log_stream_id = resolve_ids(args)

    result: dict[str, Any] = {
        "api_version": "galileo-platform-setup/luna-scorer-settings-result/v1",
        "secret_values_rendered": False,
        "dry_run": args.dry_run,
        "list_only": list_only,
        "project_id": project_id,
        "log_stream_id": log_stream_id,
        "replacements": replacements,
        "status": "ok",
        "errors": [],
    }
    try:
        settings = client.metric_settings(project_id, log_stream_id)
        target_names = [str(item.get("to") or "") for item in replacements if item.get("to")]
        targets_by_name = index_scorers_by_name(client, target_names)
        result["current_scorers"] = [scorer_identity(item) for item in settings.get("scorers", [])]
        result["available_slm_scorers"] = slm_inventory(client)
        result["target_scorers"] = {
            name: scorer_identity(scorer) for name, scorer in sorted(targets_by_name.items())
        }
        if list_only:
            write_result(args.output, result)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0

        plan = build_metric_settings_plan(settings, replacements, targets_by_name, strict)
        result.update(
            {
                "planned_replacements": plan["applied"],
                "unavailable_replacements": plan["unavailable"],
                "preserved_scorers": plan["preserved"],
                "patch_body": plan["patch_body"] if args.dry_run else {"redacted": "written_to_output_summary_only"},
            }
        )
        if plan["errors"]:
            result["status"] = "error"
            result["errors"] = plan["errors"]
            write_result(args.output, result)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 1
        if not plan["applied"]:
            result["status"] = "no_changes"
            write_result(args.output, result)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        if args.dry_run:
            result["status"] = "planned"
            write_result(args.output, result)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0

        updated = client.patch_metric_settings(project_id, log_stream_id, plan["patch_body"])
        result["status"] = "updated"
        result["updated_scorers"] = [scorer_identity(item) for item in updated.get("scorers", [])]
        recompute_ids = [
            str(item.get("to", {}).get("id") or "")
            for item in result["planned_replacements"]
            if item.get("status") == "planned"
        ]
        recompute_ids = [item for item in recompute_ids if item]
        if recompute and recompute_ids:
            result["recompute"] = client.recompute_metrics(
                project_id,
                log_stream_id,
                recompute_ids,
                args.recompute_limit,
            )
    except Exception as exc:
        result["status"] = "error"
        result["errors"] = [str(exc)]
        write_result(args.output, result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1

    write_result(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
