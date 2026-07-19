from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import stat
import urllib.error
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT / "skills" / "lemonade-splunk-otel" / "scripts" / "splunk_trace_readback.py"
)
SPEC = importlib.util.spec_from_file_location("splunk_trace_readback", SCRIPT)
assert SPEC and SPEC.loader
READBACK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(READBACK)

TRACE_ID = "0123456789abcdef0123456789abcdef"
SPAN_ID = "0123456789abcdef"
START = "2026-07-11T12:00:01Z"
CREATED_AFTER = "2026-07-11T12:00:00Z"
CREATED_BEFORE = "2026-07-11T12:00:02Z"


class FakeResponse:
    def __init__(
        self,
        document: Any = None,
        *,
        body: bytes | None = None,
        status: int = 200,
        content_type: str = "application/json",
        content_length: str | None = None,
    ) -> None:
        self.status = status
        self.body = (
            json.dumps(document, separators=(",", ":")).encode("utf-8")
            if body is None
            else body
        )
        self.headers: dict[str, str] = {"Content-Type": content_type}
        self.headers["Content-Length"] = (
            str(len(self.body)) if content_length is None else content_length
        )

    def getcode(self) -> int:
        return self.status

    def read(self, limit: int = -1) -> bytes:
        return self.body if limit < 0 else self.body[:limit]

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class FakeOpener:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[Any] = []

    def open(self, request: Any, timeout: float) -> FakeResponse:
        del timeout
        self.requests.append(request)
        if not self.outcomes:
            raise AssertionError("unexpected network request")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeClock:
    def __init__(self) -> None:
        self.value = 10.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.value

    def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.value += delay


def http_error(
    code: int, headers: dict[str, str] | None = None
) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.us0.observability.splunkcloud.com/v2/test",
        code,
        "redacted",
        headers or {},
        None,
    )


def client(
    outcomes: list[Any],
    *,
    clock: FakeClock | None = None,
    max_response_bytes: int = 1024,
) -> tuple[Any, FakeOpener, FakeClock]:
    fake_clock = clock or FakeClock()
    opener = FakeOpener(outcomes)
    instance = READBACK.SplunkApiClient(
        realm="us0",
        token="do-not-print-this-token",
        deadline_seconds=30,
        request_timeout=5,
        opener=opener,
        monotonic=fake_clock.monotonic,
        sleep=fake_clock.sleep,
        wall_clock=lambda: dt.datetime(2026, 7, 11, tzinfo=dt.timezone.utc),
        max_response_bytes=max_response_bytes,
    )
    return instance, opener, fake_clock


def span(
    *,
    trace_id: str = TRACE_ID,
    span_id: str = SPAN_ID,
    service: str = "lemonade-otel-canary",
    operation: str = "chat lemonade-privacy-canary-a1b2c3d4",
    start: str = START,
    extra_tags: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tags: dict[str, Any] = {
        "deployment.environment.name": "production",
        "gen_ai.request.model": "lemonade-privacy-canary",
        "gen_ai.response.model": "lemonade-privacy-canary",
        "gen_ai.provider.name": "lemonade",
        "gen_ai.operation.name": "chat",
        "openinference.span.kind": "LLM",
    }
    tags.update(extra_tags or {})
    return {
        "objectType": "span",
        "traceId": trace_id,
        "spanId": span_id,
        "serviceName": service,
        "operationName": operation,
        "startTime": start,
        "durationMicros": 50_000,
        "tags": tags,
        "processTags": {},
        "logs": [],
    }


def test_client_disables_proxies_and_refuses_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_handlers: list[Any] = []
    opener = FakeOpener([http_error(302)])

    def fake_build_opener(*handlers: Any) -> FakeOpener:
        captured_handlers.extend(handlers)
        return opener

    monkeypatch.setattr(READBACK.urllib.request, "build_opener", fake_build_opener)
    instance = READBACK.SplunkApiClient(
        realm="us0",
        token="do-not-print-this-token",
        deadline_seconds=10,
        request_timeout=2,
    )
    with pytest.raises(READBACK.ReadbackError, match="HTTP 302") as exc_info:
        instance.get_json("/v2/organization", retry_not_found=False)
    assert len(opener.requests) == 1
    assert "do-not-print-this-token" not in str(exc_info.value)
    proxy_handlers = [
        handler
        for handler in captured_handlers
        if isinstance(handler, READBACK.urllib.request.ProxyHandler)
    ]
    assert len(proxy_handlers) == 1
    assert proxy_handlers[0].proxies == {}
    assert any(
        isinstance(handler, READBACK.NoRedirectHandler) for handler in captured_handlers
    )


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (FakeResponse({}, content_length="17"), "size limit"),
        (FakeResponse(body=b"x" * 17, content_length="1"), "size limit"),
        (FakeResponse({}, content_type="text/plain"), "non-JSON"),
        (FakeResponse(body=b""), "empty response"),
        (FakeResponse(body=b"not-json"), "invalid JSON"),
        (FakeResponse(body=b'{"bad":NaN}'), "invalid JSON"),
        (FakeResponse({}, status=201), "HTTP 201"),
        (FakeResponse({}, content_length="bad"), "Content-Length"),
    ],
)
def test_client_rejects_unbounded_or_malformed_responses(
    response: FakeResponse, message: str
) -> None:
    instance, _opener, _clock = client([response], max_response_bytes=16)
    with pytest.raises(READBACK.ReadbackError, match=message):
        instance.get_json("/v2/organization", retry_not_found=False)


def test_client_retries_404_and_429_without_leaking_error_bodies() -> None:
    instance, opener, clock = client(
        [
            http_error(404),
            http_error(429, {"Retry-After": "2"}),
            FakeResponse([123]),
        ]
    )
    assert instance.get_json(
        f"/v2/apm/trace/{TRACE_ID}/segments", retry_not_found=True
    ) == [123]
    assert clock.sleeps == [1.0, 2.0]
    assert len(opener.requests) == 3


def test_retry_after_zero_still_has_a_minimum_delay() -> None:
    instance, _opener, clock = client(
        [http_error(429, {"Retry-After": "0"}), FakeResponse({"id": "org"})]
    )
    assert instance.get_json("/v2/organization", retry_not_found=False) == {"id": "org"}
    assert clock.sleeps == [0.25]


def test_client_does_not_retry_authentication_failures() -> None:
    instance, opener, _clock = client([http_error(403)])
    with pytest.raises(READBACK.ReadbackError, match="HTTP 403") as exc_info:
        instance.get_json("/v2/organization", retry_not_found=False)
    assert len(opener.requests) == 1
    assert "do-not-print-this-token" not in str(exc_info.value)
    assert "redacted" not in str(exc_info.value)


class ScriptedClient:
    def __init__(self, responses: dict[str, list[Any]]) -> None:
        self.responses = {key: list(values) for key, values in responses.items()}
        self.paths: list[str] = []
        self.pauses: list[float] = []

    def get_json(self, path: str, *, retry_not_found: bool) -> Any:
        del retry_not_found
        self.paths.append(path)
        values = self.responses.get(path)
        if not values:
            raise AssertionError(f"unexpected API path: {path}")
        return values.pop(0)

    def pause(self, delay: float, exhausted_message: str) -> None:
        del exhausted_message
        self.pauses.append(delay)


def test_retrieve_all_segments_reads_every_stable_segment() -> None:
    segments_path = f"/v2/apm/trace/{TRACE_ID}/segments"
    first_path = f"/v2/apm/trace/{TRACE_ID}/100"
    second_path = f"/v2/apm/trace/{TRACE_ID}/200"
    scripted = ScriptedClient(
        {
            segments_path: [[200, 100], [100, 200]],
            first_path: [[span()]],
            second_path: [[span(span_id="fedcba9876543210")]],
        }
    )
    segments, spans = READBACK.retrieve_all_segments(scripted, TRACE_ID)
    assert segments == (100, 200)
    assert len(spans) == 2
    assert scripted.paths == [segments_path, first_path, second_path, segments_path]


def test_retrieve_all_segments_polls_http_200_empty_index() -> None:
    segments_path = f"/v2/apm/trace/{TRACE_ID}/segments"
    segment_path = f"/v2/apm/trace/{TRACE_ID}/100"
    scripted = ScriptedClient(
        {
            segments_path: [[], [100], [100]],
            segment_path: [[span()]],
        }
    )
    segments, spans = READBACK.retrieve_all_segments(scripted, TRACE_ID)
    assert segments == (100,)
    assert len(spans) == 1
    assert scripted.pauses == [1.0]


def test_retrieve_all_segments_restarts_if_stability_index_is_empty() -> None:
    segments_path = f"/v2/apm/trace/{TRACE_ID}/segments"
    segment_path = f"/v2/apm/trace/{TRACE_ID}/100"
    scripted = ScriptedClient(
        {
            segments_path: [[100], [], [100], [100]],
            segment_path: [[span()], [span()]],
        }
    )
    segments, spans = READBACK.retrieve_all_segments(scripted, TRACE_ID)
    assert segments == (100,)
    assert len(spans) == 1
    assert scripted.pauses == [1.0]


@pytest.mark.parametrize(
    "document",
    [
        [],
        [True],
        [-1],
        [1, 1],
        ["1"],
    ],
)
def test_segment_index_validation_is_fail_closed(document: Any) -> None:
    with pytest.raises(READBACK.ReadbackError):
        READBACK.parse_segments(document)


def test_documented_api_caps_are_treated_as_possible_truncation() -> None:
    with pytest.raises(READBACK.ReadbackError, match="index might be truncated"):
        READBACK.parse_segments(list(range(READBACK.MAX_TRACE_SEGMENTS)))
    with pytest.raises(READBACK.ReadbackError, match="segment might be truncated"):
        READBACK.parse_spans([span()] * READBACK.MAX_SPANS_PER_SEGMENT, TRACE_ID)


def test_segment_span_validation_rejects_cross_trace_and_duplicates() -> None:
    wrong = span(trace_id="f" * 32)
    with pytest.raises(READBACK.ReadbackError, match="different trace"):
        READBACK.parse_spans([wrong], TRACE_ID)

    segments_path = f"/v2/apm/trace/{TRACE_ID}/segments"
    scripted = ScriptedClient(
        {
            segments_path: [[1, 2], [1, 2]],
            f"/v2/apm/trace/{TRACE_ID}/1": [[span()]],
            f"/v2/apm/trace/{TRACE_ID}/2": [[span()]],
        }
    )
    with pytest.raises(READBACK.ReadbackError, match="duplicate spans"):
        READBACK.retrieve_all_segments(scripted, TRACE_ID)


def test_trace_validation_is_exact_for_identity_time_and_genai_fields() -> None:
    validation = READBACK.validate_trace(
        [span()],
        expected_service="lemonade-otel-canary",
        expected_operation="chat lemonade-privacy-canary-a1b2c3d4",
        created_after=READBACK.parse_timestamp(CREATED_AFTER, "after"),
        created_before=READBACK.parse_timestamp(CREATED_BEFORE, "before"),
        expected_environment="production",
        expected_model="lemonade-privacy-canary",
        expected_provider="lemonade",
        expected_genai_operation="chat",
        expected_openinference_kind="LLM",
    )
    assert validation["matched_span_count"] == 1
    assert validation["duration_micros_min"] == 50_000

    bad_model = span(extra_tags={"gen_ai.response.model": "wrong"})
    with pytest.raises(READBACK.ReadbackError, match="response model"):
        READBACK.validate_trace(
            [bad_model],
            expected_service="lemonade-otel-canary",
            expected_operation="chat lemonade-privacy-canary-a1b2c3d4",
            created_after=READBACK.parse_timestamp(CREATED_AFTER, "after"),
            created_before=READBACK.parse_timestamp(CREATED_BEFORE, "before"),
            expected_environment="production",
            expected_model="lemonade-privacy-canary",
            expected_provider="lemonade",
            expected_genai_operation="chat",
            expected_openinference_kind="LLM",
        )


def test_forbidden_sentinel_scan_covers_nested_keys_and_values() -> None:
    sentinel = "privacy-sentinel-0123456789"
    READBACK.scan_forbidden_content({"safe": ["value"]}, (sentinel,))
    with pytest.raises(READBACK.ReadbackError, match="forbidden content") as exc_info:
        READBACK.scan_forbidden_content(
            {"logs": [{"fields": {"nested": f"prefix-{sentinel}-suffix"}}]},
            (sentinel,),
        )
    assert sentinel not in str(exc_info.value)
    with pytest.raises(READBACK.ReadbackError, match="forbidden content"):
        READBACK.scan_forbidden_content({sentinel: "value"}, (sentinel,))


class RunClient:
    def __init__(self, **_kwargs: Any) -> None:
        self.responses = {
            "/v2/organization": [
                {
                    "id": "org-expected",
                    "organizationName": "must-not-appear",
                    "accountKey": "must-not-appear-either",
                }
            ],
            f"/v2/apm/trace/{TRACE_ID}/segments": [[100], [100]],
            f"/v2/apm/trace/{TRACE_ID}/100": [
                [span(extra_tags={"unreviewed.raw.attribute": "must-not-appear"})]
            ],
        }

    def get_json(self, path: str, *, retry_not_found: bool) -> Any:
        del retry_not_found
        values = self.responses.get(path)
        if not values:
            raise AssertionError(f"unexpected API path: {path}")
        return values.pop(0)

    def pause(self, delay: float, exhausted_message: str) -> None:
        raise AssertionError((delay, exhausted_message))


def private_file(path: Path, value: str) -> Path:
    path.write_text(value + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def run_args(tmp_path: Path) -> argparse.Namespace:
    tmp_path.chmod(0o700)
    return argparse.Namespace(
        realm="us0",
        expected_organization_id="org-expected",
        api_token_file=private_file(tmp_path / "api-token", "secret-api-token"),
        trace_id=TRACE_ID,
        expected_service="lemonade-otel-canary",
        expected_operation="chat lemonade-privacy-canary-a1b2c3d4",
        created_after=CREATED_AFTER,
        created_before=CREATED_BEFORE,
        expected_environment="production",
        expected_model="lemonade-privacy-canary",
        expected_provider="lemonade",
        expected_genai_operation="chat",
        expected_openinference_kind="LLM",
        forbidden_content_file=[
            private_file(tmp_path / "forbidden", "privacy-sentinel-0123456789")
        ],
        deadline_seconds=30.0,
        request_timeout=5.0,
        output=tmp_path / "evidence.json",
    )


def test_run_outputs_only_sanitized_private_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(READBACK, "SplunkApiClient", RunClient)
    args = run_args(tmp_path)
    evidence = READBACK.run(args)
    assert evidence["ok"] is True
    assert evidence["content_privacy"] == "verified"
    assert "organizationName" not in evidence
    rendered = args.output.read_text(encoding="utf-8")
    assert stat.S_IMODE(args.output.stat().st_mode) == 0o600
    for forbidden in (
        "secret-api-token",
        "privacy-sentinel-0123456789",
        "must-not-appear",
        "must-not-appear-either",
        "unreviewed.raw.attribute",
    ):
        assert forbidden not in rendered


def test_token_and_forbidden_files_require_private_single_link_files(
    tmp_path: Path,
) -> None:
    token = private_file(tmp_path / "token", "secret-api-token")
    assert READBACK.read_token_file(token) == "secret-api-token"
    token.chmod(0o644)
    with pytest.raises(READBACK.ReadbackError, match="0600"):
        READBACK.read_token_file(token)

    target = private_file(tmp_path / "target", "secret-api-token")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(READBACK.ReadbackError, match="non-symlink"):
        READBACK.read_token_file(link)

    linked = private_file(tmp_path / "linked", "secret-api-token")
    os.link(linked, tmp_path / "second-link")
    with pytest.raises(READBACK.ReadbackError, match="single-link"):
        READBACK.read_token_file(linked)


def test_output_cannot_replace_a_protected_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(READBACK, "SplunkApiClient", RunClient)
    args = run_args(tmp_path)
    args.output = args.api_token_file
    with pytest.raises(READBACK.ReadbackError, match="protected input"):
        READBACK.run(args)


def test_output_path_requires_a_file_name() -> None:
    with pytest.raises(READBACK.ReadbackError, match="regular evidence file"):
        READBACK.validate_private_output_parent(Path("/"))


def test_parser_has_no_direct_secret_argument() -> None:
    options = READBACK.build_parser()._option_string_actions
    assert "--api-token-file" in options
    assert "--token" not in options
    assert "--api-token" not in options
    assert "--access-token" not in options


@pytest.mark.parametrize(
    "arguments",
    [
        ["--token", "must-not-be-printed"],
        ["--api-token=must-not-be-printed"],
        ["--splunk-access-token", "must-not-be-printed"],
    ],
)
def test_direct_secret_arguments_are_rejected_without_echo(
    arguments: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert READBACK.main(arguments) == 1
    captured = capsys.readouterr()
    assert "use --api-token-file" in captured.err
    assert "must-not-be-printed" not in captured.err


def test_unknown_arguments_are_rejected_without_echo(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        READBACK.main(["--unknown-option", "must-not-be-printed"])
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "invalid command-line arguments" in captured.err
    assert "must-not-be-printed" not in captured.err


def test_readback_script_is_executable() -> None:
    assert SCRIPT.stat().st_mode & stat.S_IXUSR
