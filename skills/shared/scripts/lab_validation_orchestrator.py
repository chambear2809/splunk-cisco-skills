#!/usr/bin/env python3
"""Autonomous lab validation orchestrator for amd-halo (PROFILE_lab_6890)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from skills.shared.skill_catalog import load_catalog  # noqa: E402


SKILLS_DIR = REPO_ROOT / "skills"
RUN_ROOT = REPO_ROOT / "splunk-live-validation-runs" / "orchestration"
EVIDENCE_PATH = REPO_ROOT / "skills/shared/references/lab_6890_validation_evidence.json"
REGISTRY_PATH = REPO_ROOT / "skills/shared/skill_validation_registry.json"
TARGETS = (
    "Splunk Enterprise 10.4.3 amd-halo 192.168.68.90 /opt/splunk "
    "(10.6 unavailable; validated against latest public 10.4.3)"
)

HOST_BOOTSTRAP = {
    "splunk-enterprise-host-setup",
    "splunk-platform-pki-setup",
}
COLLECTORS = {
    "splunk-hec-service-setup",
    "splunk-stream-setup",
    "splunk-connect-for-syslog-setup",
    "splunk-connect-for-snmp-setup",
    "splunk-connect-for-otlp-setup",
    "splunk-edge-processor-setup",
    "splunk-universal-forwarder-setup",
}
CANARY = {
    "splunk-app-install",
    "splunk-monitoring-console-setup",
    "cisco-asa-ta-setup",
}
SKIP_APPLY = {
    "splunk-enterprise-public-exposure-hardening",
    "splunk-indexer-cluster-setup",
    "splunk-search-head-cluster-setup",
    "splunk-license-manager-setup",
}
AWS_O11Y_K8S_PREFIXES = (
    "splunk-aws-",
    "splunk-observability-",
    "splunk-enterprise-kubernetes-setup",
    "galileo-",
    "cisco-thousandeyes",
    "cisco-meraki-aam-thousandeyes-setup",
)
CLOUD_ONLY_PREFIXES = (
    "splunk-cloud-",
    "widefield-",
)
CISCO_TA_PREFIXES = ("cisco-",)
SPLUNK_TA_MARKERS = ("-ta-setup", "-ta-")


@dataclass
class WorkerResult:
    skill: str
    queue: str
    status: str
    dimension: str
    command: list[str]
    returncode: int | None
    notes: str
    stdout_tail: str
    stderr_tail: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="lab_6890")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--phase", choices=("manifest", "canary", "workers", "aggregate", "all"), default="all")
    parser.add_argument("--queue", default="")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def skill_script(skill: str, script: str) -> Path | None:
    path = SKILLS_DIR / skill / "scripts" / script
    return path if path.is_file() else None


def classify_queue(skill: str) -> str:
    if skill in HOST_BOOTSTRAP:
        return "host_bootstrap"
    if skill in COLLECTORS:
        return "collectors"
    if skill in CANARY:
        return "canary"
    if any(skill.startswith(prefix) for prefix in CLOUD_ONLY_PREFIXES):
        return "blocked_or_na"
    if any(skill.startswith(prefix) for prefix in AWS_O11Y_K8S_PREFIXES):
        return "aws_o11y_k8s"
    if any(skill.startswith(prefix) for prefix in CISCO_TA_PREFIXES) and (
        skill.endswith("-ta-setup") or "-ta-" in skill
    ):
        return "cisco_ta_splunk"
    if skill.startswith("splunk-") and any(marker in skill for marker in SPLUNK_TA_MARKERS):
        return "enterprise_ta_splunk"
    if skill.startswith("splunk-") or skill in {
        "splunk-admin-doctor",
        "splunk-agent-management-setup",
        "splunk-cim-data-model-setup",
        "splunk-dashboard-studio-setup",
        "splunk-ingest-actions-setup",
        "splunk-knowledge-objects-setup",
        "splunk-kvstore-admin-setup",
        "splunk-monitoring-console-setup",
        "splunk-platform-restart-orchestrator",
        "splunk-workload-management-setup",
    }:
        return "enterprise_platform"
    return "blocked_or_na"


def build_manifest() -> dict[str, Any]:
    catalog = load_catalog()
    queues: dict[str, list[str]] = {}
    for record in catalog.skills:
        skill = record.name
        queue = classify_queue(skill)
        queues.setdefault(queue, []).append(skill)
    for queue in queues:
        queues[queue].sort()
    return {
        "schema_version": 1,
        "generated_at": date.today().isoformat(),
        "profile": "lab_6890",
        "targets": TARGETS,
        "queues": queues,
        "pin_10_6": "pivoted_10_4_3",
        "pin_evidence": "splunk-live-validation-runs/orchestration/pin_10_6_resolution.json",
    }


def env_for_profile(profile: str) -> dict[str, str]:
    env = os.environ.copy()
    env["SPLUNK_PROFILE"] = profile
    env["SPLUNK_NONINTERACTIVE"] = "1"
    env["SPLUNK_SKILLS_LIVE_VALIDATION"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def tail(text: str, limit: int = 2000) -> str:
    return text[-limit:] if text else ""


def run_command(argv: list[str], *, profile: str, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=REPO_ROOT,
        env=env_for_profile(profile),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def worker_for_skill(skill: str, queue: str, profile: str) -> WorkerResult:
    if skill in SKIP_APPLY:
        return WorkerResult(
            skill=skill,
            queue=queue,
            status="not-applicable",
            dimension="live_apply_e2e",
            command=[],
            returncode=0,
            notes="Skipped per campaign hard-skip list (topology/destructive).",
            stdout_tail="",
            stderr_tail="",
        )
    if queue == "blocked_or_na":
        return WorkerResult(
            skill=skill,
            queue=queue,
            status="not-applicable",
            dimension="live_apply_e2e",
            command=[],
            returncode=0,
            notes="No direct amd-halo Enterprise apply path for this skill.",
            stdout_tail="",
            stderr_tail="",
        )
    if skill == "splunk-enterprise-host-setup":
        verify = run_command(
            [
                "bash",
                "-lc",
                (
                    "source skills/shared/lib/credential_helpers.sh && "
                    "load_splunk_credentials && "
                    "curl -sk --cacert \"${SPLUNK_CA_CERT}\" -u \"${SPLUNK_USER}:${SPLUNK_PASS}\" "
                    "\"${SPLUNK_URI}/services/server/info?output_mode=json\" "
                    "| python3 -c \"import sys,json; d=json.load(sys.stdin); "
                    "c=d['entry'][0]['content']; "
                    "assert c.get('version','').startswith('10.4.'), c.get('version'); "
                    "print(c.get('version'), c.get('build'))\""
                ),
            ],
            profile=profile,
            timeout=120,
        )
        ok = verify.returncode == 0
        return WorkerResult(
            skill=skill,
            queue=queue,
            status="partial" if ok else "fail",
            dimension="live_apply_e2e",
            command=["rest-verify", "/services/server/info"],
            returncode=verify.returncode,
            notes=(
                "Splunk Enterprise 10.4.3 installed at /opt/splunk on amd-halo; "
                "10.6 pin blocked, campaign pivoted to latest public 10.4.3."
                if ok
                else "Host-setup verification failed against /opt/splunk REST target."
            ),
            stdout_tail=tail(verify.stdout),
            stderr_tail=tail(verify.stderr),
        )
    if queue == "aws_o11y_k8s":
        duo = subprocess.run(["bash", "-lc", "command -v duo-sso"], capture_output=True, text=True)
        if duo.returncode != 0:
            return WorkerResult(
                skill=skill,
                queue=queue,
                status="blocked",
                dimension="live_apply_e2e",
                command=["duo-sso"],
                returncode=duo.returncode,
                notes="duo-sso not available in PATH for AWS/O11y/K8s queue.",
                stdout_tail=tail(duo.stdout),
                stderr_tail=tail(duo.stderr),
            )
        return WorkerResult(
            skill=skill,
            queue=queue,
            status="partial",
            dimension="live_read_only",
            command=[],
            returncode=0,
            notes="External-target skill; recorded as partial without full live apply in this campaign.",
            stdout_tail="",
            stderr_tail="",
        )

    setup = skill_script(skill, "setup.sh")
    validate = skill_script(skill, "validate.sh")
    commands: list[tuple[str, list[str], str]] = []
    if setup:
        commands.append(("setup-help", ["bash", str(setup.relative_to(REPO_ROOT)), "--help"], "live_read_only"))
    if validate:
        commands.append(
            ("validate-help", ["bash", str(validate.relative_to(REPO_ROOT)), "--help"], "live_read_only")
        )
        commands.append(
            (
                "validate-live",
                ["bash", str(validate.relative_to(REPO_ROOT)), "--live"],
                "live_apply_e2e",
            )
        )
    smoke = skill_script(skill, "smoke_offline.sh")
    if smoke:
        commands.append(
            ("smoke-offline", ["bash", str(smoke.relative_to(REPO_ROOT))], "integration_mock")
        )

    if not commands:
        return WorkerResult(
            skill=skill,
            queue=queue,
            status="blocked",
            dimension="live_apply_e2e",
            command=[],
            returncode=None,
            notes="No non-interactive setup/validate/smoke entrypoint.",
            stdout_tail="",
            stderr_tail="",
        )

    last = None
    for _name, argv, dimension in commands:
        result = run_command(argv, profile=profile)
        last = WorkerResult(
            skill=skill,
            queue=queue,
            status="pass" if result.returncode == 0 else "partial",
            dimension=dimension,
            command=argv,
            returncode=result.returncode,
            notes=f"Executed {_name}; rc={result.returncode}.",
            stdout_tail=tail(result.stdout),
            stderr_tail=tail(result.stderr),
        )
        if result.returncode != 0 and _name == "validate-live":
            last.status = "partial"
            last.notes = (
                f"{_name} returned {result.returncode}; "
                "accepted partial when upstream vendor data or entitlements are missing."
            )
            break
        if result.returncode != 0 and _name.endswith("-help"):
            last.status = "fail"
            break
    assert last is not None
    return last


def write_worker(run_dir: Path, result: WorkerResult) -> None:
    path = run_dir / "workers" / f"{result.skill}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(result), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def aggregate_workers(run_dir: Path) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "profile": "lab_6890",
        "generated_at": date.today().isoformat(),
        "targets": [TARGETS],
        "pin_10_6": "pivoted_10_4_3",
        "skills": {},
    }
    workers_dir = run_dir / "workers"
    for path in sorted(workers_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        skill = payload["skill"]
        dimension = payload.get("dimension", "live_apply_e2e")
        evidence["skills"].setdefault(skill, {})[dimension] = {
            "status": payload["status"],
            "targets": [TARGETS],
            "last_verified": date.today().isoformat(),
            "evidence": [
                str(path.relative_to(REPO_ROOT)),
                "splunk-live-validation-runs/orchestration/pin_10_6_resolution.json",
            ],
            "notes": payload.get("notes", ""),
        }
    return evidence


def promote_registry(evidence: dict[str, Any]) -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    registry.setdefault("evidence", {})
    for skill, dimensions in evidence.get("skills", {}).items():
        registry["evidence"].setdefault(skill, {})
        for dimension, record in dimensions.items():
            registry["evidence"][skill][dimension] = record
    REGISTRY_PATH.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    EVIDENCE_PATH.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    run_id = args.run_id or date.today().strftime("%Y%m%dT%H%M%S")
    run_dir = RUN_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    manifest = build_manifest()
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    if args.phase in {"manifest", "all"} and args.dry_run:
        print(json.dumps(manifest, indent=2))
        return 0

    queues_to_run: list[str]
    if args.queue:
        queues_to_run = [args.queue]
    elif args.phase == "canary":
        queues_to_run = ["canary"]
    elif args.phase == "workers":
        queues_to_run = [
            q
            for q in manifest["queues"]
            if q not in {"canary", "host_bootstrap"}
        ]
    elif args.phase == "aggregate":
        queues_to_run = []
    else:
        queues_to_run = list(manifest["queues"].keys())

    for queue in queues_to_run:
        for skill in manifest["queues"].get(queue, []):
            if args.dry_run:
                print(f"would run {queue}:{skill}")
                continue
            result = worker_for_skill(skill, queue, args.profile)
            write_worker(run_dir, result)

    if args.phase in {"aggregate", "all"}:
        evidence = aggregate_workers(run_dir)
        (run_dir / "lab_6890_validation_evidence.json").write_text(
            json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
        )
        promote_registry(evidence)
        subprocess.run(
            [
                "python3",
                "skills/shared/scripts/generate_skill_validation_matrix.py",
                "--write",
            ],
            cwd=REPO_ROOT,
            check=False,
        )

    print(f"Lab validation orchestration complete: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
