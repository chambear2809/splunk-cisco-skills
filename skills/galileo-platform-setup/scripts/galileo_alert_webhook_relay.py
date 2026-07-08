#!/usr/bin/env python3
"""Receive Galileo alert webhooks and forward them to Splunk HEC.

Galileo's generic webhook token mode sends a Bearer authorization scheme while
Splunk HEC expects its distinct Splunk authorization scheme. This small relay validates the
Galileo bearer token from a local file, preserves the v1.0 alert payload, and
wraps it in a Splunk HEC event without putting either credential on argv.
"""

from __future__ import annotations

import argparse
import hmac
import ipaddress
import json
import ssl
import stat
import sys
import urllib.error
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


MAX_BODY_BYTES = 1_048_576
DIRECT_SECRET_FLAGS = {
    "--access-token",
    "--api-key",
    "--api-token",
    "--authorization",
    "--bearer-token",
    "--galileo-api-key",
    "--galileo-webhook-token",
    "--hec-token",
    "--o11y-token",
    "--password",
    "--sf-token",
    "--splunk-hec-token",
    "--token",
}


def reject_direct_secret_flags(argv: list[str]) -> None:
    for arg in argv:
        name = arg.split("=", 1)[0]
        if name in DIRECT_SECRET_FLAGS:
            raise SystemExit(
                "ERROR: Direct secret flags are not accepted. Use "
                "--galileo-webhook-token-file and --splunk-hec-token-file."
            )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    values = list(sys.argv[1:] if argv is None else argv)
    reject_direct_secret_flags(values)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=8787)
    parser.add_argument("--path", default="/galileo/alerts")
    parser.add_argument("--galileo-webhook-token-file", required=True)
    parser.add_argument("--splunk-hec-url", required=True)
    parser.add_argument("--splunk-hec-token-file", required=True)
    parser.add_argument("--splunk-index", default="galileo")
    parser.add_argument("--splunk-source", default="galileo-alert-webhook")
    parser.add_argument("--splunk-sourcetype", default="galileo:alert:webhook:json")
    parser.add_argument("--splunk-host", default="")
    parser.add_argument("--ca-file", default="")
    parser.add_argument("--allow-insecure-hec-http", action="store_true")
    parser.add_argument("--max-body-bytes", type=int, default=MAX_BODY_BYTES)
    parser.add_argument(
        "--allow-public-http-listener",
        action="store_true",
        help="Allow a reviewed non-loopback listener behind an operator-managed HTTPS proxy.",
    )
    return parser.parse_args(values)


def read_secret_file(path: str, label: str) -> str:
    secret_path = Path(path).expanduser()
    if not secret_path.is_file():
        raise RuntimeError(f"{label} is not readable: {secret_path}")
    mode = stat.S_IMODE(secret_path.stat().st_mode)
    if mode & 0o077:
        raise RuntimeError(
            f"{label} permissions must be 0600 or stricter: {secret_path} has {mode:04o}"
        )
    value = secret_path.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"{label} is empty: {secret_path}")
    return value


def normalize_hec_url(value: str, *, allow_insecure_http: bool = False) -> str:
    try:
        parsed = urlparse(value)
        _ = parsed.port
    except ValueError as exc:
        raise RuntimeError("Splunk HEC URL is invalid") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError("Splunk HEC URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise RuntimeError("Splunk HEC URL must not contain credentials")
    if parsed.params or parsed.query or parsed.fragment:
        raise RuntimeError("Splunk HEC URL must not contain params, query, or fragment")
    loopback = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
    if parsed.scheme != "https" and not loopback and not allow_insecure_http:
        raise RuntimeError(
            "Splunk HEC URL must use HTTPS unless it is loopback or "
            "--allow-insecure-hec-http was explicitly reviewed"
        )
    path = parsed.path.rstrip("/")
    if path in {"", "/"}:
        path = "/services/collector/event"
    elif path.endswith("/services/collector"):
        path += "/event"
    elif not path.endswith("/services/collector/event"):
        raise RuntimeError(
            "Splunk HEC URL path must be empty, /services/collector, or "
            "/services/collector/event"
        )
    return parsed._replace(path=path).geturl()


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects so the Splunk authorization header stays on one origin."""

    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def open_without_redirect(
    request: urllib.request.Request,
    *,
    timeout: float,
    context: ssl.SSLContext | None,
) -> Any:
    handlers: list[Any] = [NoRedirectHandler()]
    if context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=context))
    return urllib.request.build_opener(*handlers).open(request, timeout=timeout)


def epoch_timestamp(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def validate_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    if payload.get("version") != "1.0":
        raise ValueError("unsupported or missing Galileo webhook version")
    event_type = payload.get("event")
    if not isinstance(event_type, str) or not event_type.startswith("alert."):
        raise ValueError("missing Galileo alert event type")
    for key in ("event_id", "timestamp", "dedup_key"):
        if not isinstance(payload.get(key), str) or not payload[key].strip():
            raise ValueError(f"missing Galileo webhook field: {key}")
    alert = payload.get("alert")
    if not isinstance(alert, dict):
        raise ValueError("missing Galileo alert object")
    for key in ("id", "name", "status"):
        if not isinstance(alert.get(key), str) or not alert[key].strip():
            raise ValueError(f"missing Galileo alert field: {key}")
    scope = payload.get("scope")
    if not isinstance(scope, dict):
        raise ValueError("missing Galileo scope object")
    for key in ("project_id", "log_stream_id"):
        if not isinstance(scope.get(key), str) or not scope[key].strip():
            raise ValueError(f"missing Galileo scope field: {key}")
    conditions = payload.get("conditions")
    if not isinstance(conditions, list) or not conditions:
        raise ValueError("missing Galileo conditions array")
    for index, condition in enumerate(conditions):
        if not isinstance(condition, dict):
            raise ValueError(f"Galileo condition {index} must be an object")
        for key in ("metric", "aggregation", "operator"):
            if not isinstance(condition.get(key), str) or not condition[key].strip():
                raise ValueError(f"missing Galileo condition field: {key}")
        for key in ("threshold", "observed_value"):
            value = condition.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"Galileo condition field {key} must be numeric")
    if "metadata" in payload and not isinstance(payload["metadata"], dict):
        raise ValueError("Galileo metadata must be an object")
    return payload


def validate_listener(host: str, *, allow_public: bool) -> None:
    normalized = host.strip().lower()
    try:
        loopback = ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        loopback = normalized == "localhost" or normalized.endswith(".localhost")
    if not loopback and not allow_public:
        raise RuntimeError(
            "Non-loopback relay listeners require --allow-public-http-listener and an "
            "operator-managed HTTPS reverse proxy"
        )


def build_hec_envelope(payload: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    alert = payload.get("alert") or {}
    scope = payload.get("scope") or {}
    envelope: dict[str, Any] = {
        "source": args.splunk_source,
        "sourcetype": args.splunk_sourcetype,
        "index": args.splunk_index,
        "fields": {
            "galileo_alert_event_id": str(payload.get("event_id") or ""),
            "galileo_alert_event_type": str(payload.get("event") or ""),
            "galileo_alert_dedup_key": str(payload.get("dedup_key") or ""),
            "galileo_alert_id": str(alert.get("id") or ""),
            "galileo_alert_status": str(alert.get("status") or ""),
            "galileo_project_id": str(scope.get("project_id") or ""),
            "galileo_log_stream_id": str(scope.get("log_stream_id") or ""),
        },
        "event": payload,
    }
    event_time = epoch_timestamp(payload.get("timestamp"))
    if event_time is not None:
        envelope["time"] = event_time
    if args.splunk_host:
        envelope["host"] = args.splunk_host
    return envelope


def send_to_hec(
    envelope: dict[str, Any],
    *,
    hec_url: str,
    hec_token: str,
    ca_file: str,
) -> None:
    data = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        hec_url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Splunk {hec_token}",
            "Content-Type": "application/json",
            "User-Agent": "galileo-platform-setup-alert-relay/1.0",
        },
    )
    context = None
    if ca_file:
        context = ssl.create_default_context(cafile=str(Path(ca_file).expanduser()))
    try:
        with open_without_redirect(request, timeout=15, context=context) as response:
            body = response.read(65_536)
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"Splunk HEC returned HTTP {response.status}")
            if not body:
                raise RuntimeError("Splunk HEC returned an empty response")
            try:
                parsed = json.loads(body.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise RuntimeError("Splunk HEC returned a non-JSON response") from exc
            if not isinstance(parsed, dict) or parsed.get("code") != 0:
                code = parsed.get("code") if isinstance(parsed, dict) else None
                raise RuntimeError(f"Splunk HEC rejected event with code {code}")
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            raise RuntimeError(
                f"Splunk HEC returned HTTP {exc.code}; redirects are disabled"
            ) from exc
        raise RuntimeError(f"Splunk HEC returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Splunk HEC request failed: {exc.reason}") from exc


def make_handler(
    args: argparse.Namespace,
    *,
    webhook_token: str,
    hec_token: str,
    hec_url: str,
) -> type[BaseHTTPRequestHandler]:
    expected_path = "/" + args.path.strip("/")

    class GalileoAlertHandler(BaseHTTPRequestHandler):
        server_version = "GalileoAlertWebhookRelay/1.0"

        def _json_response(self, status: int, body: dict[str, Any]) -> None:
            encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
            if self.path.split("?", 1)[0] != expected_path:
                self._json_response(404, {"error": "not_found"})
                return
            supplied = self.headers.get("Authorization", "")
            expected = f"Bearer {webhook_token}"
            if not hmac.compare_digest(supplied, expected):
                self._json_response(401, {"error": "unauthorized"})
                return
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._json_response(400, {"error": "invalid_content_length"})
                return
            if content_length <= 0 or content_length > args.max_body_bytes:
                self._json_response(413, {"error": "payload_size_rejected"})
                return
            try:
                payload = validate_payload(json.loads(self.rfile.read(content_length)))
                envelope = build_hec_envelope(payload, args)
                send_to_hec(
                    envelope,
                    hec_url=hec_url,
                    hec_token=hec_token,
                    ca_file=args.ca_file,
                )
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                self._json_response(400, {"error": "invalid_payload", "detail": str(exc)})
                return
            except RuntimeError:
                self._json_response(502, {"error": "hec_delivery_failed"})
                return
            self._json_response(
                200,
                {
                    "accepted": True,
                    "event_id": payload["event_id"],
                    "dedup_key": payload["dedup_key"],
                },
            )

        def log_message(self, format: str, *values: Any) -> None:
            # Do not log request headers or bodies; the default line is enough.
            sys.stderr.write("galileo-alert-relay: " + format % values + "\n")

    return GalileoAlertHandler


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        validate_listener(
            args.listen_host,
            allow_public=args.allow_public_http_listener,
        )
        webhook_token = read_secret_file(
            args.galileo_webhook_token_file, "Galileo webhook token file"
        )
        hec_token = read_secret_file(args.splunk_hec_token_file, "Splunk HEC token file")
        hec_url = normalize_hec_url(
            args.splunk_hec_url,
            allow_insecure_http=args.allow_insecure_hec_http,
        )
    except RuntimeError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    handler = make_handler(
        args,
        webhook_token=webhook_token,
        hec_token=hec_token,
        hec_url=hec_url,
    )
    server = ThreadingHTTPServer((args.listen_host, args.listen_port), handler)
    print(
        f"Galileo alert relay listening on http://{args.listen_host}:{args.listen_port}"
        f"/{args.path.strip('/')}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
