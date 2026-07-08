"""Read-only Splunk Observability API probe for current DBMon telemetry."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ALLOWED_REALMS = {"us0", "us1", "eu0", "eu1", "eu2", "au0", "jp0", "sg0"}
MAX_TOKEN_BYTES = 16 * 1024
REDACTED = "<redacted>"
FILTER_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:/-]{0,255}$")
METRIC_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:/-]{0,511}$")
TARGET_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
RECEIVER_PATTERN = re.compile(
    r"^(?:postgresql|sqlserver|oracledb|mysql)/[A-Za-z0-9_-]{1,128}$"
)
SECRET_KEY_PARTS = (
    "accesskey",
    "accesstoken",
    "apikey",
    "auth",
    "authorization",
    "bearer",
    "clientsecret",
    "connectionstring",
    "credential",
    "datasource",
    "password",
    "passwd",
    "privatekey",
    "secret",
    "token",
)


class ApiProbeError(RuntimeError):
    """Raised when a read-only Observability API probe fails."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", default="")
    parser.add_argument("--realm", default="")
    parser.add_argument("--token-file", default="")
    parser.add_argument("--metric", dest="metrics", action="append", default=[])
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
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ApiProbeError(
            f"cannot read metadata file {metadata_path}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ApiProbeError(
            f"metadata file must contain a JSON object: {metadata_path}"
        )
    return data


def token_from_file(path: str) -> str:
    if not path:
        raise ApiProbeError("SPLUNK_O11Y_TOKEN_FILE is required for --api validation.")
    token_path = Path(path)
    try:
        before = os.lstat(token_path)
    except OSError as exc:
        raise ApiProbeError(
            f"cannot lstat SPLUNK_O11Y_TOKEN_FILE: {token_path}"
        ) from exc
    if stat.S_ISLNK(before.st_mode):
        raise ApiProbeError("SPLUNK_O11Y_TOKEN_FILE must not be a symbolic link.")
    if not stat.S_ISREG(before.st_mode):
        raise ApiProbeError("SPLUNK_O11Y_TOKEN_FILE must be a regular file.")
    # O_NONBLOCK closes the lstat/open FIFO-swap race; it has no effect on a
    # regular file, which is revalidated from the opened descriptor below.
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(token_path, flags)
    except OSError as exc:
        raise ApiProbeError(
            f"cannot securely open SPLUNK_O11Y_TOKEN_FILE: {token_path}"
        ) from exc
    try:
        info = os.fstat(descriptor)
        if (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino):
            raise ApiProbeError(
                "SPLUNK_O11Y_TOKEN_FILE changed while it was being opened."
            )
        if not stat.S_ISREG(info.st_mode):
            raise ApiProbeError("SPLUNK_O11Y_TOKEN_FILE must be a regular file.")
        raw = os.read(descriptor, MAX_TOKEN_BYTES + 1)
        after = os.fstat(descriptor)
    except ApiProbeError:
        raise
    except OSError as exc:
        raise ApiProbeError(
            "cannot securely read SPLUNK_O11Y_TOKEN_FILE; details were suppressed."
        ) from exc
    finally:
        os.close(descriptor)
    if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise ApiProbeError("SPLUNK_O11Y_TOKEN_FILE changed while it was being read.")
    if info.st_uid != os.geteuid():
        raise ApiProbeError("SPLUNK_O11Y_TOKEN_FILE must be owned by the current user.")
    if info.st_nlink != 1:
        raise ApiProbeError("SPLUNK_O11Y_TOKEN_FILE must have exactly one hard link.")
    if info.st_mode & 0o077:
        raise ApiProbeError(
            "SPLUNK_O11Y_TOKEN_FILE must be owner-only (for example chmod 400 or 600)."
        )
    if info.st_size <= 0 or info.st_size > MAX_TOKEN_BYTES or len(raw) != info.st_size:
        raise ApiProbeError("SPLUNK_O11Y_TOKEN_FILE has an invalid size.")
    try:
        token = raw.decode("utf-8", "strict")
    except UnicodeError as exc:
        raise ApiProbeError("SPLUNK_O11Y_TOKEN_FILE is not valid UTF-8 text.") from exc
    if not token or b"\x00" in raw or any(character.isspace() for character in token):
        raise ApiProbeError(
            "SPLUNK_O11Y_TOKEN_FILE must contain exactly one token with no whitespace or NUL."
        )
    return token


def secret_like_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return any(part in normalized for part in SECRET_KEY_PARTS)


def secret_like_value(value: str) -> bool:
    patterns = (
        r"(?i)^(?:bearer|basic)\s+",
        r"AKIA[0-9A-Z]{16}",
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        r"(?i)(?:password|passwd|token|secret|authorization|api[_-]?key)\s*[:=]",
        r"(?i)^[a-z][a-z0-9+.-]*://[^/@\s]+:[^/@\s]+@",
        r"^[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}$",
    )
    return any(re.search(pattern, value) for pattern in patterns)


def validate_filter(key: Any, value: Any, *, source: str) -> tuple[str, str]:
    if not isinstance(key, str) or not FILTER_KEY_PATTERN.fullmatch(key):
        raise ApiProbeError(f"{source} contains an invalid filter key.")
    if secret_like_key(key):
        raise ApiProbeError(f"{source} contains a prohibited secret-like filter key.")
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise ApiProbeError(f"{source} contains an invalid filter value.")
    if value != value.strip() or any(
        ord(character) < 32 or ord(character) == 127 for character in value
    ):
        raise ApiProbeError(f"{source} contains an invalid filter value.")
    if secret_like_value(value):
        raise ApiProbeError(f"{source} contains a prohibited secret-like filter value.")
    return key, value


def parse_filter(raw: str) -> tuple[str, str]:
    if "=" not in raw:
        raise ApiProbeError(
            "--filter must look like key=value; the value was suppressed."
        )
    key, value = raw.split("=", 1)
    return validate_filter(key, value, source="--filter")


def normalize_metric_names(raw: Any, *, source: str) -> list[str]:
    if not isinstance(raw, list) or not raw:
        raise ApiProbeError(f"{source} must contain at least one metric.")
    metrics: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise ApiProbeError(f"{source} contains an invalid metric name.")
        metric = item
        if (
            not METRIC_PATTERN.fullmatch(metric)
            or secret_like_key(metric)
            or secret_like_value(metric)
        ):
            raise ApiProbeError(f"{source} contains an invalid metric name.")
        if metric not in metrics:
            metrics.append(metric)
    return metrics


def normalize_probe_filters(raw: Any, *, target: str) -> list[tuple[str, str]]:
    if not isinstance(raw, list) or not raw:
        raise ApiProbeError(
            f"validation probe for target {target!r} must contain nonempty filters."
        )
    filters: list[tuple[str, str]] = []
    keys: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict) or set(entry) != {"key", "value"}:
            raise ApiProbeError(
                f"validation probe for target {target!r} has a malformed filter."
            )
        key, value = validate_filter(
            entry["key"],
            entry["value"],
            source=f"validation probe for target {target!r}",
        )
        if key in keys:
            raise ApiProbeError(
                f"validation probe for target {target!r} repeats filter key {key!r}."
            )
        keys.add(key)
        filters.append((key, value))
    return filters


def merge_filters(
    probe_filters: list[tuple[str, str]],
    global_filters: list[tuple[str, str]],
    *,
    target: str,
) -> list[tuple[str, str]]:
    merged = list(probe_filters)
    by_key = dict(probe_filters)
    for key, value in global_filters:
        if key in by_key:
            if by_key[key] != value:
                raise ApiProbeError(
                    f"--filter conflicts with the target-owned {key!r} filter for {target!r}; "
                    "values were suppressed."
                )
            continue
        by_key[key] = value
        merged.append((key, value))
    return merged


def normalize_global_filters(raw_filters: list[str]) -> list[tuple[str, str]]:
    filters: list[tuple[str, str]] = []
    by_key: dict[str, str] = {}
    for raw in raw_filters:
        key, value = parse_filter(raw)
        if key in by_key:
            if by_key[key] != value:
                raise ApiProbeError(
                    f"--filter repeats key {key!r} with conflicting values; values were suppressed."
                )
            continue
        by_key[key] = value
        filters.append((key, value))
    return filters


def normalize_metadata_probes(
    metadata: dict[str, Any], global_filters: list[tuple[str, str]]
) -> list[dict[str, Any]]:
    raw_probes = metadata.get("validation_probes")
    if not isinstance(raw_probes, list) or not raw_probes:
        raise ApiProbeError(
            "metadata.validation_probes must contain a filtered probe for every target."
        )

    target_records = metadata.get("targets")
    if not isinstance(target_records, list) or not target_records:
        raise ApiProbeError(
            "metadata.targets is required for target-specific API validation."
        )
    expected: dict[str, str] = {}
    for record in target_records:
        if not isinstance(record, dict):
            raise ApiProbeError("metadata.targets contains a malformed target.")
        target = record.get("name")
        receiver_id = record.get("receiver_id")
        if (
            not isinstance(target, str)
            or not TARGET_PATTERN.fullmatch(target)
            or not isinstance(receiver_id, str)
            or not RECEIVER_PATTERN.fullmatch(receiver_id)
        ):
            raise ApiProbeError("metadata.targets contains an invalid target identity.")
        if target in expected:
            raise ApiProbeError(f"metadata.targets repeats target {target!r}.")
        expected[target] = receiver_id

    probes: list[dict[str, Any]] = []
    identities: set[tuple[str, str]] = set()
    covered: set[str] = set()
    for raw_probe in raw_probes:
        if not isinstance(raw_probe, dict) or set(raw_probe) != {
            "target",
            "receiver_id",
            "metric",
            "filters",
        }:
            raise ApiProbeError(
                "metadata.validation_probes contains a malformed probe."
            )
        target = raw_probe.get("target")
        receiver_id = raw_probe.get("receiver_id")
        if not isinstance(target, str) or not TARGET_PATTERN.fullmatch(target):
            raise ApiProbeError(
                "metadata.validation_probes contains an invalid target."
            )
        if target not in expected:
            raise ApiProbeError(
                f"validation probe references unknown target {target!r}."
            )
        if receiver_id != expected[target]:
            raise ApiProbeError(
                f"validation probe receiver_id does not match target {target!r}."
            )
        metric = normalize_metric_names(
            [raw_probe.get("metric")], source=f"validation probe for target {target!r}"
        )[0]
        identity = (target, metric)
        if identity in identities:
            raise ApiProbeError(
                f"metadata.validation_probes repeats target/metric identity {target!r}."
            )
        identities.add(identity)
        covered.add(target)
        probe_filters = normalize_probe_filters(raw_probe.get("filters"), target=target)
        probes.append(
            {
                "target": target,
                "receiver_id": receiver_id,
                "metric": metric,
                "filters": merge_filters(probe_filters, global_filters, target=target),
            }
        )
    missing = sorted(set(expected) - covered)
    if missing:
        raise ApiProbeError(
            "metadata.validation_probes does not cover every metadata target: "
            + ", ".join(missing)
        )
    return probes


def normalize_ad_hoc_probes(
    metrics: list[str], global_filters: list[tuple[str, str]]
) -> list[dict[str, Any]]:
    if not global_filters:
        raise ApiProbeError(
            "Ad-hoc --metric validation requires at least one explicit --filter."
        )
    return [
        {
            "target": f"ad-hoc-{index}",
            "receiver_id": None,
            "metric": metric,
            "filters": list(global_filters),
        }
        for index, metric in enumerate(
            normalize_metric_names(metrics, source="--metric"), start=1
        )
    ]


def signalflow_string(value: str) -> str:
    return json.dumps(value)


def signalflow_program(metric: str, filters: list[tuple[str, str]]) -> str:
    arguments = [signalflow_string(metric)]
    if filters:
        filter_expression = " and ".join(
            f"filter({signalflow_string(key)}, {signalflow_string(value)})"
            for key, value in filters
        )
        arguments.append(f"filter={filter_expression}")
    return f'data({", ".join(arguments)}).count().publish(label="dbmon_api_probe")'


def request_json(url: str, token: str, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "X-SF-TOKEN": token},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_body = response.read(1024 * 1024 + 1)
            if len(raw_body) > 1024 * 1024:
                raise ApiProbeError(
                    "Observability API response exceeded the one-megabyte validation limit."
                )
            body = raw_body.decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        # API responses can reflect request material using escaping that makes
        # literal token replacement incomplete. Suppress the body entirely.
        try:
            exc.close()
        except OSError:
            pass
        raise ApiProbeError(
            f"Observability API returned HTTP {exc.code}; response body was suppressed."
        ) from exc
    except urllib.error.URLError as exc:
        raise ApiProbeError(f"Observability API request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise ApiProbeError("Observability API request timed out.") from exc
    except OSError as exc:
        raise ApiProbeError(
            "Observability API response read failed; details were suppressed."
        ) from exc
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ApiProbeError("Observability API returned invalid JSON.") from exc
    if not isinstance(data, dict):
        raise ApiProbeError("Observability API did not return a JSON object.")
    return data


def execute_signalflow(
    *,
    realm: str,
    token: str,
    program: str,
    metric: str,
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
    url = (
        f"https://stream.{realm}.observability.splunkcloud.com/"
        f"v2/signalflow/execute?{params}"
    )
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
    deadline = time.monotonic() + timeout_seconds
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            chunks: list[bytes] = []
            total = 0
            timed_out = False
            while True:
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
                try:
                    chunk = response.readline(64 * 1024)
                except TimeoutError:
                    timed_out = True
                    break
                except OSError as exc:
                    raise ApiProbeError(
                        "SignalFlow stream read failed; details were suppressed."
                    ) from exc
                if not chunk:
                    break
                total += len(chunk)
                if total > 1024 * 1024:
                    raise ApiProbeError(
                        "SignalFlow response exceeded the one-megabyte validation limit."
                    )
                chunks.append(chunk)
                if chunk in {b"\n", b"\r\n"}:
                    partial = b"".join(chunks).decode("utf-8", "replace")
                    events = parse_sse(partial)
                    metadata_seen = any(
                        contains_metric(payload, metric) for _, payload in events
                    )
                    positive_data_seen = any(
                        event == "data" and has_data(payload)
                        for event, payload in events
                    )
                    if metadata_seen and positive_data_seen:
                        return partial
            partial = b"".join(chunks).decode("utf-8", "replace")
            if timed_out and not partial:
                raise ApiProbeError(
                    "SignalFlow timed out before returning a complete event."
                )
            return partial
    except urllib.error.HTTPError as exc:
        # SignalFlow may echo the submitted program, including target filters.
        # Suppress its response body rather than risking identifier disclosure.
        try:
            exc.close()
        except OSError:
            pass
        raise ApiProbeError(
            f"SignalFlow returned HTTP {exc.code}; response body was suppressed."
        ) from exc
    except urllib.error.URLError as exc:
        raise ApiProbeError(f"SignalFlow request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise ApiProbeError(
            "SignalFlow timed out before returning a complete event."
        ) from exc
    except OSError as exc:
        raise ApiProbeError(
            "SignalFlow request failed; details were suppressed."
        ) from exc


def metric_catalog_probe(
    realm: str, token: str, metric: str, timeout: int
) -> dict[str, Any]:
    url = (
        f"https://api.{realm}.observability.splunkcloud.com/v2/metric?"
        + urllib.parse.urlencode({"query": f"name:{metric}", "limit": "10"})
    )
    data = request_json(url, token, timeout)
    results = data.get("results") or []
    if not isinstance(results, list):
        raise ApiProbeError("Metric catalog results field is not a list.")
    matches = [
        item
        for item in results
        if isinstance(item, dict) and item.get("name") == metric
    ]
    if not matches:
        raise ApiProbeError(f"Metric catalog did not contain {metric!r}.")
    return {"count": data.get("count"), "matches": len(matches)}


def parse_sse(stream_text: str) -> list[tuple[str, Any]]:
    events: list[tuple[str, Any]] = []
    current_event = ""
    data_lines: list[str] = []

    def finish() -> None:
        nonlocal current_event, data_lines
        if current_event or data_lines:
            raw = "\n".join(data_lines).strip()
            try:
                payload: Any = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                payload = raw
            events.append((current_event, payload))
        current_event = ""
        data_lines = []

    for line in stream_text.splitlines():
        if not line:
            finish()
        elif line.startswith("event:"):
            current_event = line.partition(":")[2].strip()
        elif line.startswith("data:"):
            data_lines.append(line.partition(":")[2].lstrip())
    finish()
    return events


def contains_metric(value: Any, metric: str) -> bool:
    if isinstance(value, dict):
        return value.get("sf_originatingMetric") == metric or any(
            contains_metric(child, metric) for child in value.values()
        )
    if isinstance(value, list):
        return any(contains_metric(child, metric) for child in value)
    return False


def positive_count_point(value: Any) -> bool:
    if isinstance(value, dict):
        if isinstance(value.get("value"), (int, float)):
            return value["value"] > 0
        return any(positive_count_point(child) for child in value.values())
    if isinstance(value, list):
        if len(value) >= 2 and isinstance(value[0], (int, float)):
            return positive_count_point(value[1])
        return any(positive_count_point(child) for child in value)
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def has_data(value: Any) -> bool:
    if isinstance(value, dict):
        points = value.get("data")
        if isinstance(points, list):
            return any(positive_count_point(point) for point in points)
        return any(has_data(child) for child in value.values())
    if isinstance(value, list):
        return any(has_data(child) for child in value)
    return False


def signalflow_probe(
    realm: str,
    token: str,
    target: str,
    metric: str,
    filters: list[tuple[str, str]],
    lookback_seconds: int,
    resolution_ms: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    program = signalflow_program(metric, filters)
    events = parse_sse(
        execute_signalflow(
            realm=realm,
            token=token,
            program=program,
            metric=metric,
            lookback_seconds=lookback_seconds,
            resolution_ms=resolution_ms,
            timeout_seconds=timeout_seconds,
        )
    )
    metadata_seen = any(contains_metric(payload, metric) for _, payload in events)
    data_messages = sum(
        1 for event, payload in events if event == "data" and has_data(payload)
    )
    filter_text = ", ".join(f"{key}={REDACTED}" for key, _ in filters) or "<none>"
    if not metadata_seen:
        raise ApiProbeError(
            f"SignalFlow did not return metadata for target {target!r}, metric "
            f"{metric!r}, filters {filter_text}."
        )
    if data_messages < 1:
        raise ApiProbeError(
            f"SignalFlow found metadata but no positive data for target {target!r}, "
            f"metric {metric!r}, filters {filter_text}."
        )
    return {"metadata_seen": True, "data_messages": data_messages, "program": program}


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if (
        args.lookback_seconds <= 0
        or args.resolution_ms <= 0
        or args.timeout_seconds <= 0
    ):
        raise ApiProbeError(
            "lookback, resolution, and timeout must be positive integers."
        )
    metadata = load_metadata(args.metadata)
    realm = args.realm or str(
        metadata.get("realm") or os.environ.get("SPLUNK_O11Y_REALM") or ""
    )
    if realm not in ALLOWED_REALMS:
        raise ApiProbeError(
            f"Splunk Observability realm must be one of {', '.join(sorted(ALLOWED_REALMS))}."
        )
    token_file = args.token_file or os.environ.get("SPLUNK_O11Y_TOKEN_FILE", "")
    global_filters = normalize_global_filters(args.filters)
    probes = (
        normalize_ad_hoc_probes(args.metrics, global_filters)
        if args.metrics
        else normalize_metadata_probes(metadata, global_filters)
    )
    token = token_from_file(token_file)

    results: list[dict[str, Any]] = []
    catalog_cache: dict[str, dict[str, Any]] = {}
    for probe in probes:
        target = probe["target"]
        metric = probe["metric"]
        filters = probe["filters"]
        if metric not in catalog_cache:
            catalog_cache[metric] = metric_catalog_probe(
                realm, token, metric, args.timeout_seconds
            )
        signalflow = signalflow_probe(
            realm,
            token,
            target,
            metric,
            filters,
            args.lookback_seconds,
            args.resolution_ms,
            args.timeout_seconds,
        )
        results.append(
            {
                "target": target,
                "receiver_id": probe["receiver_id"],
                "metric": metric,
                "filters": [{"key": key, "value": REDACTED} for key, _ in filters],
                "metric_catalog": catalog_cache[metric],
                "signalflow": {
                    "metadata_seen": signalflow["metadata_seen"],
                    "data_messages": signalflow["data_messages"],
                },
            }
        )
    print(
        json.dumps(
            {
                "api": "splunk-observability-dbmon",
                "realm": realm,
                "global_filters": [
                    {"key": key, "value": REDACTED} for key, _ in global_filters
                ],
                "probes": results,
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
