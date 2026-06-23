#!/usr/bin/env python3
"""Render Meraki AAM + ThousandEyes review artifacts from an intake spec."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "shared" / "lib"))

from yaml_compat import dump_yaml, load_yaml_or_json  # noqa: E402


SUPPORTED_MX_MODELS = {
    "MX67",
    "MX67W",
    "MX67C",
    "MX68",
    "MX68W",
    "MX68CW",
    "MX75",
    "MX85",
    "MX95",
    "MX105",
    "MX250",
    "MX450",
    "C8111-G2",
    "C8111-C-G2",
    "C8121-G2",
    "C8121-W-G2",
    "C8121-CW-G2",
    "C8455-G2",
}


def normalize_mx_model(model: str) -> str:
    value = model.strip().upper()
    if value in SUPPORTED_MX_MODELS:
        return value
    for suffix in ("-NA", "-WW", "-RW", "-EU"):
        if value.endswith(suffix):
            candidate = value[: -len(suffix)]
            if candidate in SUPPORTED_MX_MODELS:
                return candidate
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, help="YAML or JSON intake spec")
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def read_spec(path: Path) -> dict[str, Any]:
    data = load_yaml_or_json(path.read_text(encoding="utf-8"), source=str(path))
    if not isinstance(data, dict):
        raise SystemExit(f"Spec must be a mapping: {path}")
    return data


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "application"


def scalar(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def bool_text(value: Any) -> str:
    return "yes" if bool(value) else "no"


def list_items(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- None"


def check_networks(networks: list[dict[str, Any]]) -> list[str]:
    findings: list[str] = []
    for network in networks:
        name = scalar(network.get("name"), "unnamed network")
        model = normalize_mx_model(scalar(network.get("mx_model")))
        firmware = scalar(network.get("firmware"), "unknown")
        license_name = scalar(network.get("license"), "unknown")
        if model and model not in SUPPORTED_MX_MODELS:
            findings.append(f"{name}: MX model `{model}` is not in the public supported list.")
        if firmware != "unknown" and not firmware.startswith(("18.", "19.", "20.")):
            findings.append(f"{name}: firmware `{firmware}` needs manual review; minimum is MX 18.104.")
        if not network.get("nat_mode_confirmed"):
            findings.append(f"{name}: NAT mode not confirmed.")
        if license_name == "enterprise":
            findings.append(f"{name}: Enterprise license is not sufficient for AAM ThousandEyes.")
        if license_name == "advanced-security":
            findings.append(
                f"{name}: Advanced Security supports agent install; verify purchased ThousandEyes units for tests."
            )
    return findings


def render_plan(spec: dict[str, Any]) -> str:
    meraki = spec.get("meraki", {}) or {}
    te = spec.get("thousandeyes", {}) or {}
    app = spec.get("application", {}) or {}
    networks = spec.get("networks", []) or []
    validation = spec.get("validation", {}) or {}
    findings = check_networks([n for n in networks if isinstance(n, dict)])

    network_rows = []
    for network in networks:
        if not isinstance(network, dict):
            continue
        network_rows.append(
            "| {name} | {network_id} | {model} | {firmware} | {nat} | {license} | {topology} |".format(
                name=scalar(network.get("name"), "unknown"),
                network_id=scalar(network.get("network_id"), "unknown"),
                model=scalar(network.get("mx_model"), "unknown"),
                firmware=scalar(network.get("firmware"), "unknown"),
                nat=bool_text(network.get("nat_mode_confirmed")),
                license=scalar(network.get("license"), "unknown"),
                topology=scalar(network.get("topology"), "unknown"),
            )
        )
    if not network_rows:
        network_rows.append("| TODO | TODO | TODO | TODO | no | unknown | unknown |")

    target = scalar(app.get("target_url"), "TODO_TARGET")
    app_name = scalar(app.get("name"), "TODO application")
    interval = scalar(app.get("interval_seconds"), "300")

    return f"""# Meraki AAM ThousandEyes Plan

## Scope

- Meraki organization: `{scalar(meraki.get("organization_name"), "unknown")}` (`{scalar(meraki.get("organization_id"), "unknown")}`)
- Meraki dashboard: `{scalar(meraki.get("dashboard_url"), "unknown")}`
- Meraki region: `{scalar(meraki.get("dashboard_region"), "unknown")}`
- ThousandEyes account group: `{scalar(te.get("account_group_name"), "unknown")}` (`{scalar(te.get("account_group_id"), "unknown")}`)
- ThousandEyes region: `{scalar(te.get("account_region"), "unknown")}`
- Application: `{app_name}`
- Target: `{target}`
- Profile: `{scalar(app.get("profile"), "custom-http-server")}`
- Interval seconds: `{interval}`

## Preflight Checklist

- [ ] Meraki has at least two full organization admins: `{bool_text(meraki.get("full_org_admins_confirmed"))}`.
- [ ] ThousandEyes Account Admin confirmed: `{bool_text(te.get("account_admin_confirmed"))}`.
- [ ] ThousandEyes local auth available for linking: `{bool_text(te.get("local_auth_available_confirmed"))}`.
- [ ] Meraki and ThousandEyes regions are compatible.
- [ ] Supported MX model, firmware MX 18.104+, NAT mode, and connectivity are confirmed for each network.
- [ ] License and ThousandEyes unit posture is confirmed before creating tests.
- [ ] User confirms before final `Start monitoring`, free-test claim, delete, disconnect, or replay action.

## Networks

| Network | Network ID | MX model | Firmware | NAT confirmed | License | Topology |
| --- | --- | --- | --- | --- | --- | --- |
{chr(10).join(network_rows)}

## Findings To Resolve

{list_items(findings)}

## Meraki Dashboard Procedure

1. Open Meraki Dashboard for the target organization.
2. Go to `Insight > Active Application Monitoring`.
3. If prompted, click `Try it` or `Get started`.
4. Link the ThousandEyes account. Use browser login; do not collect credentials in chat.
5. Select the account group if the user has multiple ThousandEyes account groups.
6. Select a verified application template or custom target for `{app_name}`.
7. Fill tenant/subdomain if required: `{scalar(app.get("tenant_or_subdomain"), "not required or TODO")}`.
8. Select the eligible Meraki networks listed above.
9. Review the summary screen.
10. Confirm the final side effect with the user before clicking `Start monitoring`.

## Validation Targets

- Expected Meraki network filter: `{scalar(validation.get("meraki_network_filter"), scalar(networks[0].get("name") if networks and isinstance(networks[0], dict) else "", ""))}`
- Expected Meraki MX serial filter: `{scalar(validation.get("meraki_mx_serial_filter"), "")}`
- Expected agent name filter: `{scalar(validation.get("agent_name_filter"), app_name)}`
- Expected test name filter: `{scalar(validation.get("test_name_filter"), app_name)}`
- Wait after start: `{scalar(validation.get("wait_minutes_after_start"), "15")}` minutes

Run read-only Meraki API preflight with a rotated key file:

```bash
bash skills/cisco-meraki-aam-thousandeyes-setup/scripts/validate.sh \\
  --meraki-api-key-file /path/to/rotated_meraki_api_key \\
  --meraki-org-id "{scalar(meraki.get("organization_id"), "123456")}" \\
  --network-filter "{scalar(validation.get("meraki_network_filter"), scalar(networks[0].get("name") if networks and isinstance(networks[0], dict) else "", ""))}" \\
  --mx-serial-filter "{scalar(validation.get("meraki_mx_serial_filter"), "")}" \\
  --output-dir live-validation
```

Run ThousandEyes validation after the wizard starts monitoring:

```bash
bash skills/cisco-meraki-aam-thousandeyes-setup/scripts/validate.sh \\
  --te-token-file /path/to/te_token \\
  --account-group-id "{scalar(te.get("account_group_id"), "1234")}" \\
  --agent-filter "{scalar(validation.get("agent_name_filter"), app_name)}" \\
  --test-filter "{scalar(validation.get("test_name_filter"), app_name)}" \\
  --output-dir live-validation
```
"""


def render_capture_checklist(spec: dict[str, Any]) -> str:
    capture = spec.get("capture", {}) or {}
    steps = capture.get("expected_ui_steps", []) or []
    return f"""# Browser Capture Checklist

Use this when the user asks to inspect Meraki Dashboard POSTs for AAM.

Raw HAR files are sensitive. Keep them local and use the redacted summary from
`scripts/summarize_har.py` for discussion.

## Expected UI Steps

{list_items([str(step) for step in steps])}

## Capture Command

```bash
python3 skills/cisco-meraki-aam-thousandeyes-setup/scripts/summarize_har.py \\
  --har "{scalar(capture.get("har_path"), "~/Downloads/meraki-aam.har")}" \\
  --output-md har-summary.md \\
  --output-json har-summary.json \\
  --url-filter meraki
```

## Evidence To Record

- Account-link initiation and callback requests.
- Application/template catalog and tenant validation requests.
- Eligible network lookup.
- Start-monitoring/deployment request.
- Free-test claim request, if present.
- Agent list or monitored network refresh after deployment.

Do not replay private Meraki requests without explicit user confirmation of the
exact organization, endpoint, payload, and side effect.
"""


def render_validation_doc(spec: dict[str, Any]) -> str:
    meraki = spec.get("meraki", {}) or {}
    te = spec.get("thousandeyes", {}) or {}
    validation = spec.get("validation", {}) or {}
    return f"""# Meraki And ThousandEyes Validation

Use public Meraki Dashboard API v1 for read-only preflight before the wizard.
Use public ThousandEyes API v7 after the Meraki Dashboard wizard has started
monitoring and the propagation window has elapsed.

## Meraki Preflight Command

```bash
bash skills/cisco-meraki-aam-thousandeyes-setup/scripts/validate.sh \\
  --meraki-api-key-file /path/to/rotated_meraki_api_key \\
  --meraki-org-id "{scalar(meraki.get("organization_id"), "123456")}" \\
  --network-filter "{scalar(validation.get("meraki_network_filter"), "")}" \\
  --mx-serial-filter "{scalar(validation.get("meraki_mx_serial_filter"), "")}" \\
  --output-dir live-validation
```

## ThousandEyes Command

```bash
bash skills/cisco-meraki-aam-thousandeyes-setup/scripts/validate.sh \\
  --te-token-file /path/to/te_token \\
  --account-group-id "{scalar(te.get("account_group_id"), "1234")}" \\
  --agent-filter "{scalar(validation.get("agent_name_filter"), "")}" \\
  --test-filter "{scalar(validation.get("test_name_filter"), "")}" \\
  --output-dir live-validation
```

## Evidence

- `agents.json`: raw `GET /v7/agents` response.
- `tests.json`: raw `GET /v7/tests` response.
- `meraki-organizations.json`: raw Meraki organization list response.
- `meraki-networks.json`: raw Meraki organization networks response.
- `meraki-devices.json`: raw Meraki organization devices response.
- `summary.md`: filtered agent/test summary.
- Meraki Dashboard Monitored Networks page or Agent List screenshot, if visual
  evidence is needed.

## Pass Criteria

- At least one expected MX-hosted Enterprise Agent is online.
- Expected tests exist and are assigned to the intended agent IDs.
- Results appear in ThousandEyes after the Meraki-documented propagation window.
- Splunk ingestion, if in scope, is validated separately with
  `cisco-thousandeyes-setup`.
"""


def render_handoff_spec(spec: dict[str, Any]) -> dict[str, Any]:
    app = spec.get("application", {}) or {}
    te = spec.get("thousandeyes", {}) or {}
    app_name = scalar(app.get("name"), "Meraki AAM application")
    target = scalar(app.get("target_url"), "TODO_TARGET")
    interval = int(app.get("interval_seconds") or 300)
    profile = scalar(app.get("profile"), "custom-http-server")
    tests: list[dict[str, Any]] = []

    if profile in {"custom-http-server", "verified-template", "both"}:
        tests.append(
            {
                "type": "http-server",
                "name": f"{app_name} from Meraki MX",
                "target": target,
                "url": target,
                "interval": interval,
                "enabled": True,
                "alerts_enabled": bool(app.get("alerts_enabled")),
                "agents": ["TODO_REPLACE_WITH_MERAKI_AGENT_IDS"],
                "expected_status_code": app.get("expected_status_code", 200),
                "verify_content": scalar(app.get("verify_content")),
            }
        )
    if profile in {"custom-network", "both"}:
        tests.append(
            {
                "type": "agent-to-server",
                "name": f"{app_name} network from Meraki MX",
                "target": target,
                "server": target,
                "interval": interval,
                "enabled": True,
                "alerts_enabled": bool(app.get("alerts_enabled")),
                "agents": ["TODO_REPLACE_WITH_MERAKI_AGENT_IDS"],
            }
        )

    return {
        "api_version": "splunk-observability-thousandeyes-integration/v1",
        "account_group_id": scalar(te.get("account_group_id")),
        "stream": {"enabled": False},
        "apm_connector": {"enabled": False},
        "tests": tests,
        "labels": [{"name": f"meraki-aam-{slugify(app_name)}", "color": "#0B6E69"}],
        "tags": [{"name": "source:meraki-aam"}, {"name": f"application:{slugify(app_name)}"}],
        "dashboards": {"enabled": False, "test_types": []},
        "detectors": {"enabled": False, "test_types": []},
        "handoffs": {
            "dashboard_builder": False,
            "native_ops": False,
            "mcp_setup": True,
            "splunk_platform_ta": True,
        },
        "notes": [
            "Replace TODO_REPLACE_WITH_MERAKI_AGENT_IDS after validate.sh confirms the MX-hosted Enterprise Agent IDs.",
            "Use Meraki Dashboard UI for AAM agent deployment; this handoff is for public ThousandEyes API assets after agents exist.",
        ],
    }


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    args = parse_args()
    spec_path = Path(args.spec)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    spec = read_spec(spec_path)

    write(out / "meraki-aam-plan.md", render_plan(spec))
    write(out / "browser-capture-checklist.md", render_capture_checklist(spec))
    write(out / "thousandeyes-validation.md", render_validation_doc(spec))
    write(out / "handoff-thousandeyes-api-tests.yaml", dump_yaml(render_handoff_spec(spec), sort_keys=False))
    write(
        out / "metadata.json",
        json.dumps(
            {
                "skill": "cisco-meraki-aam-thousandeyes-setup",
                "spec": str(spec_path),
                "outputs": [
                    "meraki-aam-plan.md",
                    "browser-capture-checklist.md",
                    "thousandeyes-validation.md",
                    "handoff-thousandeyes-api-tests.yaml",
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
