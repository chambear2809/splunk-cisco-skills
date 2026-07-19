#!/usr/bin/env python3
"""Render protected-asset identity evidence for the dedicated Galileo proxy."""

from __future__ import annotations

import argparse
import grp
import json
import os
import tempfile
import urllib.parse
from pathlib import Path

from collector_runtime_wrapper import (
    TINYPROXY_CONTROL,
    open_trusted_executable,
    read_trusted_proxy_asset,
    validate_endpoint,
    validate_galileo_proxy_url,
    validate_tinyproxy_config,
    validate_tinyproxy_filter,
)


def atomic_json(
    path: Path, document: dict[str, object], collector_group: str = ""
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o440)
        if collector_group:
            if not hasattr(os, "geteuid") or os.geteuid() != 0:
                raise ValueError("--collector-group requires root execution")
            try:
                group_id = grp.getgrnam(collector_group).gr_gid
            except KeyError as exc:
                raise ValueError("--collector-group does not exist") from exc
            os.chown(temporary, 0, group_id)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--filter", type=Path, required=True)
    parser.add_argument("--proxy-url", default="http://127.0.0.1:18888")
    parser.add_argument("--galileo-traces-endpoint", required=True)
    parser.add_argument(
        "--collector-group",
        default="",
        help=(
            "Production group owner; requires root and installs the output as "
            "root:GROUP mode 0440. Omit only for a staged artifact."
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        proxy_url, _, proxy_port = validate_galileo_proxy_url(args.proxy_url)
        _, canonical_endpoint = validate_endpoint(args.galileo_traces_endpoint)
        parsed_endpoint = urllib.parse.urlsplit(canonical_endpoint)
        allowed_host = parsed_endpoint.hostname
        if not allowed_host or parsed_endpoint.port not in {None, 443}:
            raise ValueError("Galileo traces endpoint must use HTTPS port 443")
        binary_descriptor, binary = open_trusted_executable(args.binary, None)
        os.close(binary_descriptor)
        config_data, config = read_trusted_proxy_asset(args.config, "config", None)
        filter_data, filter_provenance = read_trusted_proxy_asset(
            args.filter, "filter", None
        )
        validate_tinyproxy_filter(filter_data, allowed_host)
        validate_tinyproxy_config(
            config_data,
            proxy_port=proxy_port,
            filter_path=str(args.filter),
        )
        atomic_json(
            args.output,
            {
                "schema_version": 1,
                "control": TINYPROXY_CONTROL,
                "proxy_url": proxy_url,
                "allowed_connect_host": allowed_host,
                "allowed_connect_port": 443,
                "binary": binary,
                "config": config,
                "filter": filter_provenance,
            },
            args.collector_group,
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc


if __name__ == "__main__":
    main()
