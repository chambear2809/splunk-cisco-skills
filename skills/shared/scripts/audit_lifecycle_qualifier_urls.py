#!/usr/bin/env python3
"""Detect vendor lifecycle drift behind documentation URLs that still return 200.

A plain link check cannot catch the failure mode this repository keeps hitting.
When a vendor promotes a feature out of preview, the old slug keeps working: it
301s to a page with the lifecycle qualifier stripped from both the slug and the
title. The link is "alive", so a link checker is satisfied, while every claim the
skill makes about that feature's release stage has quietly gone stale.

Three real instances motivated this audit:

    feature-preview-cisco-deep-time-series-model -> cisco-deep-time-series-model
    use-new-dashboard-experience-beta            -> use-new-dashboard-experience
    use-modern-dashboards/...                    -> restructured parent

This audit is deliberately scoped to URLs whose path already claims a lifecycle
stage. A repository-wide sweep found 177 in-scope URLs that redirect for benign
reasons (the bulk docs.splunk.com -> help.splunk.com migration, patch-to-minor
version collapses). Failing on every redirect would report 177 findings on day
one and be switched off in a week, so only qualifier-bearing paths are checked.

Two independent signals are reported, because they fail in different ways:

    redirected        the requested URL is not the effective URL
    qualifier_dropped the resolved <title> no longer carries the qualifier

Either one means the vendor probably moved the feature to a new release stage.
The redirect is only the symptom; the stale lifecycle claim is the defect.

This performs live HTTP and therefore belongs in scheduled drift detection, not
in a push gate. Rate limits, transient failures, and bot-blocking would make a
per-push job flaky enough that people learn to ignore it. Hosts that refuse
automated clients (403/429) are reported as unverifiable and never fail the run.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import html
import ipaddress
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
USER_AGENT = "splunk-cisco-skills/lifecycle-qualifier-url-audit"

DEFAULT_MAX_WORKERS = 12
DEFAULT_TIMEOUT_SECONDS = 20
# Enough of the document to reach </title> without downloading whole manuals.
MAX_BODY_BYTES = 262_144
MAX_DOWNLOAD_BYTES = 8_000_000

# Lifecycle qualifiers that a vendor strips when a feature changes stage.
# Matched as whole hyphen-delimited tokens, so "alpha" does not fire on
# "alphabetical" and "preview" still fires inside "tech-preview" or
# "feature-preview-..." because the hyphen is a token boundary.
LIFECYCLE_QUALIFIERS = (
    "preview",
    "beta",
    "alpha",
    "early-access",
    "limited-availability",
    "controlled-availability",
)

URL_RE = re.compile(r"https?://[^\s<>\[\]\"'`\\|]+")
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

# Template markers. A URL carrying one of these is a fill-in-the-blank example,
# not a page that can be fetched.
PLACEHOLDER_MARKERS = ("{", "}", "$", "...", "%s", "%d", "%(")
PLACEHOLDER_HOSTS = ("example.com", "example.org", "example.net", "example")

# API surfaces answer a bare GET with 401/404 by design, so a non-200 there says
# nothing about a feature's lifecycle stage.
API_HOST_PREFIXES = ("api.", "ingest.", "rum-ingest.", "alert.", "app.")
API_HOST_SUFFIXES = (".signalfx.com",)
API_PATH_PREFIXES = (
    "/api/",
    "/rest/",
    "/graphql",
    "/mcp",
    "/oauth",
    "/services/",
    "/servicesns/",
    "/token",
    "/v1/",
    "/v2/",
    "/v3/",
    "/v4/",
    "/v5/",
    "/v6/",
    "/v7/",
)

PRIVATE_HOST_NAMES = ("localhost", "localhost.localdomain")
PRIVATE_HOST_SUFFIXES = (
    ".local",
    ".localdomain",
    ".internal",
    ".intranet",
    ".lan",
    ".svc",
    ".svc.cluster.local",
    ".cluster.local",
    ".test",
    ".invalid",
)

# Bot protection, not evidence. Reported separately, never failed on.
UNVERIFIABLE_STATUSES = frozenset({401, 403, 405, 406, 429})

SKIP_PATH_PARTS = frozenset({".git", "__pycache__", "node_modules", ".venv"})

# This audit's own test file exists to hold fabricated qualifier URLs. Auditing
# them would report the fixtures as dead documentation on every run. No other
# file is exempt: a real URL cited in a test is still a claim worth checking.
FIXTURE_FILES = frozenset({"tests/test_lifecycle_qualifier_url_audit.py"})


def normalize_tokens(value: str) -> str:
    """Collapse a URL path or page title to hyphen-delimited lowercase tokens."""
    return re.sub(r"[^a-z0-9]+", "-", value.lower())


def qualifier_pattern(qualifier: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![a-z0-9]){re.escape(qualifier)}(?![a-z0-9])")


QUALIFIER_PATTERNS = {q: qualifier_pattern(q) for q in LIFECYCLE_QUALIFIERS}


def trim_url(raw: str) -> str:
    """Strip trailing delimiters a URL picked up from surrounding markup.

    Markdown links are the reason this exists. Extracting on `](` splits the URL
    and manufactures dead-link findings, so the URL is matched whole and then
    unbalanced closers and sentence punctuation are peeled off the end.
    """
    url = raw
    while url:
        if url.endswith(")") and url.count("(") < url.count(")"):
            url = url[:-1]
        elif url.endswith("]") and url.count("[") < url.count("]"):
            url = url[:-1]
        elif url[-1] in "'\"`>,.;:!?*_":
            url = url[:-1]
        else:
            break
    return url


def safe_urlsplit(url: str) -> urllib.parse.SplitResult | None:
    """Parse a URL, returning None for text that only looked like one.

    Documentation prose and rendered examples contain fragments that match the
    URL regex but are not parseable (unbalanced brackets read as IPv6 literals),
    and a crash there would take down the whole audit.
    """
    try:
        return urllib.parse.urlsplit(url)
    except ValueError:
        return None


def find_qualifiers(url: str) -> list[str]:
    """Return the lifecycle qualifiers claimed by the URL path (not the host)."""
    parsed = safe_urlsplit(url)
    if parsed is None:
        return []
    scope = normalize_tokens(f"{parsed.path} {parsed.query}")
    return [q for q, pattern in QUALIFIER_PATTERNS.items() if pattern.search(scope)]


def exclusion_reason(url: str) -> str | None:
    """Classify URLs that cannot yield lifecycle evidence, or None to check it."""
    lowered = url.lower()
    if any(marker in url for marker in PLACEHOLDER_MARKERS):
        return "placeholder"

    parsed = safe_urlsplit(lowered)
    if parsed is None:
        return "placeholder"
    host = parsed.hostname or ""
    if not host:
        return "placeholder"
    if host in PLACEHOLDER_HOSTS or any(
        host == h or host.endswith(f".{h}") for h in PLACEHOLDER_HOSTS
    ):
        return "placeholder"

    if host in PRIVATE_HOST_NAMES:
        return "private-host"
    if any(host.endswith(suffix) for suffix in PRIVATE_HOST_SUFFIXES):
        return "private-host"
    if "." not in host:
        return "private-host"
    try:
        if ipaddress.ip_address(host).is_global is False:
            return "private-host"
    except ValueError:
        pass

    if host.startswith(API_HOST_PREFIXES) or host.endswith(API_HOST_SUFFIXES):
        return "api-endpoint"
    path = parsed.path or "/"
    if any(path.startswith(prefix) for prefix in API_PATH_PREFIXES):
        return "api-endpoint"

    return None


def iter_tracked_files(root: Path) -> list[Path]:
    """Prefer git-known files; fall back to a filtered walk outside a checkout.

    Untracked-but-not-ignored files are included so a URL added in the working
    tree is audited before it is committed, while ignored build and rendered
    output stays out of scope.
    """
    try:
        completed = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return [
            path
            for path in sorted(root.rglob("*"))
            if path.is_file()
            and not SKIP_PATH_PARTS.intersection(path.relative_to(root).parts)
        ]
    names = [name for name in completed.stdout.split("\0") if name]
    return [root / name for name in names if (root / name).is_file()]


def collect_occurrences(root: Path) -> dict[str, list[dict[str, Any]]]:
    """Map each qualifier-bearing URL to every file and line that cites it."""
    occurrences: dict[str, list[dict[str, Any]]] = {}
    for path in iter_tracked_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "http" not in text:
            continue
        relative = path.relative_to(root).as_posix()
        if relative in FIXTURE_FILES:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for match in URL_RE.finditer(line):
                url = trim_url(match.group(0))
                if not url or not find_qualifiers(url):
                    continue
                occurrences.setdefault(url, []).append(
                    {"file": relative, "line": line_number}
                )
    return occurrences


def extract_title(body: bytes) -> str:
    match = TITLE_RE.search(body.decode("utf-8", errors="ignore"))
    if not match:
        return ""
    return html.unescape(" ".join(match.group(1).split()))


def canonicalize(url: str) -> str:
    """Normalize away differences that are not lifecycle drift.

    Fragments never reach the server and a bare trailing slash is the same
    resource, so neither should be reported as a redirect.
    """
    parsed = safe_urlsplit(url)
    if parsed is None:
        return url
    path = parsed.path.rstrip("/") or "/"
    host = (parsed.hostname or "").lower()
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urllib.parse.urlunsplit((parsed.scheme.lower(), host, path, parsed.query, ""))


def probe(url: str, timeout: int) -> dict[str, Any]:
    """Fetch a URL through curl, following redirects, recording where it landed.

    curl rather than urllib because the documentation CDNs fingerprint the
    client below the User-Agent: help.splunk.com answers 403 to every urllib
    request no matter which User-Agent it sends, and 200 to curl. Verifying
    nothing would be worse than shelling out.

    Redirects are restricted to https so a hijacked hop cannot downgrade the
    transport, and --globoff keeps curl from expanding brackets in a URL.
    """
    with tempfile.NamedTemporaryFile(suffix=".body") as body_file:
        command = [
            "curl",
            "-q",
            "--silent",
            "--show-error",
            "--globoff",
            "--proto",
            "=https",
            "--proto-redir",
            "=https",
            "--location",
            "--max-redirs",
            "10",
            "--max-time",
            str(timeout),
            "--max-filesize",
            str(MAX_DOWNLOAD_BYTES),
            # No explicit Accept header: help.splunk.com's WAF answers 403 to
            # "Accept: text/html,application/xhtml+xml" and 200 to curl's
            # default "*/*", so narrowing the header loses the page entirely.
            "--user-agent",
            USER_AGENT,
            "--output",
            body_file.name,
            "--write-out",
            "%{http_code} %{url_effective}",
            "--",
            url,
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout + 10,
            )
        except (OSError, subprocess.SubprocessError) as error:
            return {
                "status": None,
                "effective_url": url,
                "title": "",
                "error": f"{type(error).__name__}: {error}",
            }

        if completed.returncode != 0:
            detail = completed.stderr.strip() or f"curl exit {completed.returncode}"
            return {
                "status": None,
                "effective_url": url,
                "title": "",
                "error": f"transport failure ({detail})",
            }

        status_text, _, effective_url = completed.stdout.strip().partition(" ")
        try:
            status = int(status_text)
        except ValueError:
            return {
                "status": None,
                "effective_url": url,
                "title": "",
                "error": f"unparseable curl status {status_text!r}",
            }

        body = Path(body_file.name).read_bytes()[:MAX_BODY_BYTES]

    return {
        "status": status,
        "effective_url": effective_url or url,
        "title": extract_title(body),
    }


def evaluate(url: str, qualifiers: list[str], result: dict[str, Any]) -> dict[str, Any]:
    """Turn one probe into findings, an unverifiable note, or a clean result."""
    status = result.get("status")
    record: dict[str, Any] = {
        "url": url,
        "qualifiers": qualifiers,
        "status": status,
        "effective_url": result.get("effective_url", url),
        "title": result.get("title", ""),
    }

    if status is None or status in UNVERIFIABLE_STATUSES or (status and status >= 500):
        record["state"] = "unverifiable"
        record["reason"] = result.get("error") or f"HTTP {status}"
        return record

    if status != 200:
        record["state"] = "finding"
        record["signals"] = ["unreachable"]
        record["detail"] = f"HTTP {status} for a URL that claims a lifecycle stage"
        return record

    signals: list[str] = []
    if canonicalize(url) != canonicalize(record["effective_url"]):
        signals.append("redirected")

    title_tokens = normalize_tokens(record["title"])
    dropped = [q for q in qualifiers if not QUALIFIER_PATTERNS[q].search(title_tokens)]
    if record["title"] and dropped:
        signals.append("qualifier_dropped")
        record["dropped_qualifiers"] = dropped

    if signals:
        record["state"] = "finding"
        record["signals"] = signals
        return record

    record["state"] = "ok"
    return record


def audit(root: Path, max_workers: int, timeout: int) -> dict[str, Any]:
    occurrences = collect_occurrences(root)

    excluded: list[dict[str, Any]] = []
    checkable: dict[str, list[str]] = {}
    for url in sorted(occurrences):
        reason = exclusion_reason(url)
        if reason:
            excluded.append({"url": url, "reason": reason})
            continue
        checkable[url] = find_qualifiers(url)

    records: list[dict[str, Any]] = []
    if checkable:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(probe, url, timeout): url for url in sorted(checkable)
            }
            for future in concurrent.futures.as_completed(futures):
                url = futures[future]
                record = evaluate(url, checkable[url], future.result())
                record["occurrences"] = occurrences[url]
                records.append(record)

    records.sort(key=lambda record: record["url"])
    return {
        "scanned_urls": len(occurrences),
        "checked_urls": len(checkable),
        "qualifiers": list(LIFECYCLE_QUALIFIERS),
        "findings": [r for r in records if r["state"] == "finding"],
        "unverifiable": [r for r in records if r["state"] == "unverifiable"],
        "ok": [r for r in records if r["state"] == "ok"],
        "excluded": excluded,
    }


def render_text(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(
        f"Lifecycle-qualifier URL audit: {report['checked_urls']} checked, "
        f"{len(report['excluded'])} excluded, "
        f"{len(report['findings'])} findings, "
        f"{len(report['unverifiable'])} unverifiable"
    )
    lines.append(f"Qualifiers: {', '.join(report['qualifiers'])}")

    for record in report["findings"]:
        lines.append("")
        lines.append(f"FINDING [{', '.join(record['signals'])}] {record['url']}")
        lines.append(f"  qualifiers claimed by URL : {', '.join(record['qualifiers'])}")
        lines.append(f"  requested URL             : {record['url']}")
        lines.append(f"  effective URL             : {record['effective_url']}")
        lines.append(f"  resolved title            : {record['title'] or '(none)'}")
        if record.get("dropped_qualifiers"):
            lines.append(
                "  qualifier missing in title: "
                f"{', '.join(record['dropped_qualifiers'])}"
            )
        if record.get("detail"):
            lines.append(f"  detail                    : {record['detail']}")
        for occurrence in record["occurrences"]:
            lines.append(f"  cited at                  : {occurrence['file']}:{occurrence['line']}")

    for record in report["unverifiable"]:
        lines.append("")
        lines.append(f"UNVERIFIABLE {record['url']}")
        lines.append(f"  reason                    : {record['reason']}")
        for occurrence in record["occurrences"]:
            lines.append(f"  cited at                  : {occurrence['file']}:{occurrence['line']}")

    if report["findings"]:
        lines.append("")
        lines.append(
            "Each finding means the vendor probably changed the feature's release "
            "stage. Re-read the resolved page, update the skill's lifecycle claim, "
            "then update the URL."
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="List in-scope URLs without performing any network request.",
    )
    args = parser.parse_args()

    if args.max_workers < 1:
        parser.error("--max-workers must be at least 1")
    if args.timeout < 1:
        parser.error("--timeout must be at least 1")

    root = Path(args.root).resolve()

    if args.list_only:
        occurrences = collect_occurrences(root)
        listing = [
            {
                "url": url,
                "qualifiers": find_qualifiers(url),
                "excluded": exclusion_reason(url),
                "occurrences": occurrences[url],
            }
            for url in sorted(occurrences)
        ]
        if args.json:
            print(json.dumps({"in_scope": listing}, indent=2, sort_keys=True))
        else:
            for entry in listing:
                marker = entry["excluded"] or "check"
                print(f"[{marker}] {entry['url']}")
        return 0

    if shutil.which("curl") is None:
        print("curl is required for the lifecycle-qualifier URL audit", file=sys.stderr)
        return 2

    report = audit(root, args.max_workers, args.timeout)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_text(report))

    return 1 if report["findings"] else 0


if __name__ == "__main__":
    sys.exit(main())
