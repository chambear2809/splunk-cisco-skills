#!/usr/bin/env python3
"""Generate an evidence-qualified Enterprise 10.6 workflow ledger.

This inventories workflows; it never executes a skill or promotes public
package compatibility from a functional lab result.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from skills.shared.skill_catalog import load_catalog  # noqa: E402
from skills.shared.scripts.audit_skill_compatibility import load_frontmatter  # noqa: E402
from skills.shared.scripts.audit_splunk_enterprise_10_6_compatibility import selected_package_evidence  # noqa: E402

EVIDENCE = ROOT / "skills/shared/references/splunk_enterprise_10_6_validation_evidence.json"
JSON_OUTPUT = ROOT / "skills/shared/references/splunk_enterprise_10_6_validation_ledger.json"
MD_OUTPUT = ROOT / "SPLUNK_ENTERPRISE_10_6_VALIDATION_LEDGER.md"


def build() -> dict:
    catalog = load_catalog()
    registry = json.loads((ROOT / "skills/shared/app_registry.json").read_text())
    evidence = json.loads(EVIDENCE.read_text())
    if evidence.get("schema_version") != 1 or evidence.get("enterprise_version") != "10.6.0.5":
        raise ValueError("ledger evidence must explicitly target Enterprise 10.6.0.5")
    known = set(catalog.by_name)
    unknown = set(evidence.get("workflows", {})) - known
    if unknown:
        raise ValueError(f"unknown evidence skills: {sorted(unknown)}")
    validation_registry = json.loads((ROOT / "skills/shared/skill_validation_registry.json").read_text())
    apps = registry["apps"]
    by_id = {str(a.get("splunkbase_id")): a for a in apps if a.get("splunkbase_id")}
    rows = []
    for skill in catalog.skills:
        text = (ROOT / skill.path).read_text()
        status = load_frontmatter(ROOT / skill.path)["metadata"]["splunk_enterprise_10_6"]
        packages = []
        required_skills = set()
        for app in apps:
            if app.get("skill") != skill.name:
                continue
            selected = selected_package_evidence(app)
            requires = [str(i) for i in app.get("install_requires", [])]
            required_skills.update(by_id[i]["skill"] for i in requires if i in by_id)
            packages.append({"id": str(app.get("splunkbase_id", "")),
                             "name": app.get("app_name"), **selected,
                             "install_requires": requires,
                             "role_support": app.get("role_support", {})})
        # Inventory routing surfaces too; a reference remains a handoff, not a
        # claim that every child is mandatory for every product selection.
        routing_text = text
        if status == "delegated":
            directory = (ROOT / skill.path).parent
            for path in directory.rglob("*"):
                if path.is_file() and path.suffix in {".sh", ".py", ".json", ".md"}:
                    routing_text += "\n" + path.read_text(encoding="utf-8")
            if skill.name == "widefield-security-setup":
                for path in (ROOT / "skills/shared/lib").glob("widefield*.sh"):
                    routing_text += "\n" + path.read_text(encoding="utf-8")
        # References are handoffs, not a claim that every mentioned skill is mandatory.
        handoffs = sorted(n for n in known if n != skill.name and
                          re.search(r"(?<![a-z0-9-])" + re.escape(n) + r"(?![a-z0-9-])", routing_text))
        observation = evidence.get("workflows", {}).get(skill.name)
        functional = "not-applicable" if status == "not-applicable" else "pending"
        if observation:
            functional = observation["status"]
            if functional not in {"pass", "partial", "blocked", "fail", "pending", "not-applicable"}:
                raise ValueError(f"{skill.name}: invalid workflow status")
            if not observation.get("notes"):
                raise ValueError(f"{skill.name}: observation requires explanatory notes")
            if functional in {"pass", "partial", "fail"}:
                if not observation.get("last_verified") or not observation.get("evidence"):
                    raise ValueError(f"{skill.name}: measured result requires date and evidence")
            if functional == "blocked" and not all(observation.get(k) for k in ("owner", "next_action", "impact", "evidence")):
                raise ValueError(f"{skill.name}: blocker requires evidence, impact, owner and next action")
            for ref in observation.get("evidence", []):
                if not ref.startswith("https://") and (Path(ref).is_absolute() or ".." in Path(ref).parts or not (ROOT / ref).is_file()):
                    raise ValueError(f"{skill.name}: missing or unsafe evidence reference {ref}")
        ta_gate = "ta_completion_gate.md" in text
        rows.append({
            "skill": skill.name, "enterprise_compatibility": status,
            "functional_status": functional, "workflow": skill.purpose,
            "selected_packages": packages, "required_skills": sorted(required_skills - {skill.name}),
            "documented_skill_handoffs": handoffs,
            "test_target": "dedicated supported Enterprise 10.6.0.5 lab; product dependencies must be available",
            "validation_entrypoint": f"bash skills/{skill.name}/scripts/validate.sh",
            "required_evidence": ["reviewed render/preflight", "authenticated operation and readback", "health and persistence"] +
                                 (["enabled source ingest", "visible populated shipped dashboards, or explicit no-dashboard package evidence"] if ta_gate else []),
            "cleanup": "Remove only run-owned objects/resources after readback; retain primary/reusable lab and required recovery artifacts.",
            "observation": observation,
            "existing_validation_dimensions": validation_registry.get("evidence", {}).get(skill.name, {}),
            "existing_evidence_qualification": "Historical dimensions retain their original dates and environment; only the explicit Enterprise observation above qualifies this target.",
        })
    by_skill = {row["skill"]: row for row in rows}
    for row in rows:
        if row["enterprise_compatibility"] == "delegated":
            row["child_results"] = [{"skill": name,
                "enterprise_compatibility": by_skill[name]["enterprise_compatibility"],
                "functional_status": by_skill[name]["functional_status"]}
                for name in sorted(set(row["required_skills"] + row["documented_skill_handoffs"]))]
    return {"schema_version": 1, "enterprise_version": evidence["enterprise_version"],
            "assessment_date": evidence["assessment_date"], "skill_count": len(rows),
            "compatibility_counts": dict(sorted(Counter(r["enterprise_compatibility"] for r in rows).items())),
            "functional_counts": dict(sorted(Counter(r["functional_status"] for r in rows).items())),
            "scope": "Default documented Enterprise workflow per skill; optional variants remain explicitly qualified. Historical evidence is not transferred to a new version.",
            "workflows": rows}


def markdown(payload: dict) -> str:
    lines = ["# Enterprise 10.6 Validation Ledger", "",
             "Generated by `generate_enterprise_10_6_validation_ledger.py`. Compatibility and functional results are separate.", "",
             f"Assessment: {payload['assessment_date']}. Target: `{payload['enterprise_version']}`. Canonical skills: {payload['skill_count']}.", "",
             "The companion JSON contains package releases, install dependencies, documented handoffs, required evidence, targets, and cleanup obligations.", "",
             "| Skill | Compatibility | Functional result | Evidence / next action |", "| --- | --- | --- | --- |"]
    for row in payload["workflows"]:
        obs = row["observation"] or {}
        detail = obs.get("notes", "No current Enterprise 10.6 workflow evidence recorded." if row["functional_status"] == "pending" else "No direct Enterprise runtime dependency.")
        if obs.get("next_action"):
            detail += " Next: " + obs["next_action"]
        detail = detail.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| `{row['skill']}` | {row['enterprise_compatibility']} | {row['functional_status']} | {detail} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--write", action="store_true")
    modes.add_argument("--check", action="store_true")
    args = parser.parse_args()
    payload = build()
    outputs = {JSON_OUTPUT: json.dumps(payload, indent=2, sort_keys=True) + "\n", MD_OUTPUT: markdown(payload)}
    if args.write:
        for path, content in outputs.items():
            path.write_text(content)
    if args.check:
        for path, content in outputs.items():
            if not path.exists() or path.read_text() != content:
                print(f"Outdated ledger: {path.name}", file=sys.stderr)
                return 1
    print(json.dumps({k: payload[k] for k in ("skill_count", "compatibility_counts", "functional_counts")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
