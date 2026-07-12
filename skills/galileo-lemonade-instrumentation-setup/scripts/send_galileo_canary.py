#!/usr/bin/env python3
"""Send a redacted agent/LLM canary to a loopback OTLP/HTTP receiver."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


MAX_RESPONSE_BYTES = 1024 * 1024
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Reject redirects so a local canary cannot be forwarded elsewhere."""

    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


def attribute(key: str, value: str | int) -> dict[str, Any]:
    typed = (
        {"intValue": str(value)} if isinstance(value, int) else {"stringValue": value}
    )
    return {"key": key, "value": typed}


def loopback_http(url: str) -> bool:
    try:
        url.encode("utf-8")
    except UnicodeEncodeError:
        return False
    if (
        not url
        or "\\" in url
        or any(character.isspace() or ord(character) == 127 for character in url)
    ):
        return False
    try:
        parsed = urllib.parse.urlparse(url)
        port = parsed.port
    except ValueError:
        return False
    decoded_path = urllib.parse.unquote(parsed.path)
    return bool(
        parsed.scheme == "http"
        and parsed.hostname in LOOPBACK_HOSTS
        and port is not None
        and 1 <= port <= 65535
        and parsed.username is None
        and parsed.password is None
        and not parsed.netloc.endswith(":")
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
        and "?" not in url
        and "#" not in url
        and decoded_path == "/v1/traces"
        and parsed.path == decoded_path
    )


def rejected_span_count(result: dict[str, Any]) -> int:
    counts: list[int] = []
    for container_name in ("partialSuccess", "partial_success"):
        if container_name not in result or result[container_name] is None:
            continue
        partial = result[container_name]
        if not isinstance(partial, dict):
            raise ValueError
        for field_name in ("rejectedSpans", "rejected_spans"):
            if field_name not in partial:
                continue
            raw = partial[field_name]
            if isinstance(raw, bool) or not isinstance(raw, (int, str)):
                raise ValueError
            if isinstance(raw, str) and not raw.isdigit():
                raise ValueError
            count = int(raw)
            if count < 0:
                raise ValueError
            counts.append(count)
    if len(set(counts)) > 1:
        raise ValueError
    return counts[0] if counts else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("client", "server"), default="client")
    parser.add_argument("--endpoint", default="")
    parser.add_argument("--deployment-environment", default="lemonade-dev")
    args = parser.parse_args()
    if not args.endpoint:
        args.endpoint = (
            "http://127.0.0.1:4318/v1/traces"
            if args.mode == "server"
            else "http://127.0.0.1:14318/v1/traces"
        )
    if not loopback_http(args.endpoint):
        parser.error("--endpoint must be a loopback HTTP URL ending in /v1/traces")
    if not 1 <= len(args.deployment_environment) <= 128 or any(
        not (character.isascii() and (character.isalnum() or character in "._-"))
        for character in args.deployment_environment
    ):
        parser.error(
            "--deployment-environment must contain only ASCII letters, numbers, dot, dash, or underscore"
        )

    trace_id = secrets.token_hex(16)
    agent_span_id = secrets.token_hex(8)
    llm_span_id = secrets.token_hex(8)
    tool_span_id = secrets.token_hex(8)
    suffix = secrets.token_hex(4)
    agent_name = f"lemonade-galileo-canary-{suffix}"
    trace_name = f"invoke_agent {agent_name}"
    session_id = agent_name
    created_after = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    started = time.time_ns()
    common = [
        attribute("input.value", "[REDACTED]"),
        attribute("output.value", "[REDACTED]"),
        attribute("gen_ai.provider.name", "lemonade"),
        attribute("session.id", session_id),
        attribute("gen_ai.conversation.id", session_id),
        attribute("galileo.logstream.name", "route-guard-canary"),
        attribute("galileo.experiment.id", "route-guard-canary"),
    ]
    payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        attribute(
                            "service.name",
                            "lemonade-server"
                            if args.mode == "server"
                            else "lemonade-galileo-client",
                        ),
                        attribute(
                            "deployment.environment.name", args.deployment_environment
                        ),
                        attribute("galileo.project.name", "route-guard-canary"),
                        attribute("galileo.dataset.input", "route-guard-canary"),
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {
                            "name": "lemonade.galileo.validation",
                            "version": "1.0.0",
                        },
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": agent_span_id,
                                "name": trace_name,
                                "kind": 1,
                                "startTimeUnixNano": str(started),
                                "endTimeUnixNano": str(started + 120_000_000),
                                "attributes": common
                                + [
                                    attribute("openinference.span.kind", "AGENT"),
                                    attribute("gen_ai.operation.name", "invoke_agent"),
                                    attribute("gen_ai.agent.name", agent_name),
                                ],
                            },
                            {
                                "traceId": trace_id,
                                "spanId": llm_span_id,
                                "parentSpanId": agent_span_id,
                                "name": f"chat lemonade-galileo-canary-{suffix}",
                                "kind": 3,
                                "startTimeUnixNano": str(started + 1_000_000),
                                "endTimeUnixNano": str(started + 100_000_000),
                                "attributes": common
                                + [
                                    attribute("openinference.span.kind", "LLM"),
                                    attribute("gen_ai.operation.name", "chat"),
                                    attribute(
                                        "gen_ai.request.model",
                                        "lemonade-galileo-canary",
                                    ),
                                    attribute(
                                        "gen_ai.response.model",
                                        "lemonade-galileo-canary",
                                    ),
                                    attribute("gen_ai.usage.input_tokens", 4),
                                    attribute("gen_ai.usage.output_tokens", 2),
                                    attribute(
                                        "llm.input_messages.0.message.role", "user"
                                    ),
                                    attribute(
                                        "llm.input_messages.0.message.content",
                                        "[REDACTED]",
                                    ),
                                    attribute(
                                        "llm.output_messages.0.message.role",
                                        "assistant",
                                    ),
                                    attribute(
                                        "llm.output_messages.0.message.content",
                                        "[REDACTED]",
                                    ),
                                ],
                            },
                            {
                                "traceId": trace_id,
                                "spanId": tool_span_id,
                                "parentSpanId": agent_span_id,
                                "name": f"execute_tool privacy-canary-{suffix}",
                                "kind": 1,
                                "startTimeUnixNano": str(started + 101_000_000),
                                "endTimeUnixNano": str(started + 110_000_000),
                                "attributes": common
                                + [
                                    attribute("openinference.span.kind", "TOOL"),
                                    attribute("gen_ai.operation.name", "execute_tool"),
                                    attribute("gen_ai.tool.name", "privacy-canary"),
                                    attribute(
                                        "gen_ai.tool.call.arguments", "[REDACTED]"
                                    ),
                                    attribute("gen_ai.tool.call.result", "[REDACTED]"),
                                ],
                            },
                        ],
                    }
                ],
            }
        ]
    }
    request = urllib.request.Request(
        args.endpoint,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        NoRedirect(),
    )
    try:
        with opener.open(request, timeout=10) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise SystemExit("ERROR: OTLP receiver request failed") from exc
    if len(body) > MAX_RESPONSE_BYTES:
        raise SystemExit("ERROR: OTLP receiver response exceeded the size limit")
    if body:
        try:
            result = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
            raise SystemExit("ERROR: OTLP receiver returned non-JSON content") from exc
        if not isinstance(result, dict):
            raise SystemExit("ERROR: OTLP receiver returned an invalid response shape")
        try:
            rejected_count = rejected_span_count(result)
        except ValueError:
            raise SystemExit(
                "ERROR: OTLP receiver returned an invalid rejection count"
            ) from None
        if rejected_count > 0:
            raise SystemExit("ERROR: OTLP receiver rejected one or more spans")
    print(f"TRACE_ID={trace_id}")
    print(f"TRACE_NAME={trace_name}")
    print(f"SESSION_ID={session_id}")
    print(f"CREATED_AFTER={created_after}")


if __name__ == "__main__":
    main()
