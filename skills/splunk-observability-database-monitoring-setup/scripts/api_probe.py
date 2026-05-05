"""Read-only Splunk Observability API probe for DBMon telemetry."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_METRIC = "postgresql.database.count"


class ApiProbeError(RuntimeError):
    """Raised when a read-only Observability API probe fails."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", default="")
    parser.add_argument("--realm", default="")
    parser.add_argument("--token-file", default="")
    parser.add_argument("--metric", default=DEFAULT_METRIC)
    parser.add_argument("--filter", dest="filters", action="append", default=[])
    parser.add_argument("--lookback-seconds", type=int, default=600)
    parser.add_argument("--resolution-ms", type=int, default=10000)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    return parser.parse_args(argv)


def load_metadata(path: str) -> dict[str, Any]:
    if not path:
        return {}
    metadata_path = Path(path)
    if not metadata_path.is_file():
        raise ApiProbeError(f"metadata file not found: {metadata_path}")
    data = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ApiProbeError(f"metadata file must contain a JSON object: {metadata_path}")
    return data


def token_from_file(path: str) -> str:
    if not path:
        raise ApiProbeError("SPLUNK_O11Y_TOKEN_FILE is required for --api validation.")
    token_path = Path(path)
    if not token_path.is_file():
        raise ApiProbeError(f"SPLUNK_O11Y_TOKEN_FILE does not exist: {token_path}")
    token = token_path.read_text(encoding="utf-8").strip()
    if not token:
        raise ApiProbeError("SPLUNK_O11Y_TOKEN_FILE is empty.")
    return token


def parse_filter(raw: str) -> tuple[str, str]:
    if "=" not in raw:
        raise ApiProbeError(f"--filter must look like key=value, got {raw!r}.")
    key, value = raw.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key or not value:
        raise ApiProbeError(f"--filter must include non-empty key and value, got {raw!r}.")
    return key, value


def signalflow_string(value: str) -> str:
    return json.dumps(value)


def signalflow_program(metric: str, filters: list[tuple[str, str]]) -> str:
    metric_arg = signalflow_string(metric)
    if not filters:
        return f"data({metric_arg}).count().publish(label=\"dbmon_api_probe\")"
    if len(filters) > 1:
        raise ApiProbeError("The DBMon API probe currently supports one SignalFlow filter.")
    key, value = filters[0]
    filter_arg = f"filter({signalflow_string(key)}, {signalflow_string(value)})"
    return (
        f"data({metric_arg}, filter={filter_arg}).count().publish("
        'label="dbmon_api_probe")'
    )


def request_json(url: str, token: str, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "X-SF-TOKEN": token},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise ApiProbeError(f"Observability API returned HTTP {exc.code}: {body[:300]}") from exc
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ApiProbeError("Observability API did not return a JSON object.")
    return data


def execute_signalflow(
    *,
    realm: str,
    token: str,
    program: str,
    lookback_seconds: int,
    resolution_ms: int,
    timeout_seconds: int,
) -> str:
    now_ms = int(time.time() * 1000)
    params = urllib.parse.urlencode(
        {
            "start": str(now_ms - lookback_seconds * 1000),
            "stop": str(now_ms),
            "resolution": str(resolution_ms),
        }
    )
    url = f"https://stream.{realm}.signalfx.com/v2/signalflow/execute?{params}"
    request = urllib.request.Request(
        url,
        data=program.encode("utf-8"),
        method="POST",
        headers={
            "Accept": "text/event-stream",
            "Content-Type": "text/plain",
            "X-SF-TOKEN": token,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return response.read(32768).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise ApiProbeError(f"SignalFlow returned HTTP {exc.code}: {body[:300]}") from exc


def metric_catalog_probe(realm: str, token: str, metric: str, timeout: int) -> dict[str, Any]:
    query = f"name:{metric}"
    url = f"https://api.{realm}.observability.splunkcloud.com/v2/metric?" + urllib.parse.urlencode(
        {"query": query, "limit": "10"}
    )
    data = request_json(url, token, timeout)
    results = data.get("results") or []
    if not isinstance(results, list):
        raise ApiProbeError("Metric catalog results field is not a list.")
    matches = [item for item in results if isinstance(item, dict) and item.get("name") == metric]
    if not matches:
        raise ApiProbeError(f"Metric catalog did not contain {metric!r}.")
    return {"count": data.get("count"), "matches": len(matches)}


def signalflow_probe(
    realm: str,
    token: str,
    metric: str,
    filters: list[tuple[str, str]],
    lookback_seconds: int,
    resolution_ms: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    program = signalflow_program(metric, filters)
    stream_text = execute_signalflow(
        realm=realm,
        token=token,
        program=program,
        lookback_seconds=lookback_seconds,
        resolution_ms=resolution_ms,
        timeout_seconds=timeout_seconds,
    )
    metadata_seen = bool(
        re.search(r'"sf_originatingMetric"\s*:\s*' + re.escape(json.dumps(metric)), stream_text)
    )
    data_messages = len(re.findall(r"event:\s*data", stream_text))
    if not metadata_seen:
        filter_text = ", ".join(f"{key}={value}" for key, value in filters) or "<none>"
        raise ApiProbeError(
            f"SignalFlow did not return metadata for {metric!r} with filter {filter_text}."
        )
    return {
        "metadata_seen": metadata_seen,
        "data_messages": data_messages,
        "program": program,
    }


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    metadata = load_metadata(args.metadata)
    realm = args.realm or metadata.get("realm") or ""
    token_file = args.token_file or ""
    if not token_file:
        import os

        token_file = os.environ.get("SPLUNK_O11Y_TOKEN_FILE", "")
    if not realm:
        import os

        realm = os.environ.get("SPLUNK_O11Y_REALM", "")
    if not realm:
        raise ApiProbeError("Splunk Observability realm is required for --api validation.")

    filters = [parse_filter(raw) for raw in args.filters]
    if not filters and metadata.get("cluster_name"):
        filters = [("k8s.cluster.name", str(metadata["cluster_name"]))]

    token = token_from_file(token_file)
    catalog = metric_catalog_probe(realm, token, args.metric, args.timeout_seconds)
    signalflow = signalflow_probe(
        realm,
        token,
        args.metric,
        filters,
        args.lookback_seconds,
        args.resolution_ms,
        args.timeout_seconds,
    )
    print(
        json.dumps(
            {
                "api": "splunk-observability-dbmon",
                "realm": realm,
                "metric": args.metric,
                "filters": [{"key": key, "value": value} for key, value in filters],
                "metric_catalog": catalog,
                "signalflow": {
                    "metadata_seen": signalflow["metadata_seen"],
                    "data_messages": signalflow["data_messages"],
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    try:
        return run()
    except ApiProbeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
