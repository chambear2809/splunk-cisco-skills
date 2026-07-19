#!/usr/bin/env python3
"""Privacy-first caller instrumentation for a discovered Lemonade base URL."""

from __future__ import annotations

import argparse
import datetime as dt
import inspect
import ipaddress
import os
import stat
import urllib.parse
from pathlib import Path

DEPENDENCY_ERROR = ""
try:
    import httpx
    import requests
    from openai import OpenAI
    from openinference.instrumentation import TraceConfig
    from openinference.instrumentation.openai import OpenAIInstrumentor
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
except ImportError as exc:
    DEPENDENCY_ERROR = getattr(exc, "name", None) or "required package"
    httpx = requests = OpenAI = TraceConfig = OpenAIInstrumentor = None
    trace = OTLPSpanExporter = Resource = TracerProvider = BatchSpanProcessor = None


MAX_SECRET_BYTES = 64 * 1024
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


if requests is not None:

    class NoRedirectSession(requests.Session):
        """A requests session that ignores ambient proxies and rejects redirects."""

        def __init__(self) -> None:
            super().__init__()
            self.trust_env = False

        def request(self, method: str, url: str, **kwargs: object) -> requests.Response:
            kwargs["allow_redirects"] = False
            return super().request(method, url, **kwargs)

else:

    class NoRedirectSession:  # pragma: no cover - dependency error path only.
        def __init__(self) -> None:
            raise RuntimeError("client dependencies are unavailable")


def required(name: str) -> str:
    raw_value = os.environ.get(name, "")
    value = raw_value.strip()
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError:
        size = 1025
    if (
        not value
        or value != raw_value
        or size > 1024
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise SystemExit(f"ERROR: set {name} after discovering the live endpoint")
    return value


def lemonade_api_key() -> str:
    if "LEMONADE_API_KEY" in os.environ:
        raise SystemExit(
            "ERROR: use LEMONADE_API_KEY_FILE instead of an inline environment key"
        )
    raw_path_value = os.environ.get("LEMONADE_API_KEY_FILE", "")
    raw_path = raw_path_value.strip()
    if not raw_path:
        return "lemonade"
    if raw_path != raw_path_value:
        raise SystemExit("ERROR: LEMONADE_API_KEY_FILE must not have outer whitespace")
    path = Path(raw_path)
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise SystemExit(
            "ERROR: LEMONADE_API_KEY_FILE is not a readable regular file"
        ) from None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise SystemExit(
                "ERROR: LEMONADE_API_KEY_FILE must be a single-link regular file"
            )
        if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
            raise SystemExit(
                "ERROR: LEMONADE_API_KEY_FILE must be owned by the current user"
            )
        if (
            stat.S_IMODE(info.st_mode) & 0o077
            or not 1 <= info.st_size <= MAX_SECRET_BYTES
        ):
            raise SystemExit(
                "ERROR: LEMONADE_API_KEY_FILE must be nonempty and mode 0600"
            )
        chunks: list[bytes] = []
        remaining = MAX_SECRET_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 8192))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(descriptor)
        if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ) or len(data) != info.st_size:
            raise SystemExit(
                "ERROR: LEMONADE_API_KEY_FILE changed or was not read completely"
            )
    finally:
        os.close(descriptor)
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        raise SystemExit(
            "ERROR: LEMONADE_API_KEY_FILE must contain UTF-8 text"
        ) from None
    if (
        len(lines) != 1
        or not lines[0]
        or any(ord(character) < 32 or ord(character) == 127 for character in lines[0])
    ):
        raise SystemExit("ERROR: LEMONADE_API_KEY_FILE must contain exactly one line")
    return lines[0]


def valid_network_host(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        labels = host.rstrip(".").split(".")
        return (
            len(host.rstrip(".")) <= 253
            and bool(labels)
            and all(
                label
                and len(label) <= 63
                and label[0].isascii()
                and label[0].isalnum()
                and label[-1].isascii()
                and label[-1].isalnum()
                and all(
                    character.isascii() and (character.isalnum() or character == "-")
                    for character in label
                )
                for label in labels
            )
        )


def parsed_url(value: str, label: str) -> urllib.parse.ParseResult:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise SystemExit(f"ERROR: {label} contains unsafe URL characters") from None
    if (
        not value
        or "\\" in value
        or any(character.isspace() or ord(character) == 127 for character in value)
    ):
        raise SystemExit(f"ERROR: {label} contains unsafe URL characters")
    try:
        parsed = urllib.parse.urlparse(value)
        port = parsed.port
    except ValueError:
        raise SystemExit(f"ERROR: {label} contains an invalid port") from None
    if not parsed.hostname or not valid_network_host(parsed.hostname):
        raise SystemExit(f"ERROR: {label} contains an invalid hostname")
    if port is not None and not 1 <= port <= 65535:
        raise SystemExit(f"ERROR: {label} contains an invalid port")
    decoded_path = urllib.parse.unquote(parsed.path)
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.netloc.endswith(":")
        or parsed.params
        or parsed.query
        or parsed.fragment
        or "?" in value
        or "#" in value
        or parsed.path != decoded_path
    ):
        raise SystemExit(
            f"ERROR: {label} must not contain credentials or URL modifiers"
        )
    return parsed


def validate_urls(lemonade_base_url: str, otlp_endpoint: str) -> None:
    lemonade = parsed_url(lemonade_base_url, "LEMONADE_BASE_URL")
    lemonade_loopback = lemonade.hostname in LOOPBACK_HOSTS
    if (
        lemonade.scheme not in {"http", "https"}
        or lemonade.path not in {"/v1", "/v1/", "/api/v1", "/api/v1/"}
        or (lemonade.scheme == "http" and not lemonade_loopback)
        or (lemonade.scheme == "http" and lemonade.port is None)
    ):
        raise SystemExit(
            "ERROR: LEMONADE_BASE_URL must be credential-free and HTTPS unless loopback"
        )
    otlp = parsed_url(otlp_endpoint, "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    if (
        otlp.scheme != "http"
        or otlp.hostname not in LOOPBACK_HOSTS
        or otlp.port is None
        or otlp.path != "/v1/traces"
    ):
        raise SystemExit(
            "ERROR: caller OTLP endpoint must be the loopback client receiver"
        )


def hardened_otlp_exporter(
    endpoint: str, session: requests.Session
) -> OTLPSpanExporter:
    try:
        supports_session = "session" in inspect.signature(OTLPSpanExporter).parameters
    except (TypeError, ValueError):
        supports_session = False
    if not supports_session:
        raise SystemExit(
            "ERROR: installed OTLP exporter does not support hardened HTTP sessions"
        )
    try:
        return OTLPSpanExporter(endpoint=endpoint, session=session)
    except (TypeError, ValueError):
        raise SystemExit(
            "ERROR: failed to initialize the hardened OTLP exporter"
        ) from None


def local_privacy_check(lemonade_base_url: str) -> bool:
    """Example local tool whose execution is represented by a TOOL span."""
    return urllib.parse.urlparse(lemonade_base_url).scheme in {"http", "https"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate URLs, protected key handling, dependencies, and hardened transports only",
    )
    args = parser.parse_args()
    if DEPENDENCY_ERROR:
        raise SystemExit(
            "ERROR: install skills/galileo-lemonade-instrumentation-setup/assets/"
            "lemonade_openinference_client.requirements.txt in an isolated "
            f"environment (missing {DEPENDENCY_ERROR})"
        )
    lemonade_base_url = required("LEMONADE_BASE_URL")
    deployment_environment = required("LEMONADE_DEPLOYMENT_ENVIRONMENT")
    model = required("LEMONADE_MODEL")
    otlp_endpoint = os.environ.get(
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        "http://127.0.0.1:14318/v1/traces",
    )
    validate_urls(lemonade_base_url, otlp_endpoint)
    api_key = lemonade_api_key()
    with (
        httpx.Client(
            timeout=30.0, trust_env=False, follow_redirects=False
        ) as http_client,
        NoRedirectSession() as otel_session,
    ):
        exporter = hardened_otlp_exporter(otlp_endpoint, otel_session)
        if args.check:
            exporter.shutdown()
            print("Hardened Lemonade/OpenInference client preflight passed")
            return
        provider: TracerProvider | None = None
        try:
            provider = TracerProvider(
                resource=Resource.create(
                    {
                        "service.name": "lemonade-galileo-client",
                        "deployment.environment.name": deployment_environment,
                    }
                )
            )
            provider.add_span_processor(BatchSpanProcessor(exporter))
            trace.set_tracer_provider(provider)
            OpenAIInstrumentor().instrument(
                tracer_provider=provider,
                config=TraceConfig(
                    hide_inputs=True,
                    hide_outputs=True,
                    hide_input_messages=True,
                    hide_output_messages=True,
                    hide_input_images=True,
                    hide_input_text=True,
                    hide_output_text=True,
                    hide_llm_invocation_parameters=True,
                    hide_llm_tools=True,
                    hide_embedding_vectors=True,
                    hide_embeddings_vectors=True,
                    hide_embeddings_text=True,
                    hide_prompts=True,
                    hide_choices=True,
                    enable_genai_semconv=False,
                ),
            )

            client = OpenAI(
                base_url=lemonade_base_url,
                api_key=api_key,
                timeout=30.0,
                max_retries=0,
                http_client=http_client,
            )
        except SystemExit:
            if provider is not None:
                provider.shutdown()
            raise
        except Exception:
            if provider is not None:
                provider.shutdown()
            raise SystemExit(
                "ERROR: failed to initialize the instrumented client"
            ) from None
        tracer = trace.get_tracer("lemonade.galileo.example")
        flushed = False
        shutdown_cleanly = True
        request_failed = False
        trace_id = ""
        created_after = (
            dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        )
        try:
            with tracer.start_as_current_span(
                "invoke_agent lemonade-canary",
                attributes={
                    "openinference.span.kind": "AGENT",
                    "input.value": "[REDACTED]",
                    "output.value": "[REDACTED]",
                    "gen_ai.operation.name": "invoke_agent",
                    "gen_ai.agent.name": "lemonade-canary",
                    "gen_ai.provider.name": "lemonade",
                    "gen_ai.request.model": model,
                    "gen_ai.response.model": model,
                },
            ) as agent_span:
                trace_id = f"{agent_span.get_span_context().trace_id:032x}"
                with tracer.start_as_current_span(
                    "execute_tool local-privacy-check",
                    attributes={
                        "openinference.span.kind": "TOOL",
                        "input.value": "[REDACTED]",
                        "output.value": "[REDACTED]",
                        "gen_ai.operation.name": "execute_tool",
                        "gen_ai.provider.name": "lemonade",
                        "gen_ai.tool.name": "local-privacy-check",
                        "gen_ai.tool.call.arguments": "[REDACTED]",
                        "gen_ai.tool.call.result": "[REDACTED]",
                    },
                ):
                    if not local_privacy_check(lemonade_base_url):
                        raise RuntimeError("local privacy check failed")
                client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "user", "content": "Reply with only: canary-ok"}
                    ],
                    temperature=0,
                )
        except Exception:  # The collector records a redacted exception.
            request_failed = True
        finally:
            try:
                flushed = provider.force_flush(timeout_millis=10_000)
            except Exception:
                flushed = False
            try:
                provider.shutdown()
            except Exception:
                shutdown_cleanly = False
            try:
                client.close()
            except Exception:
                shutdown_cleanly = False
        if not flushed:
            raise SystemExit("ERROR: OpenTelemetry force_flush timed out")
        if not shutdown_cleanly:
            raise SystemExit(
                "ERROR: instrumented client shutdown did not complete cleanly"
            )
        if request_failed:
            raise SystemExit(
                "ERROR: Lemonade canary request failed; inspect protected local logs"
            )
        if len(trace_id) != 32 or not all(
            character in "0123456789abcdef" for character in trace_id
        ):
            raise SystemExit("ERROR: instrumented client did not produce a trace ID")
        created_before = (
            dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        )
    print("Privacy-safe Lemonade caller canary completed")
    print(f"TRACE_ID={trace_id}")
    print("TRACE_NAME=invoke_agent lemonade-canary")
    print(f"CREATED_AFTER={created_after}")
    print(f"CREATED_BEFORE={created_before}")


if __name__ == "__main__":
    main()
