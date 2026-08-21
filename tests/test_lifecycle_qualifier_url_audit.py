#!/usr/bin/env python3
"""Offline regression tests for the lifecycle-qualifier URL drift audit.

The audit itself performs live HTTP and runs on a schedule, so these tests cover
only its pure logic: which URLs come into scope, which are excluded, and how a
fetched result is classified. Keeping this suite network-free is deliberate —
the whole point of the audit's design is that no push gate depends on a remote
documentation site being reachable.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT = REPO_ROOT / "skills/shared/scripts/audit_lifecycle_qualifier_urls.py"


def load_module():
    spec = importlib.util.spec_from_file_location("lifecycle_qualifier_url_audit", AUDIT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def extract(module, line: str) -> list[str]:
    return [module.trim_url(match.group(0)) for match in module.URL_RE.finditer(line)]


# ── URL extraction ───────────────────────────────────────────────────────


def test_markdown_link_yields_the_url_without_the_closing_paren() -> None:
    module = load_module()
    line = "See [the beta page](https://help.splunk.com/en/thing-beta) for details."
    assert extract(module, line) == ["https://help.splunk.com/en/thing-beta"]


def test_parenthesized_url_keeps_balanced_parens_inside_the_path() -> None:
    module = load_module()
    line = "(https://example.invalid/a_(b)_beta)"
    assert extract(module, line) == ["https://example.invalid/a_(b)_beta"]


def test_trailing_sentence_punctuation_is_not_part_of_the_url() -> None:
    module = load_module()
    line = "Read https://help.splunk.com/en/thing-beta."
    assert extract(module, line) == ["https://help.splunk.com/en/thing-beta"]


def test_angle_bracket_delimited_url_excludes_the_brackets() -> None:
    module = load_module()
    line = "<https://help.splunk.com/en/thing-beta>"
    assert extract(module, line) == ["https://help.splunk.com/en/thing-beta"]


def test_url_used_as_markdown_title_and_target_is_extracted_twice_cleanly() -> None:
    module = load_module()
    line = (
        "[https://help.splunk.com/en/thing-beta]"
        "(https://help.splunk.com/en/thing-beta)"
    )
    assert extract(module, line) == [
        "https://help.splunk.com/en/thing-beta",
        "https://help.splunk.com/en/thing-beta",
    ]


# ── Qualifier scoping ────────────────────────────────────────────────────


def test_qualifiers_are_matched_as_whole_tokens_not_substrings() -> None:
    module = load_module()
    assert module.find_qualifiers("https://h.invalid/docs/alphabetical-index") == []
    assert module.find_qualifiers("https://h.invalid/docs/betamaxine") == []
    assert module.find_qualifiers("https://h.invalid/docs/thing-alpha") == ["alpha"]


def test_compound_qualifiers_are_detected() -> None:
    module = load_module()
    for slug, expected in (
        ("early-access-program", "early-access"),
        ("feature-limited-availability", "limited-availability"),
        ("afe-controlled-availability", "controlled-availability"),
    ):
        assert expected in module.find_qualifiers(f"https://h.invalid/docs/{slug}")


def test_preview_is_detected_inside_a_longer_compound_slug() -> None:
    module = load_module()
    url = "https://h.invalid/docs/feature-preview-cisco-deep-time-series-model"
    assert module.find_qualifiers(url) == ["preview"]


def test_a_qualifier_in_the_host_alone_does_not_pull_a_url_into_scope() -> None:
    module = load_module()
    assert module.find_qualifiers("https://beta.example.invalid/docs/index.html") == []


# ── Exclusion classes ────────────────────────────────────────────────────


def test_placeholder_urls_are_excluded() -> None:
    module = load_module()
    for url in (
        "https://{tenant}.example.invalid/docs/thing-beta",
        "https://$REALM.signalfx.invalid/docs/thing-beta",
        "https://help.invalid/.../thing-beta",
        "https://example.com/docs/thing-beta",
    ):
        assert module.exclusion_reason(url) == "placeholder", url


def test_api_endpoints_are_excluded_because_a_bare_get_proves_nothing() -> None:
    module = load_module()
    for url in (
        "https://api.thousandeyes.com/docs/thing-beta",
        "https://ingest.us1.signalfx.com/v2/datapoint/thing-beta",
        "https://stack.splunkcloud.com/services/collector/thing-beta",
        "https://stack.splunkcloud.com/v7/streams/thing-beta",
    ):
        assert module.exclusion_reason(url) == "api-endpoint", url


def test_private_and_non_public_hosts_are_excluded() -> None:
    module = load_module()
    for url in (
        "https://localhost:8000/docs/thing-beta",
        "https://127.0.0.1/docs/thing-beta",
        "https://10.1.2.3/docs/thing-beta",
        "https://192.168.1.10/docs/thing-beta",
        "https://collector.monitoring.svc/docs/thing-beta",
        "https://splunk/docs/thing-beta",
    ):
        assert module.exclusion_reason(url) == "private-host", url


def test_a_public_documentation_url_is_not_excluded() -> None:
    module = load_module()
    url = "https://help.splunk.com/en/product/use-new-dashboard-experience-beta"
    assert module.exclusion_reason(url) is None


# ── Result classification ────────────────────────────────────────────────


def test_redirect_and_dropped_title_qualifier_are_separate_signals() -> None:
    module = load_module()
    record = module.evaluate(
        "https://h.invalid/docs/thing-beta",
        ["beta"],
        {
            "status": 200,
            "effective_url": "https://h.invalid/docs/thing",
            "title": "Thing | Product",
        },
    )
    assert record["state"] == "finding"
    assert record["signals"] == ["redirected", "qualifier_dropped"]
    assert record["dropped_qualifiers"] == ["beta"]


def test_redirect_alone_is_a_finding_even_when_the_title_keeps_the_qualifier() -> None:
    module = load_module()
    record = module.evaluate(
        "https://h.invalid/docs/thing-beta",
        ["beta"],
        {
            "status": 200,
            "effective_url": "https://h.invalid/manual/thing-beta",
            "title": "Thing (Beta) | Product",
        },
    )
    assert record["signals"] == ["redirected"]


def test_dropped_title_qualifier_alone_is_a_finding_without_a_redirect() -> None:
    module = load_module()
    record = module.evaluate(
        "https://h.invalid/docs/thing-beta",
        ["beta"],
        {
            "status": 200,
            "effective_url": "https://h.invalid/docs/thing-beta",
            "title": "Thing | Product",
        },
    )
    assert record["signals"] == ["qualifier_dropped"]


def test_title_qualifier_match_ignores_case_and_punctuation() -> None:
    module = load_module()
    record = module.evaluate(
        "https://h.invalid/docs/thing-early-access",
        ["early-access"],
        {
            "status": 200,
            "effective_url": "https://h.invalid/docs/thing-early-access",
            "title": "Thing (Early Access) | Product",
        },
    )
    assert record["state"] == "ok"


def test_trailing_slash_and_fragment_are_not_treated_as_a_redirect() -> None:
    module = load_module()
    record = module.evaluate(
        "https://h.invalid/docs/thing-beta",
        ["beta"],
        {
            "status": 200,
            "effective_url": "https://h.invalid/docs/thing-beta/#section",
            "title": "Thing Beta | Product",
        },
    )
    assert record["state"] == "ok"


def test_bot_blocked_statuses_are_unverifiable_and_never_findings() -> None:
    module = load_module()
    for status in (401, 403, 405, 406, 429, 503):
        record = module.evaluate(
            "https://h.invalid/docs/thing-beta",
            ["beta"],
            {"status": status, "effective_url": "https://h.invalid/docs/thing-beta"},
        )
        assert record["state"] == "unverifiable", status


def test_transport_failure_is_unverifiable_rather_than_a_finding() -> None:
    module = load_module()
    record = module.evaluate(
        "https://h.invalid/docs/thing-beta",
        ["beta"],
        {
            "status": None,
            "effective_url": "https://h.invalid/docs/thing-beta",
            "title": "",
            "error": "transport failure (curl exit 28)",
        },
    )
    assert record["state"] == "unverifiable"
    assert "curl exit 28" in record["reason"]


def test_a_missing_page_is_reported_as_a_finding() -> None:
    module = load_module()
    record = module.evaluate(
        "https://h.invalid/docs/thing-beta",
        ["beta"],
        {"status": 404, "effective_url": "https://h.invalid/docs/thing-beta"},
    )
    assert record["state"] == "finding"
    assert record["signals"] == ["unreachable"]


def test_an_empty_title_does_not_manufacture_a_dropped_qualifier() -> None:
    module = load_module()
    record = module.evaluate(
        "https://h.invalid/docs/thing-beta",
        ["beta"],
        {
            "status": 200,
            "effective_url": "https://h.invalid/docs/thing-beta",
            "title": "",
        },
    )
    assert record["state"] == "ok"


# ── Wiring ───────────────────────────────────────────────────────────────


def test_only_this_fixture_file_is_exempt_from_the_scan() -> None:
    """The exemption exists for fabricated fixtures; it must not grow silently."""
    module = load_module()
    assert module.FIXTURE_FILES == frozenset(
        {"tests/test_lifecycle_qualifier_url_audit.py"}
    )


def test_audit_runs_on_a_schedule_and_not_in_the_push_gate() -> None:
    """Live HTTP in the per-push job would fail on rate limits and get disabled."""
    drift = (REPO_ROOT / ".github/workflows/catalog-drift.yml").read_text(
        encoding="utf-8"
    )
    ci = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "audit_lifecycle_qualifier_urls.py" in drift
    assert "audit_lifecycle_qualifier_urls.py" not in ci
