#!/usr/bin/env python3
"""Audit repo restart/reload call sites for the restart orchestrator."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "splunk-platform-restart-rendered"

SCAN_ROOTS = [
    REPO_ROOT / "skills",
    REPO_ROOT / "README.md",
    REPO_ROOT / "ARCHITECTURE.md",
    REPO_ROOT / "DEPLOYMENT_ROLE_MATRIX.md",
    REPO_ROOT / "CLOUD_DEPLOYMENT_MATRIX.md",
    REPO_ROOT / "SKILL_UX_CATALOG.md",
]

TEXT_SUFFIXES = {
    ".md",
    ".py",
    ".sh",
    ".json",
    ".yaml",
    ".yml",
    ".example",
    ".conf",
    ".service",
    ".txt",
}


@dataclass(frozen=True)
class Rule:
    category: str
    pattern: re.Pattern[str]
    recommendation: str


RULES = [
    Rule(
        "out_of_scope",
        re.compile(r"\b(kubectl\s+rollout\s+restart|systemctl\s+restart\s+(?:sc4s|sc4snmp|nginx)|restart:\s+unless-stopped|rollout restart)\b", re.I),
        "Leave as service/workload-specific restart; do not route through Splunk platform restart helpers.",
    ),
    Rule(
        "cloud_acs",
        re.compile(r"\b(acs\s+restart|restartRequired|cloud_app_restart_or_exit|cloud_restart_if_required|acs_restart_required)\b"),
        "Keep ACS-owned Cloud restart semantics; ensure restart only occurs when restartRequired=true.",
    ),
    Rule(
        "cluster_safe",
        re.compile(r"\b(rolling-restart|cluster_bundle_validate|validate_bundle|shcluster/captain/control/default/restart|cluster_rolling_restart|apply cluster-bundle|apply shcluster-bundle)\b"),
        "Keep cluster-aware path; ensure indexer bundles use validate_bundle with check-restart=true.",
    ),
    Rule(
        "reload_only",
        re.compile(r"(_reload\b|reload\s+deploy-server|workloads/(?:pools|rules)/_reload|debug/refresh)"),
        "Prefer reload; do not replace with a full restart unless validation proves reload is insufficient.",
    ),
    Rule(
        "direct_rest_restart",
        re.compile(r"/services/server/control/restart"),
        "Replace with platform_restart_or_exit or an explicit platform_restart_handoff; REST restart is fallback only.",
    ),
    Rule(
        "raw_splunk_restart",
        re.compile(r"(?<!rolling-)splunk(?:_bin)?[\"'}\s./-]*(?:bin/)?splunk[\"'}\s]*(?:restart|\s+restart)|\bsplunk\s+restart\b|\$\{splunk_home\}/bin/splunk[\"'}\s]*restart", re.I),
        "Replace rendered raw restart with platform restart plan/handoff or shared helper.",
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--check", action="store_true", help="Fail if direct REST restart call sites remain outside allowlisted helpers.")
    return parser.parse_args()


def is_text_file(path: Path) -> bool:
    if path.name in {"template.example"}:
        return True
    return path.suffix in TEXT_SUFFIXES


def iter_files() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        if root.is_file():
            files.append(root)
            continue
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(REPO_ROOT)
            if any(part.startswith(".") or part == "__pycache__" for part in rel.parts):
                continue
            if path.name.endswith((".pyc", ".tgz", ".zip")):
                continue
            if is_text_file(path):
                files.append(path)
    return sorted(files)


def classify_line(line: str) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    for rule in RULES:
        if rule.pattern.search(line):
            hits.append(
                {
                    "category": rule.category,
                    "recommendation": rule.recommendation,
                }
            )
    return hits


def audit() -> dict[str, object]:
    findings: list[dict[str, object]] = []
    counts: dict[str, int] = {rule.category: 0 for rule in RULES}

    for path in iter_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        for number, line in enumerate(text.splitlines(), start=1):
            for hit in classify_line(line):
                category = hit["category"]
                counts[category] = counts.get(category, 0) + 1
                findings.append(
                    {
                        "path": rel,
                        "line": number,
                        "category": category,
                        "text": line.strip()[:240],
                        "recommendation": hit["recommendation"],
                    }
                )

    return {
        "schema": "splunk-platform-restart-audit/v1",
        "repo": str(REPO_ROOT),
        "counts": counts,
        "findings": findings,
    }


def render_markdown(report: dict[str, object]) -> str:
    counts = report["counts"]
    findings = report["findings"]
    assert isinstance(counts, dict)
    assert isinstance(findings, list)

    lines = [
        "# Splunk Platform Restart Audit",
        "",
        "Generated by `splunk-platform-restart-orchestrator`.",
        "",
        "## Counts",
        "",
        "| Category | Count |",
        "| --- | --- |",
    ]
    for category in sorted(counts):
        lines.append(f"| `{category}` | {counts[category]} |")

    lines.extend(
        [
            "",
            "## Findings",
            "",
            "| File | Line | Category | Recommendation |",
            "| --- | --- | --- | --- |",
        ]
    )
    for finding in findings:
        assert isinstance(finding, dict)
        rec = str(finding["recommendation"]).replace("|", r"\|")
        lines.append(
            f"| `{finding['path']}` | {finding['line']} | `{finding['category']}` | {rec} |"
        )

    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    report = audit()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "repo-audit.json"
    md_path = output_dir / "repo-audit.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Wrote {md_path}")
        print(f"Wrote {json_path}")

    if args.check:
        offenders = [
            finding
            for finding in report["findings"]
            if isinstance(finding, dict)
            and finding.get("category") == "direct_rest_restart"
            and "rest_helpers.sh" not in str(finding.get("path"))
            and "restart_helpers.sh" not in str(finding.get("path"))
            and "repo_audit.py" not in str(finding.get("path"))
            and "SKILL.md" not in str(finding.get("path"))
            and "reference.md" not in str(finding.get("path"))
        ]
        if offenders:
            print(f"ERROR: {len(offenders)} direct REST restart call site(s) remain.", flush=True)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
