#!/usr/bin/env python3
"""Audit public documentation citations across the repository for dead links.

This is a scheduled network audit, not a push gate. It scans every tracked and
unignored source file, deduplicates citations, and checks URLs on recognized
documentation/reference hosts. Authentication endpoints, private hosts,
templates, and application/API URLs are excluded because a bare GET does not
prove their health. Redirects are recorded but accepted; terminal 4xx responses
other than bot/auth/rate-limit statuses fail the audit.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import shutil
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from audit_lifecycle_qualifier_urls import (  # noqa: E402
    UNVERIFIABLE_STATUSES,
    URL_RE,
    exclusion_reason,
    iter_tracked_files,
    probe,
    safe_urlsplit,
    trim_url,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MAX_WORKERS = 16
DEFAULT_TIMEOUT_SECONDS = 15

DOCUMENTATION_HOST_PREFIXES = (
    "advisory.",
    "code.",
    "dev.",
    "developer.",
    "developers.",
    "docs.",
    "documentation.",
    "help.",
    "research.",
)
DOCUMENTATION_HOST_SUFFIXES = (".github.io",)
DOCUMENTATION_HOSTS = frozenset(
    {
        "agent-observability-docs.splunk.com",
        "agentskills.io",
        "arxiv.org",
        "cursor.com",
        "github.com",
        "helm.sh",
        "isovalent.com",
        "modelcontextprotocol.io",
        "opentelemetry.io",
        "pkg.go.dev",
        "pypi.org",
        "raw.githubusercontent.com",
        "registry.terraform.io",
        "tetragon.io",
        "www.cisa.gov",
        "www.cisco.com",
        "www.splunk.com",
        "www.widefield.ai",
    }
)

SKIP_FILES = frozenset(
    {
        "tests/test_documentation_url_audit.py",
        "tests/test_lifecycle_qualifier_url_audit.py",
    }
)


def is_documentation_url(url: str) -> bool:
    parsed = safe_urlsplit(url)
    if parsed is None:
        return False
    host = (parsed.hostname or "").lower()
    return (
        host in DOCUMENTATION_HOSTS
        or host.startswith(DOCUMENTATION_HOST_PREFIXES)
        or host.endswith(DOCUMENTATION_HOST_SUFFIXES)
    )


def documentation_exclusion_reason(url: str) -> str | None:
    reason = exclusion_reason(url)
    if reason:
        return reason
    parsed = safe_urlsplit(url)
    if parsed is None:
        return "placeholder"
    host = (parsed.hostname or "").lower()
    path = parsed.path or "/"
    lowered_path = path.lower()
    if "/your-org/" in lowered_path:
        return "placeholder"
    if host == "github.com" and (
        lowered_path.endswith("/releases/download/")
        or lowered_path.endswith("/tree/")
    ):
        return "composed-url-base"
    if host == "raw.githubusercontent.com" and lowered_path.endswith("/"):
        return "composed-url-base"
    return None


def probe_target(url: str) -> str:
    """Resolve non-page repository bases to the resource that proves liveness."""
    parsed = safe_urlsplit(url)
    if parsed is None:
        return url
    if (parsed.hostname or "").lower().endswith(".github.io") and parsed.path.rstrip(
        "/"
    ).endswith("/helm-charts"):
        return url.rstrip("/") + "/index.yaml"
    return url


def collect_occurrences(root: Path) -> dict[str, list[dict[str, Any]]]:
    occurrences: dict[str, list[dict[str, Any]]] = {}
    for path in iter_tracked_files(root):
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "http" not in content:
            continue
        relative = path.relative_to(root).as_posix()
        if relative in SKIP_FILES:
            continue
        for line_number, line in enumerate(content.splitlines(), start=1):
            for match in URL_RE.finditer(line):
                url = trim_url(match.group(0))
                if url and is_documentation_url(url):
                    occurrences.setdefault(url, []).append(
                        {"file": relative, "line": line_number}
                    )
    return occurrences


def evaluate(url: str, result: dict[str, Any]) -> dict[str, Any]:
    status = result.get("status")
    effective_url = str(result.get("effective_url") or url)
    record: dict[str, Any] = {
        "url": url,
        "status": status,
        "effective_url": effective_url,
        "redirected": effective_url != url,
    }
    if status is None or status in UNVERIFIABLE_STATUSES or (status and status >= 500):
        record["state"] = "unverifiable"
        record["reason"] = result.get("error") or f"HTTP {status}"
    elif 200 <= status < 400:
        record["state"] = "ok"
    else:
        record["state"] = "finding"
        record["detail"] = f"terminal HTTP {status}"
    return record


def audit(root: Path, max_workers: int, timeout: int) -> dict[str, Any]:
    occurrences = collect_occurrences(root)
    excluded: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    checkable: list[str] = []

    for url in sorted(occurrences):
        parsed = safe_urlsplit(url)
        if parsed is not None and parsed.scheme.lower() != "https":
            finding = {
                "url": url,
                "status": None,
                "effective_url": url,
                "redirected": False,
                "state": "finding",
                "detail": "documentation citation does not use HTTPS",
                "occurrences": occurrences[url],
            }
            findings.append(finding)
            continue
        reason = documentation_exclusion_reason(url)
        if reason:
            excluded.append(
                {"url": url, "reason": reason, "occurrences": occurrences[url]}
            )
            continue
        checkable.append(url)

    records: list[dict[str, Any]] = []
    if checkable:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(probe, probe_target(url), timeout): url for url in checkable
            }
            for future in concurrent.futures.as_completed(futures):
                url = futures[future]
                try:
                    result = future.result()
                except Exception as error:  # noqa: BLE001 - isolate one remote failure.
                    result = {
                        "status": None,
                        "effective_url": url,
                        "error": f"{type(error).__name__}: {error}",
                    }
                record = evaluate(url, result)
                record["occurrences"] = occurrences[url]
                records.append(record)

    records.sort(key=lambda item: item["url"])
    findings.extend(item for item in records if item["state"] == "finding")
    findings.sort(key=lambda item: item["url"])
    ok = [item for item in records if item["state"] == "ok"]
    unverifiable = [item for item in records if item["state"] == "unverifiable"]
    verified = len(ok) + len(findings)
    return {
        "scanned_urls": len(occurrences),
        "checked_urls": len(checkable),
        "verified_responses": verified,
        "findings": findings,
        "unverifiable": unverifiable,
        "ok": ok,
        "excluded": excluded,
        "audit_healthy": not checkable or verified > 0,
    }


def render_text(report: dict[str, Any]) -> str:
    lines = [
        "Documentation URL audit: "
        f"{report['scanned_urls']} in scope, {report['checked_urls']} requested, "
        f"{len(report['findings'])} findings, "
        f"{len(report['unverifiable'])} unverifiable, "
        f"{len(report['excluded'])} excluded"
    ]
    for record in report["findings"]:
        lines.extend(["", f"FINDING {record['url']}", f"  {record['detail']}"])
        if record.get("redirected"):
            lines.append(f"  effective URL: {record['effective_url']}")
        for occurrence in record["occurrences"]:
            lines.append(f"  cited at: {occurrence['file']}:{occurrence['line']}")
    for record in report["unverifiable"]:
        lines.extend(["", f"UNVERIFIABLE {record['url']}", f"  {record['reason']}"])
        for occurrence in record["occurrences"]:
            lines.append(f"  cited at: {occurrence['file']}:{occurrence['line']}")
    if not report["audit_healthy"]:
        lines.extend(
            ["", "AUDIT UNHEALTHY: no checkable URL produced a verifiable response."]
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--list-only", action="store_true")
    args = parser.parse_args()

    if args.max_workers < 1:
        parser.error("--max-workers must be at least 1")
    if args.timeout < 1:
        parser.error("--timeout must be at least 1")

    root = Path(args.root).resolve()
    if args.list_only:
        occurrences = collect_occurrences(root)
        payload = [
            {
                "url": url,
                "excluded": documentation_exclusion_reason(url),
                "occurrences": occurrences[url],
            }
            for url in sorted(occurrences)
        ]
        if args.json:
            print(json.dumps({"in_scope": payload}, indent=2, sort_keys=True))
        else:
            for item in payload:
                print(f"[{item['excluded'] or 'check'}] {item['url']}")
        return 0

    if shutil.which("curl") is None:
        print("curl is required for the documentation URL audit", file=sys.stderr)
        return 2

    report = audit(root, args.max_workers, args.timeout)
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else render_text(report))
    if not report["audit_healthy"]:
        return 2
    return 1 if report["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
