#!/usr/bin/env python3
"""Shared renderer for WideField Security skills."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import stat
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SECRET_KEY_RE = re.compile(
    r"(password|token|api[_-]?key|client[_-]?secret|private[_-]?key|bearer|secret)",
    re.IGNORECASE,
)
SAFE_SECRET_KEY_RE = re.compile(r"(?:_file|_path|_name|_id|_ref|name)$", re.IGNORECASE)

DEFAULTS = {
    "index": "widefield",
    "sourcetype": "widefield:security",
    "hec_source": "widefield",
    "hec_token_name": "widefield_security_hec",
    "okta_hook_name": "widefield_security_detect_and_remediate",
    "okta_event_types": "user.session.start,user.authentication.sso,user.account.privilege.grant,application.user_membership.add",
    "google_secops_log_type": "WIDEFIELD_SECURITY",
}

ARG_DEFAULTS = {
    "index": DEFAULTS["index"],
    "sourcetype": DEFAULTS["sourcetype"],
    "hec_source": DEFAULTS["hec_source"],
    "hec_token_name": DEFAULTS["hec_token_name"],
    "okta_org_url": "",
    "receiver_url": "",
    "hook_name": DEFAULTS["okta_hook_name"],
    "event_types": DEFAULTS["okta_event_types"],
    "saviynt_tenant_url": "",
    "google_secops_project": "",
    "google_secops_region": "us",
    "feed_name": "widefield-security",
    "evidence_file": "",
    "children": "okta,saviynt,splunk,google,doctor",
}

SPEC_ARG_PATHS = {
    "index": (("splunk", "index"), ("index",)),
    "sourcetype": (("splunk", "sourcetype"), ("sourcetype",)),
    "hec_source": (("splunk", "hec_source"), ("hec_source",)),
    "hec_token_name": (("splunk", "hec_token_name"), ("hec_token_name",)),
    "okta_org_url": (("okta", "org_url"), ("okta_org_url",)),
    "receiver_url": (("okta", "receiver_url"), ("receiver_url",)),
    "hook_name": (("okta", "hook_name"), ("hook_name",)),
    "event_types": (("okta", "event_types"), ("event_types",)),
    "saviynt_tenant_url": (("saviynt", "tenant_url"), ("saviynt_tenant_url",)),
    "google_secops_project": (("google_secops", "project"), ("google_secops_project",)),
    "google_secops_region": (("google_secops", "region"), ("google_secops_region",)),
    "feed_name": (("google_secops", "feed_name"), ("feed_name",)),
    "evidence_file": (("evidence", "file"), ("evidence_file",)),
    "children": (("children",),),
}

SOURCE_LEDGER = [
    (
        "WideField platform",
        "https://www.widefield.ai/",
        "Identity security lifecycle, human and non-human identity visibility, AI-powered behavior analytics, and remediation positioning.",
    ),
    (
        "WideField demo room",
        "https://www.widefield.ai/demo-room",
        "Public capability surface for identity posture, non-human identity ownership, connected app risk, AI identity access, and session analysis.",
    ),
    (
        "WideField OpenClaw identity research",
        "https://www.widefield.ai/blog/openclaw-beyond-endpoint-detection-think-identity-security",
        "Identity detection coverage for OAuth grants, API tokens, service principals, bots, and cross-application behavior.",
    ),
    (
        "WideField OAuth compromise analysis",
        "https://www.widefield.ai/blog/more-salesloft-drift-compromise-expanding-to-more-apps-than-salesforce",
        "OAuth token abuse and third-party connected application risk guidance.",
    ),
    (
        "Okta WideField OIN listing",
        "https://www.okta.com/integrations/widefield-security-detect-and-remediate/",
        "Public Okta Integration Network listing for WideField Security - Detect and Remediate.",
    ),
    (
        "Okta shared signal receiver docs",
        "https://help.okta.com/oie/en-us/content/topics/itp/configure-shared-signal-provider.htm",
        "Shared Signals Framework receiver setup, System Log events, and risk engine behavior.",
    ),
    (
        "Okta Event Hooks API",
        "https://developer.okta.com/docs/api/openapi/okta-management/management/tags/eventhook",
        "Documented event hook create, update, verify, activate, deactivate, and list operations.",
    ),
    (
        "Saviynt WideField exchange listing",
        "https://exchange.saviynt.com/products/widefield-security",
        "Certified remediation patterns: access revocation, password reset, and micro-certification.",
    ),
    (
        "Google SecOps parser list",
        "https://docs.cloud.google.com/chronicle/docs/ingestion/parser-list/supported-default-parsers",
        "Supported default parser entry for WideField `WIDEFIELD_SECURITY`.",
    ),
    (
        "Cisco Investments announcement",
        "https://www.businesswire.com/news/home/20260319154962/en/WideField-Announces-Participation-from-Cisco-Investments-in-Series-A-Round-as-Company-Launches-AI-Agent-Identity-Monitoring",
        "AI Agent Identity Monitoring launch and Cisco Investments participation.",
    ),
    (
        "Cisco intent to acquire WideField",
        "https://blogs.cisco.com/news/cisco-announces-intent-to-acquire-widefield-security",
        "Cisco announced intent to acquire WideField to add identity and session intelligence to Splunk's Agentic SOC and Cisco Cloud Control.",
    ),
    (
        "Cisco Investments WideField portfolio",
        "https://www.ciscoinvestments.com/portfolio/widefield-security",
        "Cisco Investments portfolio note confirming WideField and Cisco's announced acquisition intent.",
    ),
    (
        "Splunk HEC setup",
        "https://help.splunk.com/en?resourceId=Splunk_Data_UsetheHTTPEventCollector",
        "HEC token-based ingest model for sending application events to Splunk.",
    ),
    (
        "Splunk HEC REST endpoints",
        "https://help.splunk.com/en/splunk-cloud-platform/get-started/get-data-in/10.2.2510/get-data-with-http-event-collector/http-event-collector-rest-api-endpoints",
        "Documented HEC token and collector REST endpoints.",
    ),
]

WIDEFIELD_CAPABILITIES = [
    (
        "identity_visibility_posture",
        "Identity visibility and posture management",
        [
            "Identity landscape indexing across SaaS, cloud, and on-premises systems.",
            "Federated and non-federated identity discovery.",
            "Credential exposure and long-lived credential risk review.",
        ],
        "identity, credential, password, posture, stale credential, long-lived credential",
    ),
    (
        "non_human_identity_ownership",
        "Non-human identity discovery and ownership",
        [
            "Human versus non-human identity classification.",
            "Service account discovery, ownership inference, account attestation, and orphaned-account risk review.",
        ],
        "non-human, NHI, service account, workload identity, orphan, attestation",
    ),
    (
        "human_identity_posture",
        "Human identity security posture",
        [
            "Account risk, password and credential posture, and MFA enforcement visibility.",
            "Admin-without-MFA and weak MFA factor detection.",
        ],
        "MFA, admin, weak factor, account risk, password posture",
    ),
    (
        "connected_application_permission_risk",
        "Connected applications and permission risk",
        [
            "Connected application and third-party app discovery.",
            "Over-privileged application detection, app usage monitoring, and SaaS supply-chain risk review.",
        ],
        "connected app, OAuth app, third-party app, consent grant, over-privileged application",
    ),
    (
        "ai_identity_access_monitoring",
        "AI identity access monitoring",
        [
            "AI application discovery and shadow AI detection.",
            "AI identity access tracking for ChatGPT, Copilot, and similar AI integrations.",
        ],
        "AI app, shadow AI, ChatGPT, Copilot, agent identity, AI permission",
    ),
    (
        "authentication_session_analysis",
        "Authentication monitoring and session analysis",
        [
            "Authentication session tracking and policy escape monitoring.",
            "MFA bypass, session duration, and high-frequency login detection.",
        ],
        "session, MFA bypass, policy escape, high-frequency login, impossible travel",
    ),
]

OKTA_OIN_FEATURES = [
    ("API", "handoff", "Covered as an OIN capability; this suite only calls documented Okta Event Hooks APIs."),
    ("Entitlement Management", "handoff", "Render governance evidence and hand off entitlement remediation to Okta/Saviynt owners."),
    ("Event Hooks", "supported_apply", "Create, update, verify, deactivate, and validate documented event hooks."),
    ("Identity Security & Posture Management", "evidence", "Covered through WideField capability evidence and Okta System Log validation."),
    ("Inbound Federation", "handoff", "OIN/provider setup handoff; no live mutation without a documented API path."),
    ("Inline Hooks", "handoff", "Document as possible Okta integration surface; no inline-hook mutation in this skill."),
    ("Outbound Federation", "handoff", "OIN/provider setup handoff; no live mutation without a documented API path."),
    ("Partial Universal Logout", "handoff", "Render validation and owner handoff; no logout mutation from this skill."),
    ("Universal Logout", "handoff", "Render validation and owner handoff; no logout mutation from this skill."),
    ("Workflows", "handoff", "Render Okta Workflows evidence requirements; no workflow object mutation."),
    ("SAML", "handoff", "Render SSO evidence requirements."),
    ("SWA", "handoff", "Render OIN assignment evidence requirements."),
    ("WS-Federation", "handoff", "Render federation evidence requirements."),
    ("OIDC", "handoff", "Render OIDC app evidence requirements."),
    ("SCIM", "handoff", "Render SCIM/provisioning evidence requirements."),
    ("Brokered Consent", "handoff", "Render consent and connected-app review evidence requirements."),
    ("Cross App Access", "handoff", "Render app-to-app access review evidence requirements."),
    ("Privileged Access Management", "handoff", "Render privileged identity evidence requirements."),
    ("Create Users", "handoff", "Provisioning feature coverage is documented; no user create mutation."),
    ("Update User Attributes", "handoff", "Provisioning feature coverage is documented; no user update mutation."),
    ("Attribute Sourcing", "handoff", "Provisioning feature coverage is documented; validate with owner evidence."),
    ("Deactivate Users", "handoff", "Provisioning feature coverage is documented; no user deactivate mutation."),
    ("Credential Sync", "handoff", "Provisioning feature coverage is documented; no credential mutation."),
    ("Group Push", "handoff", "Provisioning feature coverage is documented; validate with owner evidence."),
    ("Group Linking", "handoff", "Provisioning feature coverage is documented; validate with owner evidence."),
    ("User Schema Discovery", "handoff", "Provisioning feature coverage is documented; validate with owner evidence."),
    ("Attribute Writeback", "handoff", "Provisioning feature coverage is documented; no writeback mutation."),
]


def parse_args(profile: dict[str, Any]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"Render {profile['display_name']} assets.")
    parser.add_argument("--output-dir", default=str(REPO_ROOT / profile["render_root"]))
    parser.add_argument("--spec", default="", help="Optional non-secret JSON/YAML spec file.")
    parser.add_argument("--index", default=None)
    parser.add_argument("--sourcetype", default=None)
    parser.add_argument("--hec-source", default=None)
    parser.add_argument("--hec-token-name", default=None)
    parser.add_argument("--okta-org-url", default=None)
    parser.add_argument("--receiver-url", default=None)
    parser.add_argument("--hook-name", default=None)
    parser.add_argument("--event-types", default=None)
    parser.add_argument("--saviynt-tenant-url", default=None)
    parser.add_argument("--google-secops-project", default=None)
    parser.add_argument("--google-secops-region", default=None)
    parser.add_argument("--feed-name", default=None)
    parser.add_argument("--evidence-file", default=None)
    parser.add_argument("--children", default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    apply_spec_defaults(args)
    return args


def parse_spec_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value[0:1] in {"'", '"'} and value[-1:] == value[0]:
        return value[1:-1]
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none"}:
        return None
    return value


def parse_simple_yaml(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        if ":" not in stripped:
            continue
        key, raw_value = stripped.split(":", 1)
        key = key.strip().strip("'\"")
        value = raw_value.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if value == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = parse_spec_scalar(value)
    return root


def load_spec(path_value: str) -> dict[str, Any]:
    if not path_value:
        return {}
    path = Path(path_value).expanduser()
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    try:
        import yaml  # type: ignore[import-not-found]

        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return parse_simple_yaml(text)


def spec_value(spec: dict[str, Any], paths: tuple[tuple[str, ...], ...]) -> Any:
    for path in paths:
        node: Any = spec
        for key in path:
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]
        if node not in (None, ""):
            return node
    return None


def stringify_spec_value(value: Any) -> str:
    if isinstance(value, list):
        return ",".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def apply_spec_defaults(args: argparse.Namespace) -> None:
    check_spec_for_secrets(args.spec)
    spec = load_spec(args.spec)
    for attr, default in ARG_DEFAULTS.items():
        current = getattr(args, attr)
        if current not in (None, ""):
            continue
        value = spec_value(spec, SPEC_ARG_PATHS[attr])
        setattr(args, attr, stringify_spec_value(value) if value not in (None, "") else default)


def check_spec_for_secrets(path_value: str) -> None:
    if not path_value:
        return
    path = Path(path_value).expanduser()
    if not path.is_file():
        raise SystemExit(f"ERROR: spec file not found: {path}")
    text = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r'["\']?([A-Za-z0-9_.-]+)["\']?\s*[:=]', stripped)
        if not match:
            continue
        key = match.group(1)
        if SECRET_KEY_RE.search(key) and not SAFE_SECRET_KEY_RE.search(key):
            raise SystemExit(
                f"ERROR: {path}:{lineno}: raw secret-looking key '{key}' is not allowed. "
                "Use a *_file, *_path, *_name, or external secret reference key."
            )


def validate_name(value: str, label: str, pattern: str) -> None:
    if not re.fullmatch(pattern, value or ""):
        raise SystemExit(f"ERROR: invalid {label}: {value!r}")


def validate_args(args: argparse.Namespace) -> None:
    validate_name(args.index, "--index", r"[_A-Za-z0-9][A-Za-z0-9_.-]*")
    validate_name(args.sourcetype, "--sourcetype", r"[A-Za-z0-9_.:-]+")
    validate_name(args.hec_source, "--hec-source", r"[A-Za-z0-9_.:/-]+")
    validate_name(args.hec_token_name, "--hec-token-name", r"[A-Za-z0-9_.:-]+")
    for attr in ("okta_org_url", "receiver_url", "saviynt_tenant_url", "google_secops_project", "feed_name"):
        value = getattr(args, attr)
        if "\n" in value or "\r" in value:
            raise SystemExit(f"ERROR: --{attr.replace('_', '-')} must not contain newlines.")
    check_spec_for_secrets(args.spec)


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def q(value: object) -> str:
    return shlex.quote(str(value))


def csv_values(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def source_ledger_md() -> str:
    lines = ["# Source Ledger", ""]
    lines.append("The skill uses public documentation only for live behavior claims.")
    lines.append("")
    lines.append("| Source | URL | Usage |")
    lines.append("| --- | --- | --- |")
    for title, url, usage in SOURCE_LEDGER:
        lines.append(f"| {title} | {url} | {usage} |")
    lines.append("")
    lines.append("Unsupported mutation rule: do not call private or undocumented WideField, Saviynt, or Google SecOps APIs from this skill suite.")
    return "\n".join(lines)


def capability_keys() -> list[str]:
    return [key for key, _title, _coverage, _signals in WIDEFIELD_CAPABILITIES]


def okta_feature_keys() -> list[str]:
    return [name.lower().replace("&", "and").replace(" ", "_").replace("-", "_") for name, _status, _notes in OKTA_OIN_FEATURES]


def capability_coverage_md(profile: dict[str, Any], args: argparse.Namespace) -> str:
    lines = [f"# WideField Capability Coverage - {profile['display_name']}", ""]
    lines.append("This matrix is based on public WideField product materials and is rendered for every WideField skill so product coverage gaps are visible during review.")
    lines.append("")
    lines.append("| Capability area | Rendered coverage | Validation evidence to collect |")
    lines.append("| --- | --- | --- |")
    for _key, title, coverage, signals in WIDEFIELD_CAPABILITIES:
        rendered = "<br>".join(coverage)
        lines.append(f"| {title} | {rendered} | WideField events or evidence containing: `{signals}` |")
    lines.append("")
    lines.append("## Skill Coverage")
    lines.append("")
    lines.append(f"- Current skill: `{profile['name']}`")
    lines.append("- Primary rendered files: `validation-searches.spl`, `identity-threat-checks.spl`, `readiness-evidence-template.json`, and this coverage matrix.")
    lines.append(f"- Splunk defaults: index `{args.index}`, sourcetype `{args.sourcetype}`, source `{args.hec_source}`.")
    lines.append("- Unsupported WideField-side mutation remains a provider/customer handoff until a documented public API is added.")
    return "\n".join(lines)


def okta_oin_coverage_md() -> str:
    lines = ["# Okta OIN Feature Coverage", ""]
    lines.append("The Okta OIN listing exposes a broad WideField feature surface. This skill suite distinguishes documented live Okta actions from OIN/provider handoffs.")
    lines.append("")
    lines.append("| OIN feature | Status in this suite | Coverage note |")
    lines.append("| --- | --- | --- |")
    for feature, status, note in OKTA_OIN_FEATURES:
        lines.append(f"| {feature} | `{status}` | {note} |")
    lines.append("")
    lines.append("Only `Event Hooks` are implemented as live Okta mutation here, and only through the documented Okta Event Hooks Management API with file-backed credentials. All OIN assignment, shared-signal provider, provisioning, logout, federation, and workflow features are rendered as handoffs unless a public documented API path is added.")
    return "\n".join(lines)


def metadata(profile: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    return {
        "skill": profile["name"],
        "display_name": profile["display_name"],
        "target": profile["target"],
        "render_first": True,
        "live_mutation_model": profile["mutation_model"],
        "defaults": {
            "index": args.index,
            "sourcetype": args.sourcetype,
            "hec_source": args.hec_source,
            "hec_token_name": args.hec_token_name,
            "google_secops_log_type": DEFAULTS["google_secops_log_type"],
        },
        "inputs": {
            "spec": args.spec,
            "okta_org_url": args.okta_org_url,
            "receiver_url": args.receiver_url,
            "hook_name": args.hook_name,
            "event_types": csv_values(args.event_types),
            "saviynt_tenant_url": args.saviynt_tenant_url,
            "google_secops_project": args.google_secops_project,
            "google_secops_region": args.google_secops_region,
            "feed_name": args.feed_name,
            "evidence_file": args.evidence_file,
            "children": csv_values(args.children),
        },
        "widefield_capability_areas": capability_keys(),
        "okta_oin_features": okta_feature_keys(),
        "sources": [url for _title, url, _usage in SOURCE_LEDGER],
    }


def profile_plan(profile: dict[str, Any], args: argparse.Namespace) -> str:
    rows = "\n".join(f"| {name} | {purpose} |" for name, purpose in profile["steps"])
    return f"""# {profile['display_name']} Plan

Target: `{profile['target']}`

## Outcomes

{profile['outcomes']}

## Work Plan

| Step | Purpose |
| --- | --- |
{rows}

## Default Event Contract

| Field | Value |
| --- | --- |
| Splunk index | `{args.index}` |
| Splunk source type | `{args.sourcetype}` |
| Splunk HEC source | `{args.hec_source}` |
| Splunk HEC token name | `{args.hec_token_name}` |
| Google SecOps log type | `{DEFAULTS['google_secops_log_type']}` |

## Live Mutation Boundary

{profile['mutation_model']}

## Coverage Artifacts

- `capability-coverage.md` maps the public WideField capability surface to rendered evidence requirements.
- `okta-oin-coverage.md` records which Okta OIN features are supported live actions versus handoffs.
"""


def handoffs_md(profile: dict[str, Any], args: argparse.Namespace) -> str:
    child_lines = "\n".join(f"- `{child}`" for child in profile.get("child_skills", [])) or "- None"
    return f"""# Handoffs

## Owning Skills

{child_lines}

## Operator Handoffs

{profile['handoffs']}

## Secret Handling

- Do not pass tokens, passwords, API keys, client secrets, or HEC token values in argv.
- Use local chmod 600 files such as `--okta-token-file`, `--hook-auth-secret-file`, `--hec-token-file`, or `--write-hec-token-file`.
- Completed specs must contain only non-secret values or file paths.

## Review Commands

```bash
bash skills/{profile['name']}/scripts/setup.sh --render --output-dir {q(args.output_dir)}
bash skills/{profile['name']}/scripts/validate.sh --dry-run
```
"""


def validation_spl(args: argparse.Namespace) -> str:
    return f"""# WideField Security Splunk validation searches

index={args.index} sourcetype={args.sourcetype}
| spath
| stats count min(_time) as first_seen max(_time) as last_seen values(event_type) as event_types by source sourcetype
| convert ctime(first_seen) ctime(last_seen)

index={args.index} sourcetype={args.sourcetype}
| spath
| eval signal=lower(coalesce(event_type,'finding.type',category,signature,message))
| eval capability=case(
    match(signal,"credential|password|posture|long.?lived"),"identity_visibility_posture",
    match(signal,"nhi|non.?human|service.?account|workload|orphan|attestation"),"non_human_identity_ownership",
    match(signal,"mfa|admin|weak.?factor|account.?risk"),"human_identity_posture",
    match(signal,"oauth|connected.?app|third.?party|consent|permission|over.?privileged|supply"),"connected_application_permission_risk",
    match(signal,"ai|chatgpt|copilot|agent"),"ai_identity_access_monitoring",
    match(signal,"session|mfa.?bypass|policy.?escape|high.?frequency|impossible"),"authentication_session_analysis",
    true(),"other")
| stats count values(event_type) as event_types values(severity) as severities by capability
| sort - count

index={args.index} sourcetype={args.sourcetype}
| spath
| eval identity=coalesce('actor.email','actor.id','identity.email','identity.id',user)
| eval risk=coalesce(risk.score,severity,threat.severity)
| stats count values(event_type) as event_types values(risk) as risks by identity
| sort - count

index={args.index} sourcetype={args.sourcetype}
| spath
| eval signal=lower(coalesce(event_type,'finding.type',category,signature,message))
| search signal="*oauth*" OR signal="*connected*app*" OR signal="*third*party*" OR signal="*consent*" OR signal="*over*privileged*"
| table _time event_type actor.id actor.email application.id application.name oauth.scope permissions risk.score remediation.action

index={args.index} sourcetype={args.sourcetype}
| spath
| eval signal=lower(coalesce(event_type,'finding.type',category,signature,message))
| search signal="*nhi*" OR signal="*non*human*" OR signal="*service*account*" OR signal="*workload*" OR signal="*orphan*"
| eval owner=coalesce('identity.owner.email','owner.email','owner.id')
| table _time event_type identity.id identity.name owner risk.score attestation.status remediation.action

index={args.index} sourcetype={args.sourcetype}
| spath
| eval signal=lower(coalesce(event_type,'finding.type',category,signature,message))
| search signal="*session*" OR signal="*mfa*bypass*" OR signal="*policy*escape*" OR signal="*high*frequency*login*" OR signal="*impossible*"
| table _time event_type actor.email session.id session.duration_minutes src_ip risk.score remediation.action

index=_internal (widefield OR {args.hec_token_name} OR {args.sourcetype})
| stats count values(log_level) as levels by source sourcetype
"""


def validation_queries(profile: dict[str, Any], args: argparse.Namespace) -> str:
    return f"""# Target Validation Queries

## Okta

- Confirm the WideField event hook exists and is verified:
  `GET /api/v1/eventHooks`
- Confirm shared-signal risk events when the WideField provider sends SSF/CAEP signals:
  `GET /api/v1/logs?filter=eventType eq "security.events.provider.receive_event"`
- Confirm downstream risk engine events:
  `GET /api/v1/logs?filter=eventType eq "user.risk.detect"`
- Confirm OIN feature coverage by reviewing `okta-oin-coverage.md`; only Event Hooks are live-mutated by this suite.

## Google SecOps

- Confirm feed/parser evidence references log type `{DEFAULTS['google_secops_log_type']}`.
- Run a UDM search for WideField events in the feed window after ingestion is configured.

## Saviynt

- Confirm remediation tickets or policy runs map WideField findings to access revocation, password reset, or micro-certification.
- Attach partner/customer API evidence before any live Saviynt mutation is attempted.

## WideField Capability Coverage

- Attach evidence for each area in `capability-coverage.md`: identity posture, non-human identity ownership, human MFA posture, connected application risk, AI identity access, and authentication/session analysis.

## Skill-Specific Notes

{profile['validation_notes']}
"""


def evidence_template(profile: dict[str, Any], args: argparse.Namespace) -> str:
    payload = {
        "skill": profile["name"],
        "widefield_workspace": "",
        "owner": "",
        "environment": "prod",
        "splunk": {
            "index": args.index,
            "sourcetype": args.sourcetype,
            "hec_token_name": args.hec_token_name,
            "sample_event_count": 0,
            "last_event_time": "",
        },
        "okta": {
            "org_url": args.okta_org_url,
            "event_hook_id": "",
            "event_hook_status": "",
            "shared_signal_receiver_configured": False,
            "system_log_events": [],
        },
        "saviynt": {
            "tenant_url": args.saviynt_tenant_url,
            "remediation_actions_validated": [],
            "api_reference_attached": False,
        },
        "google_secops": {
            "project": args.google_secops_project,
            "region": args.google_secops_region,
            "feed_name": args.feed_name,
            "log_type": DEFAULTS["google_secops_log_type"],
            "parser_visible": False,
        },
        "widefield_capabilities": {
            key: {
                "covered": False,
                "evidence_refs": [],
                "notes": "",
            }
            for key in capability_keys()
        },
        "okta_oin_feature_coverage": {
            key: {
                "configured_or_handoff_recorded": False,
                "evidence_refs": [],
            }
            for key in okta_feature_keys()
        },
        "identity_threats": {
            "oauth_token_abuse_checked": False,
            "rogue_app_checked": False,
            "nhi_checked": False,
            "ai_agent_identity_checked": False,
            "mfa_posture_checked": False,
            "session_analysis_checked": False,
            "connected_app_permissions_checked": False,
            "findings": [],
        },
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def install_commands(profile: dict[str, Any], args: argparse.Namespace) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "# Review before running. No secrets are embedded in this file.",
        f"bash skills/{profile['name']}/scripts/setup.sh --render --output-dir {q(args.output_dir)}",
        f"bash skills/{profile['name']}/scripts/validate.sh --dry-run",
        "",
        "# Live apply is opt-in and requires file-backed credentials plus --accept-apply.",
    ]
    for command in profile["apply_commands"](args):
        lines.append(command)
    lines.append("")
    return "\n".join(lines)


def okta_payload(args: argparse.Namespace) -> str:
    payload = {
        "name": args.hook_name,
        "events": {"type": "EVENT_TYPE", "items": csv_values(args.event_types)},
        "channel": {
            "type": "HTTP",
            "version": "1.0.0",
            "config": {"uri": args.receiver_url or "https://widefield.example.com/okta/events"},
        },
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def google_feed(args: argparse.Namespace) -> str:
    payload = {
        "displayName": args.feed_name,
        "logType": DEFAULTS["google_secops_log_type"],
        "sourceType": "WEBHOOK",
        "project": args.google_secops_project or "customer-project",
        "location": args.google_secops_region,
        "mutation": "render_only",
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def saviynt_map() -> str:
    return """# WideField to Saviynt remediation map
api_version: widefield-saviynt-integration-setup/v1
actions:
  - widefield_finding: compromised_identity
    saviynt_remediation: revoke_access
    mode: handoff
  - widefield_finding: stale_or_weak_credential
    saviynt_remediation: password_reset
    mode: handoff
  - widefield_finding: admin_without_mfa_or_weak_factor
    saviynt_remediation: micro_certification
    mode: handoff
  - widefield_finding: orphaned_non_human_identity
    saviynt_remediation: micro_certification
    mode: handoff
  - widefield_finding: over_privileged_connected_application
    saviynt_remediation: revoke_access
    mode: handoff
  - widefield_finding: ai_identity_access_risk
    saviynt_remediation: micro_certification
    mode: handoff
  - widefield_finding: anomalous_session_or_entitlement
    saviynt_remediation: micro_certification
    mode: handoff
live_mutation: unsupported_without_customer_api_reference
"""


def splunk_dashboard(args: argparse.Namespace) -> str:
    search = f"index={args.index} sourcetype={args.sourcetype} | spath | stats count by event_type severity"
    coverage_search = (
        f"index={args.index} sourcetype={args.sourcetype} | spath "
        "| eval signal=lower(coalesce(event_type,'finding.type',category,signature,message)) "
        "| eval capability=case(match(signal,\"credential|password|posture|long.?lived\"),\"identity_visibility_posture\","
        "match(signal,\"nhi|non.?human|service.?account|workload|orphan|attestation\"),\"non_human_identity_ownership\","
        "match(signal,\"mfa|admin|weak.?factor|account.?risk\"),\"human_identity_posture\","
        "match(signal,\"oauth|connected.?app|third.?party|consent|permission|over.?privileged|supply\"),\"connected_application_permission_risk\","
        "match(signal,\"ai|chatgpt|copilot|agent\"),\"ai_identity_access_monitoring\","
        "match(signal,\"session|mfa.?bypass|policy.?escape|high.?frequency|impossible\"),\"authentication_session_analysis\",true(),\"other\") "
        "| stats count by capability"
    )
    return f"""<dashboard version="1.1">
  <label>WideField Security Overview</label>
  <row>
    <panel>
      <title>WideField event types</title>
      <table>
        <search>
          <query>{search}</query>
          <earliest>-24h@h</earliest>
          <latest>now</latest>
        </search>
      </table>
    </panel>
  </row>
  <row>
    <panel>
      <title>WideField capability coverage</title>
      <table>
        <search>
          <query>{coverage_search}</query>
          <earliest>-24h@h</earliest>
          <latest>now</latest>
        </search>
      </table>
    </panel>
  </row>
</dashboard>
"""


def remediation_packets_md(args: argparse.Namespace) -> str:
    return f"""# Gated Remediation Packets

These packets are review artifacts. They do not execute destructive actions.

## OAuth Token Abuse and Connected Apps

- Evidence: WideField finding ID, actor, application, OAuth scopes, grant age, last use, and blast radius.
- Owner handoff: Okta app owner or identity security team.
- Allowed automation in this suite: render evidence and validate Okta/Splunk reachability.
- Blocked actions without owner runbook: revoke app grants, rotate tokens, disable apps, force logout.

## Non-Human Identity Ownership

- Evidence: identity ID, service/workload account type, inferred owner, attestation status, credential age, and permissions.
- Owner handoff: identity governance owner, Saviynt owner, or cloud/SaaS platform owner.
- Allowed automation in this suite: map to Saviynt `revoke_access`, `password_reset`, or `micro_certification` handoffs.
- Blocked actions without owner runbook: disable identity, revoke access, reset credentials.

## Human Identity Posture

- Evidence: user, admin status, MFA enrollment, weak factor, password/credential posture, and risk score.
- Owner handoff: Okta/IdP owner and governance owner.
- Allowed automation in this suite: render validation queries and record evidence in `readiness-evidence-template.json`.
- Blocked actions without owner runbook: password reset, factor reset, user suspension, universal logout.

## AI Identity Access

- Evidence: AI application name, identity used, permissions/scopes, prompts or connectors if available, and data exposure path.
- Owner handoff: AI app owner, identity security team, and data governance owner.
- Allowed automation in this suite: Splunk and Google SecOps evidence searches for `{args.sourcetype}` and `WIDEFIELD_SECURITY`.
- Blocked actions without owner runbook: revoke AI app access, remove connectors, disable agent identities.

## Authentication and Session Analysis

- Evidence: session ID, actor, source IP/device, MFA result, policy escape reason, session duration, and high-frequency login context.
- Owner handoff: Okta/IdP owner and incident response owner.
- Allowed automation in this suite: render Okta System Log checks and Splunk session searches.
- Blocked actions without owner runbook: force session revocation, universal logout, account lockout.
"""


def identity_checks(args: argparse.Namespace) -> str:
    return f"""# WideField identity threat doctor SPL

index={args.index} sourcetype={args.sourcetype}
| spath
| eval signal=lower(coalesce(event_type,'finding.type',category,signature,message))
| search signal="*oauth*" OR signal="*rogue*app*" OR signal="*connected*app*" OR signal="*third*party*" OR signal="*consent*"
| eval principal=coalesce('actor.email','actor.id','identity.id',user)
| stats count values(application.name) as apps values(oauth.scope) as scopes values(permissions) as permissions values(remediation.action) as remediation by event_type principal
| sort - count

index={args.index} sourcetype={args.sourcetype}
| spath
| eval token_age=coalesce('oauth.token.age_days','token.age_days')
| where token_age > 90
| table _time actor.email application.name token_age risk.score

index={args.index} sourcetype={args.sourcetype}
| spath
| eval signal=lower(coalesce(event_type,'finding.type',category,signature,message))
| search signal="*nhi*" OR signal="*non*human*" OR signal="*service*account*" OR signal="*workload*" OR signal="*orphan*"
| eval owner=coalesce('identity.owner.email','owner.email','owner.id')
| stats count values(owner) as owners values(attestation.status) as attestations values(permissions) as permissions by identity.id identity.name
| sort - count

index={args.index} sourcetype={args.sourcetype}
| spath
| eval signal=lower(coalesce(event_type,'finding.type',category,signature,message))
| search signal="*mfa*" OR signal="*admin*" OR signal="*weak*factor*" OR signal="*password*" OR signal="*credential*posture*"
| table _time event_type actor.email identity.admin mfa.enrolled mfa.factor credential.age_days risk.score remediation.action

index={args.index} sourcetype={args.sourcetype}
| spath
| eval signal=lower(coalesce(event_type,'finding.type',category,signature,message))
| search signal="*ai*" OR signal="*chatgpt*" OR signal="*copilot*" OR signal="*agent*"
| table _time event_type actor.email application.name ai.application ai.agent.id permissions risk.score remediation.action

index={args.index} sourcetype={args.sourcetype}
| spath
| eval signal=lower(coalesce(event_type,'finding.type',category,signature,message))
| search signal="*session*" OR signal="*mfa*bypass*" OR signal="*policy*escape*" OR signal="*high*frequency*login*" OR signal="*impossible*"
| table _time event_type actor.email session.id session.duration_minutes auth.policy mfa.result src_ip risk.score remediation.action
"""


def render_assets(profile: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    output_root = Path(args.output_dir).expanduser().resolve()
    profile_dir = output_root / profile["name"]
    files = [
        "metadata.json",
        "profile-plan.md",
        "handoffs.md",
        "install-commands.sh",
        "validation-searches.spl",
        "validation-queries.md",
        "readiness-evidence-template.json",
        "capability-coverage.md",
        "okta-oin-coverage.md",
        "remediation-packets.md",
        "source-ledger.md",
        "okta-event-hook-payload.json",
        "google-secops-feed.json",
        "saviynt-remediation-map.yaml",
        "splunk-dashboard.xml",
        "identity-threat-checks.spl",
    ]
    if args.dry_run:
        return {"ok": True, "dry_run": True, "output_dir": str(profile_dir), "files": files}
    write_file(profile_dir / "metadata.json", json.dumps(metadata(profile, args), indent=2, sort_keys=True) + "\n")
    write_file(profile_dir / "profile-plan.md", profile_plan(profile, args))
    write_file(profile_dir / "handoffs.md", handoffs_md(profile, args))
    write_file(profile_dir / "install-commands.sh", install_commands(profile, args), executable=True)
    write_file(profile_dir / "validation-searches.spl", validation_spl(args))
    write_file(profile_dir / "validation-queries.md", validation_queries(profile, args))
    write_file(profile_dir / "readiness-evidence-template.json", evidence_template(profile, args))
    write_file(profile_dir / "capability-coverage.md", capability_coverage_md(profile, args))
    write_file(profile_dir / "okta-oin-coverage.md", okta_oin_coverage_md())
    write_file(profile_dir / "remediation-packets.md", remediation_packets_md(args))
    write_file(profile_dir / "source-ledger.md", source_ledger_md())
    write_file(profile_dir / "okta-event-hook-payload.json", okta_payload(args))
    write_file(profile_dir / "google-secops-feed.json", google_feed(args))
    write_file(profile_dir / "saviynt-remediation-map.yaml", saviynt_map())
    write_file(profile_dir / "splunk-dashboard.xml", splunk_dashboard(args))
    write_file(profile_dir / "identity-threat-checks.spl", identity_checks(args))
    return {"ok": True, "dry_run": False, "output_dir": str(profile_dir), "files": files}


def emit(payload: dict[str, Any], json_output: bool, profile: dict[str, Any]) -> None:
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(f"Skill: {profile['name']}")
    print(f"Output: {payload['output_dir']}")
    print("Files: " + ", ".join(payload.get("files", [])))


def main(profile: dict[str, Any]) -> int:
    args = parse_args(profile)
    validate_args(args)
    emit(render_assets(profile, args), args.json, profile)
    return 0
