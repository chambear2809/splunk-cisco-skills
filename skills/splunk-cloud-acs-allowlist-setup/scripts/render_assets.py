#!/usr/bin/env python3
"""Render Splunk Cloud ACS allowlist assets."""

from __future__ import annotations

import argparse
import ipaddress
import json
import shlex
import stat
from pathlib import Path


FEATURES = (
    "acs",
    "search-api",
    "hec",
    "s2s",
    "search-ui",
    "idm-api",
    "idm-ui",
)

# Per Splunk doc: AWS groups share a 230-subnet cap across the features below.
AWS_GROUPS = {
    "search-head": ("search-api", "search-ui"),
    "indexer": ("hec", "s2s"),
    "idm": ("idm-api", "idm-ui"),
    "single-instance": ("search-api", "search-ui", "hec", "s2s"),
}
AWS_PER_FEATURE_CAP = 200
AWS_GROUP_CAP = 230
GCP_PER_FEATURE_CAP = 200

# Per Splunk doc: these features are open by default; everything else is
# closed by default. PCI/HIPAA stacks override `search-ui` to closed but the
# skill cannot detect compliance tier from public APIs; the README documents
# the exception.
DEFAULT_OPEN_FEATURES = ("acs", "hec", "s2s", "search-ui", "idm-api", "idm-ui")
DEFAULT_CLOSED_FEATURES = ("search-api",)

# Splunk Web features that depend on ACS — used by lock-out warning.
ACS_DEPENDENT_FEATURES = (
    "IP allowlist (IPv4 and IPv6)",
    "Federated Search",
    "Maintenance Windows (CMC app)",
    "Observability APIs",
    "Limits",
)

GENERATED_FILES = {
    "README.md",
    "metadata.json",
    "plan.json",
    "preflight.sh",
    "apply-ipv4.sh",
    "apply-ipv6.sh",
    "wait-for-ready.sh",
    "audit.sh",
    "terraform-snippets.tf",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render ACS allowlist assets.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--features", default="search-api,s2s,hec")
    parser.add_argument("--cloud-provider", choices=("aws", "gcp"), default="aws")
    parser.add_argument("--target-search-head", default="")
    parser.add_argument("--allow-acs-lockout", choices=("true", "false"), default="false")
    parser.add_argument("--strict-drift", choices=("true", "false"), default="true")
    parser.add_argument("--emit-terraform", choices=("true", "false"), default="false")
    parser.add_argument("--force", choices=("true", "false"), default="false")
    for feature in FEATURES:
        parser.add_argument(f"--{feature}-subnets", default="", dest=f"{feature.replace('-', '_')}_subnets")
        parser.add_argument(f"--{feature}-subnets-v6", default="", dest=f"{feature.replace('-', '_')}_subnets_v6")
    # Operator IPs for the ACS lock-out guard. CSV of IP/CIDR. When empty,
    # the rendered preflight does outbound public-IP discovery and fails
    # closed if discovery returns nothing while the `acs` feature is in the
    # plan and lock-out is not explicitly allowed.
    parser.add_argument("--operator-ips", default="", help="CSV of IPv4 IP/CIDR for the lock-out guard")
    parser.add_argument("--operator-ips-v6", default="", help="CSV of IPv6 IP/CIDR for the lock-out guard")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def shell_quote(value: object) -> str:
    return shlex.quote(str(value))


def csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def make_script(body: str) -> str:
    return "#!/usr/bin/env bash\nset -euo pipefail\n\n" + body.lstrip()


def clean_render_dir(render_dir: Path) -> None:
    for rel in GENERATED_FILES:
        candidate = render_dir / rel
        if candidate.is_file() or candidate.is_symlink():
            candidate.unlink()


def validate_subnet_ipv4(subnet: str, feature: str) -> str:
    try:
        net = ipaddress.IPv4Network(subnet, strict=False)
    except (ipaddress.AddressValueError, ValueError, ipaddress.NetmaskValueError) as exc:
        die(f"--{feature}-subnets contains invalid IPv4 subnet {subnet!r}: {exc}")
    return str(net)


def validate_subnet_ipv6(subnet: str, feature: str) -> str:
    try:
        net = ipaddress.IPv6Network(subnet, strict=False)
    except (ipaddress.AddressValueError, ValueError, ipaddress.NetmaskValueError) as exc:
        die(f"--{feature}-subnets-v6 contains invalid IPv6 subnet {subnet!r}: {exc}")
    return str(net)


def validate_features(features: list[str]) -> None:
    if not features:
        die("--features must specify at least one ACS feature.")
    invalid = [f for f in features if f not in FEATURES]
    if invalid:
        die(f"Unknown ACS feature(s): {', '.join(invalid)}. Allowed: {', '.join(FEATURES)}")


def validate_subnet_caps(plan: dict, cloud_provider: str) -> None:
    """Enforce AWS / GCP subnet limits up-front so apply never gets a 4xx."""
    per_feature_cap = AWS_PER_FEATURE_CAP if cloud_provider == "aws" else GCP_PER_FEATURE_CAP

    for feature, sets in plan["features"].items():
        combined = len(sets["ipv4"]) + len(sets["ipv6"])
        if combined > per_feature_cap:
            die(
                f"Feature '{feature}' would have {combined} subnets across IPv4+IPv6, "
                f"exceeding the {cloud_provider.upper()} per-feature cap of {per_feature_cap}."
            )

    if cloud_provider != "aws":
        return

    for group, members in AWS_GROUPS.items():
        total = sum(
            len(plan["features"][m]["ipv4"]) + len(plan["features"][m]["ipv6"])
            for m in members
            if m in plan["features"]
        )
        if total > AWS_GROUP_CAP:
            die(
                f"AWS group '{group}' (members: {', '.join(members)}) would have "
                f"{total} subnets, exceeding the per-group cap of {AWS_GROUP_CAP}."
            )


def build_plan(args: argparse.Namespace) -> dict:
    features = csv_list(args.features)
    validate_features(features)

    operator_ips_v4 = sorted({
        validate_subnet_ipv4(ip if "/" in ip else f"{ip}/32", "operator-ips")
        for ip in csv_list(args.operator_ips)
    })
    operator_ips_v6 = sorted({
        validate_subnet_ipv6(ip if "/" in ip else f"{ip}/128", "operator-ips-v6")
        for ip in csv_list(args.operator_ips_v6)
    })

    plan = {
        "version": 1,
        "cloud_provider": args.cloud_provider,
        "target_search_head": args.target_search_head or None,
        "allow_acs_lockout": args.allow_acs_lockout == "true",
        "strict_drift": args.strict_drift == "true",
        "force": args.force == "true",
        "features": {},
        "proposed_subnets": {},
        "operator_ips": {"ipv4": operator_ips_v4, "ipv6": operator_ips_v6},
        "default_state_notes": {
            f: ("open by default" if f in DEFAULT_OPEN_FEATURES else "closed by default")
            for f in FEATURES
        },
    }

    for feature in features:
        ipv4_attr = f"{feature.replace('-', '_')}_subnets"
        ipv6_attr = f"{feature.replace('-', '_')}_subnets_v6"
        ipv4 = sorted({validate_subnet_ipv4(s, feature) for s in csv_list(getattr(args, ipv4_attr))})
        ipv6 = sorted({validate_subnet_ipv6(s, feature) for s in csv_list(getattr(args, ipv6_attr))})
        plan["features"][feature] = {"ipv4": ipv4, "ipv6": ipv6}

    validate_subnet_caps(plan, args.cloud_provider)
    return plan


def render_plan_json(plan: dict) -> str:
    return json.dumps(plan, indent=2, sort_keys=True) + "\n"


def render_metadata(args: argparse.Namespace, plan: dict) -> str:
    return json.dumps(
        {
            "skill": "splunk-cloud-acs-allowlist-setup",
            "cloud_provider": plan["cloud_provider"],
            "features_in_plan": sorted(plan["features"].keys()),
            "ipv4_subnet_count": sum(len(v["ipv4"]) for v in plan["features"].values()),
            "ipv6_subnet_count": sum(len(v["ipv6"]) for v in plan["features"].values()),
            "allow_acs_lockout": plan["allow_acs_lockout"],
            "strict_drift": plan["strict_drift"],
            "target_search_head": plan["target_search_head"],
            "emit_terraform": args.emit_terraform == "true",
        },
        indent=2,
        sort_keys=True,
    ) + "\n"


def render_readme(plan: dict) -> str:
    rows = []
    for feature in FEATURES:
        sets = plan["features"].get(feature)
        if sets is None:
            rows.append(f"| {feature} | (not in plan) | (not in plan) |")
            continue
        ipv4_count = len(sets["ipv4"])
        ipv6_count = len(sets["ipv6"])
        rows.append(f"| {feature} | {ipv4_count} subnet(s) | {ipv6_count} subnet(s) |")
    table = "\n".join(rows)

    return f"""# Splunk Cloud ACS Allowlist Rendered Assets

Cloud provider: `{plan['cloud_provider']}`
Strict drift: `{plan['strict_drift']}`
Allow ACS lock-out: `{plan['allow_acs_lockout']}`
Target search head: `{plan.get('target_search_head') or '(stack default)'}`

## Plan summary

| Feature | IPv4 | IPv6 |
|---------|------|------|
{table}

## Files

- `plan.json` — full desired state.
- `preflight.sh` — FedRAMP / capability / lock-out / subnet-limit checks.
- `apply-ipv4.sh` and `apply-ipv6.sh` — converge live state to the plan.
- `wait-for-ready.sh` — polls `GET /adminconfig/v2/status` until `Ready`.
- `audit.sh` — re-snapshots and verifies plan vs. live equality.
- `terraform-snippets.tf` — `splunk/scp` resource blocks (only when emitted).

## Lock-out protection

Adding subnets to the `acs` feature allowlist can lock you out of these
Splunk Web features that depend on ACS:

- {ACS_DEPENDENT_FEATURES[0]}
- {ACS_DEPENDENT_FEATURES[1]}
- {ACS_DEPENDENT_FEATURES[2]}
- {ACS_DEPENDENT_FEATURES[3]}
- {ACS_DEPENDENT_FEATURES[4]}

`preflight.sh` refuses to apply the `acs` feature unless your current public IP
is in the planned subnet list, or `allow_acs_lockout=true`.

## AWS / GCP subnet limit math

- AWS per-feature cap: {AWS_PER_FEATURE_CAP} (IPv4 + IPv6 combined).
- AWS per-group cap: {AWS_GROUP_CAP} (sum across the group's features).
- GCP per-feature cap: {GCP_PER_FEATURE_CAP}.

`preflight.sh` enforces these before any apply call.

## Next steps

After apply succeeds and `wait-for-ready.sh` returns `Ready`:

1. Run `audit.sh` to verify live state matches the plan.
2. If you use Terraform, copy `terraform-snippets.tf` into your IaC repo.
3. Re-run with `--phase render` whenever the plan changes; commit the new
   `plan.json` next to your worksheet.
"""


def helper_path() -> Path:
    project_root = Path(__file__).resolve().parents[3]
    return project_root / "skills/shared/lib/credential_helpers.sh"


def render_preflight(plan: dict) -> str:
    helper = shell_quote(helper_path())
    cloud_provider = shell_quote(plan["cloud_provider"])
    target_sh = shell_quote(plan.get("target_search_head") or "")
    allow_acs_lockout = "true" if plan["allow_acs_lockout"] else "false"

    return make_script(
        f"""# shellcheck disable=SC1091
source {helper}
acs_prepare_context

CLOUD_PROVIDER={cloud_provider}
TARGET_SH={target_sh}
ALLOW_ACS_LOCKOUT={allow_acs_lockout}
PLAN_FILE="$(dirname "$0")/plan.json"

if [[ -n "${{TARGET_SH}}" ]]; then
  acs_command config use-stack "${{SPLUNK_CLOUD_STACK}}" --target-sh "${{TARGET_SH}}" >/dev/null
fi

# 1. Capability check (sc_admin or equivalent ACS access).
if ! acs_command status current-stack >/dev/null 2>&1; then
  echo "ERROR: ACS API access denied. Caller needs the sc_admin role or the equivalent ACS capability set." >&2
  exit 1
fi

# 2. FedRAMP carve-out: ACS does not manage allowlists on FedRAMP High stacks.
#    ACS surfaces the deployment type via stack metadata; we look for the
#    FedRAMP marker in the structured response and refuse to proceed.
status_payload=$(acs_command status current-stack 2>/dev/null | acs_extract_http_response_json || printf '%s' '{{}}')
fedramp_high=$(printf '%s' "${{status_payload}}" | python3 -c "
import json, sys
raw = sys.stdin.read()
try:
    data = json.loads(raw) if raw.strip() else {{}}
except Exception:
    data = {{}}
text = json.dumps(data).lower()
print('true' if ('fedramp-high' in text or 'fedramp_high' in text or 'govcloud-high' in text) else 'false')
")
if [[ "${{fedramp_high}}" == "true" ]]; then
  echo 'ERROR: This stack appears to be FedRAMP High. ACS does not manage IP allowlists there. Contact Splunk Support.' >&2
  exit 1
fi

# 3. Subnet limit enforcement (AWS per-feature, per-group; GCP per-feature).
python3 - "${{PLAN_FILE}}" "${{CLOUD_PROVIDER}}" <<'PY'
import json, sys
plan = json.load(open(sys.argv[1]))
provider = sys.argv[2]
PER_FEATURE = 200
GROUP_CAP = 230
AWS_GROUPS = {{
    "search-head": ("search-api", "search-ui"),
    "indexer": ("hec", "s2s"),
    "idm": ("idm-api", "idm-ui"),
    "single-instance": ("search-api", "search-ui", "hec", "s2s"),
}}
errors = []
for feature, sets in plan["features"].items():
    total = len(sets["ipv4"]) + len(sets["ipv6"])
    if total > PER_FEATURE:
        errors.append(f"feature {{feature}} has {{total}} subnets > {{PER_FEATURE}}")
if provider == "aws":
    for group, members in AWS_GROUPS.items():
        total = sum(len(plan["features"][m]["ipv4"]) + len(plan["features"][m]["ipv6"]) for m in members if m in plan["features"])
        if total > GROUP_CAP:
            errors.append(f"AWS group {{group}} ({{','.join(members)}}) has {{total}} subnets > {{GROUP_CAP}}")
if errors:
    print("ERROR: Subnet limit violations:", file=sys.stderr)
    for e in errors:
        print(f"  - {{e}}", file=sys.stderr)
    sys.exit(1)
PY

# 4. ACS feature lock-out protection. Uses real CIDR containment via Python's
#    ipaddress module so the check works for both /32 IPs and larger
#    planned subnets (e.g. /24). Fails closed: if the `acs` feature is in
#    the plan and we cannot prove that at least one operator IP is covered,
#    we refuse to render the apply scripts unless --allow-acs-lockout is set.
#
#    Operator candidates are:
#      a) IPs / CIDRs explicitly passed via --operator-ip / --operator-ip-v6
#         (preferred, especially for proxy / IPv6-only / private-egress
#         paths where outbound discovery cannot see the real client).
#      b) When the v4 list is empty, outbound discovery against multiple
#         independent endpoints. We do NOT do v6 discovery automatically;
#         operators on IPv6-only paths must pass --operator-ip-v6 if any
#         IPv6 subnets are in the planned `acs` set.
acs_planned_v4=$(python3 -c "import json; print(','.join(json.load(open('${{PLAN_FILE}}'))['features'].get('acs', {{}}).get('ipv4', [])))")
acs_planned_v6=$(python3 -c "import json; print(','.join(json.load(open('${{PLAN_FILE}}'))['features'].get('acs', {{}}).get('ipv6', [])))")
operator_v4=$(python3 -c "import json; print(','.join(json.load(open('${{PLAN_FILE}}')).get('operator_ips', {{}}).get('ipv4', [])))")
operator_v6=$(python3 -c "import json; print(','.join(json.load(open('${{PLAN_FILE}}')).get('operator_ips', {{}}).get('ipv6', [])))")

if [[ ( -n "${{acs_planned_v4}}" || -n "${{acs_planned_v6}}" ) && "${{ALLOW_ACS_LOCKOUT}}" != "true" ]]; then
  # Auto-discover v4 only when the operator did not supply one. Try multiple
  # independent endpoints so a single provider outage / egress filter does
  # not silently disable the guard.
  discovered_v4=""
  if [[ -z "${{operator_v4}}" ]]; then
    for url in https://checkip.amazonaws.com https://ifconfig.me https://api.ipify.org; do
      candidate=$(curl -sS --connect-timeout 5 --max-time 10 "${{url}}" 2>/dev/null | tr -d '[:space:]' || true)
      if [[ -n "${{candidate}}" ]]; then
        discovered_v4="${{candidate}}"
        break
      fi
    done
  fi

  # Fail closed if both candidate sources are empty for any planned family.
  if [[ -n "${{acs_planned_v4}}" && -z "${{operator_v4}}" && -z "${{discovered_v4}}" ]]; then
    cat >&2 <<EOM
ERROR: ACS lock-out guard cannot verify operator IPv4 coverage:
  - --operator-ip was not supplied, AND
  - outbound public IP discovery returned nothing (proxy/egress filter/outage).
Refusing to render the apply scripts because the planned 'acs' IPv4 subnets
would otherwise lock this caller out of ACS, IP allowlist, Federated Search,
Maintenance Windows, Observability APIs, and limits endpoints.

Re-run with one of:
  --operator-ip <your-public-ip-or-cidr>
  --allow-acs-lockout true   # only if you intend to lock out
EOM
    exit 1
  fi
  if [[ -n "${{acs_planned_v6}}" && -z "${{operator_v6}}" ]]; then
    cat >&2 <<EOM
ERROR: ACS lock-out guard cannot verify operator IPv6 coverage:
  - --operator-ip-v6 was not supplied (no automatic IPv6 discovery is
    performed because outbound IPv6 reachability does not always reflect the
    inbound admin path), AND
  - the plan includes 'acs' IPv6 subnets.
Refusing to render the apply scripts.

Re-run with one of:
  --operator-ip-v6 <your-public-ipv6-or-cidr>
  --allow-acs-lockout true   # only if you intend to lock out
EOM
    exit 1
  fi

  # Confirm at least one operator candidate is contained by the planned acs
  # subnets per family.
  contained=$(python3 - "${{acs_planned_v4}}" "${{acs_planned_v6}}" "${{operator_v4}}" "${{discovered_v4}}" "${{operator_v6}}" <<'PY'
import ipaddress, sys
acs_v4 = [s for s in sys.argv[1].split(',') if s]
acs_v6 = [s for s in sys.argv[2].split(',') if s]
ops_v4 = [s for s in (sys.argv[3] + ',' + sys.argv[4]).split(',') if s]
ops_v6 = [s for s in sys.argv[5].split(',') if s]


def covered(candidates: list[str], planned: list[str]) -> bool:
    for cand in candidates:
        try:
            ip = ipaddress.ip_interface(cand if '/' in cand else cand + '/32')
        except ValueError:
            continue
        for cidr in planned:
            try:
                net = ipaddress.ip_network(cidr, strict=False)
            except ValueError:
                continue
            if ip.network.subnet_of(net) or ip.ip in net:
                return True
    return False


problems = []
if acs_v4 and not covered(ops_v4, acs_v4):
    problems.append('ipv4')
if acs_v6 and not covered(ops_v6, acs_v6):
    problems.append('ipv6')
print(','.join(problems) if problems else 'ok')
PY
  )
  case "${{contained}}" in
    ok) ;;
    *)
      cat >&2 <<EOM
ERROR: ACS lock-out guard: planned 'acs' subnets do not cover the operator
       address(es) for: ${{contained}}.
Adding these subnets would lock this caller out of:
  - IP allowlist (IPv4 and IPv6)
  - Federated Search
  - Maintenance Windows (CMC app)
  - Observability APIs
  - Limits
Operator IPv4 candidates: ${{operator_v4:-<none>}} ${{discovered_v4:+(discovered: ${{discovered_v4}})}}
Operator IPv6 candidates: ${{operator_v6:-<none>}}

Add a covering CIDR for the missing family to the 'acs' subnet list,
pass an additional --operator-ip / --operator-ip-v6, or set
--allow-acs-lockout true to acknowledge the lock-out.
EOM
      exit 1
      ;;
  esac
fi

# 5. Drift detection: compare live state to the rendered plan, IPv4 + IPv6.
strict=$(python3 -c "import json; print('true' if json.load(open('${{PLAN_FILE}}'))['strict_drift'] else 'false')")
if [[ "${{strict}}" == "true" ]]; then
  drift_found=false
  for feature in $(python3 -c "import json; print(' '.join(json.load(open('${{PLAN_FILE}}'))['features'].keys()))"); do
    for family in ipv4 ipv6; do
      if [[ "${{family}}" == "ipv4" ]]; then
        cli_group=ip-allowlist
      else
        cli_group=ip-allowlist-v6
      fi
      live=$(acs_command "${{cli_group}}" describe "${{feature}}" 2>/dev/null | acs_extract_http_response_json | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    subs = data.get('subnets', []) if isinstance(data, dict) else []
    print(','.join(sorted([s if isinstance(s, str) else s.get('subnet', '') for s in subs])))
except Exception:
    print('')
")
      planned=$(python3 -c "import json; print(','.join(sorted(json.load(open('${{PLAN_FILE}}'))['features']['${{feature}}'].get('${{family}}', []))))")
      if [[ "${{live}}" != "${{planned}}" ]]; then
        printf 'WARNING: Drift detected on %s/%s (live=%s, plan=%s)\\n' "${{feature}}" "${{family}}" "${{live}}" "${{planned}}" >&2
        drift_found=true
      fi
    done
  done
  if [[ "${{drift_found}}" == "true" ]]; then
    echo 'ERROR: Live state has drifted from the rendered plan. Re-render or pass --force on the parent setup.sh.' >&2
    exit 1
  fi
fi

echo 'OK: ACS allowlist preflight passed.'
"""
    )


def render_apply(plan: dict, ipv6: bool) -> str:
    helper = shell_quote(helper_path())
    target_sh = shell_quote(plan.get("target_search_head") or "")
    family = "ipv6" if ipv6 else "ipv4"
    # Per Splunk ACS CLI docs (acs ip-allowlist --help, acs ip-allowlist-v6 --help):
    # IPv4 uses `acs ip-allowlist {describe,create,delete}`.
    # IPv6 uses the SEPARATE top-level command `acs ip-allowlist-v6 {describe,create,delete}`.
    cli_group = "ip-allowlist-v6" if ipv6 else "ip-allowlist"

    return make_script(
        f"""# shellcheck disable=SC1091
source {helper}
acs_prepare_context

TARGET_SH={target_sh}
PLAN_FILE="$(dirname "$0")/plan.json"
FAMILY={family!r}
CLI_GROUP={cli_group!r}

if [[ -n "${{TARGET_SH}}" ]]; then
  acs_command config use-stack "${{SPLUNK_CLOUD_STACK}}" --target-sh "${{TARGET_SH}}" >/dev/null
fi

features=$(python3 -c "import json; print(' '.join(sorted(json.load(open('${{PLAN_FILE}}'))['features'].keys())))")
for feature in ${{features}}; do
  planned=$(python3 -c "import json; print(','.join(sorted(json.load(open('${{PLAN_FILE}}'))['features']['${{feature}}']['${{FAMILY}}'])))" 2>/dev/null || echo "")

  # Per Splunk ACS CLI docs, the read-only subcommand is `describe` (not `list`).
  live_json=$(acs_command "${{CLI_GROUP}}" describe "${{feature}}" 2>/dev/null \\
    | acs_extract_http_response_json || printf '%s' '{{}}')
  live=$(printf '%s' "${{live_json}}" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    subs = data.get('subnets', []) if isinstance(data, dict) else []
    print(','.join(sorted([s if isinstance(s, str) else s.get('subnet', '') for s in subs])))
except Exception:
    print('')
")

  to_add=$(python3 - "${{planned}}" "${{live}}" <<'PY'
import sys
planned = set(filter(None, sys.argv[1].split(',')))
live = set(filter(None, sys.argv[2].split(',')))
print(','.join(sorted(planned - live)))
PY
  )
  to_remove=$(python3 - "${{planned}}" "${{live}}" <<'PY'
import sys
planned = set(filter(None, sys.argv[1].split(',')))
live = set(filter(None, sys.argv[2].split(',')))
print(','.join(sorted(live - planned)))
PY
  )

  if [[ -n "${{to_add}}" ]]; then
    log "Adding ${{FAMILY}} subnets to '${{feature}}': ${{to_add}}"
    acs_command "${{CLI_GROUP}}" create "${{feature}}" --subnets "${{to_add}}" >/dev/null
  fi
  if [[ -n "${{to_remove}}" ]]; then
    log "Removing ${{FAMILY}} subnets from '${{feature}}': ${{to_remove}}"
    acs_command "${{CLI_GROUP}}" delete "${{feature}}" --subnets "${{to_remove}}" >/dev/null
  fi
done

log "OK: ${{FAMILY}} apply complete. Run wait-for-ready.sh to confirm Ready status."
"""
    )


def render_wait_for_ready() -> str:
    helper = shell_quote(helper_path())
    return make_script(
        f"""# shellcheck disable=SC1091
source {helper}
acs_prepare_context

TIMEOUT_SECS=${{TIMEOUT_SECS:-900}}
INTERVAL_SECS=${{INTERVAL_SECS:-10}}
waited=0

# `acs status current-stack` returns
#   {{"status": {{"infrastructure": {{"status": "Ready" | "Pending" | "Failed"}}}}}}
parse_status() {{
  python3 -c "
import json, sys
text = sys.stdin.read()
if not text.strip():
    print('unknown'); sys.exit(0)
try:
    data = json.loads(text)
except Exception:
    print('unknown'); sys.exit(0)
infra = (data.get('infrastructure') or (data.get('status') or {{}}).get('infrastructure') or {{}})
print(infra.get('status', 'unknown'))
"
}}

while (( waited < TIMEOUT_SECS )); do
  payload=$(acs_command status current-stack 2>/dev/null | acs_extract_http_response_json || printf '%s' '{{}}')
  status=$(printf '%s' "${{payload}}" | parse_status)
  case "${{status}}" in
    Ready)
      echo "OK: ACS reports Ready."
      exit 0
      ;;
    Failed)
      echo "ERROR: ACS reports Failed status. See ${{payload}}" >&2
      exit 1
      ;;
    *)
      log "ACS status=${{status}}, waiting..."
      sleep "${{INTERVAL_SECS}}"
      waited=$((waited + INTERVAL_SECS))
      ;;
  esac
done

echo "ERROR: Timed out waiting for ACS to reach Ready." >&2
exit 1
"""
    )


def render_audit() -> str:
    helper = shell_quote(helper_path())
    return make_script(
        f"""# shellcheck disable=SC1091
source {helper}
acs_prepare_context

PLAN_FILE="$(dirname "$0")/plan.json"
TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
AUDIT_DIR="$(dirname "$0")/audit/${{TIMESTAMP}}"
mkdir -p "${{AUDIT_DIR}}"

features=$(python3 -c "import json; print(' '.join(sorted(json.load(open('${{PLAN_FILE}}'))['features'].keys())))")

mismatch=false

for feature in ${{features}}; do
  for family in ipv4 ipv6; do
    # Per Splunk ACS CLI: IPv4 = `acs ip-allowlist describe`,
    # IPv6 = `acs ip-allowlist-v6 describe`.
    if [[ "${{family}}" == "ipv4" ]]; then
      cli_group=ip-allowlist
    else
      cli_group=ip-allowlist-v6
    fi
    snapshot_path="${{AUDIT_DIR}}/${{feature}}-${{family}}.json"
    acs_command "${{cli_group}}" describe "${{feature}}" 2>/dev/null \\
      | acs_extract_http_response_json > "${{snapshot_path}}" || printf '%s' '{{}}' > "${{snapshot_path}}"

    live=$(python3 -c "
import json, sys
try:
    data = json.load(open(sys.argv[1]))
except Exception:
    data = {{}}
subs = data.get('subnets', []) if isinstance(data, dict) else []
print(','.join(sorted([s if isinstance(s, str) else s.get('subnet', '') for s in subs])))
" "${{snapshot_path}}" 2>/dev/null || printf '')
    planned=$(python3 -c "
import json, sys
plan = json.load(open(sys.argv[1]))
print(','.join(sorted(plan['features'].get(sys.argv[2], {{}}).get(sys.argv[3], []))))
" "${{PLAN_FILE}}" "${{feature}}" "${{family}}" 2>/dev/null || printf '')
    if [[ "${{live}}" != "${{planned}}" ]]; then
      printf 'MISMATCH: feature=%s family=%s live=%s plan=%s\\n' "${{feature}}" "${{family}}" "${{live}}" "${{planned}}"
      mismatch=true
    fi
  done
done

if [[ "${{mismatch}}" == "true" ]]; then
  echo "WARNING: Live state differs from the rendered plan. See ${{AUDIT_DIR}} for details." >&2
  exit 1
fi
echo "OK: Live state matches the rendered plan. Snapshot saved to ${{AUDIT_DIR}}."
"""
    )


def render_terraform_snippets(plan: dict) -> str:
    if not plan["features"]:
        return "# splunk/scp Terraform snippets (no features in plan)\n"
    # Per the Splunk Cloud Platform Terraform Provider docs, the resource type
    # is `scp_ip_allowlists` (plural) and accepts the documented features
    # (acs, search-api, hec, s2s, search-ui, idm-api, idm-ui). The provider
    # currently exposes IPv4 only via this resource; IPv6 lists must be
    # managed via the ACS CLI / API until the provider adds an IPv6 resource.
    lines = [
        "# Splunk Cloud Platform Terraform Provider snippets.",
        "# Provider: splunk/scp (https://registry.terraform.io/providers/splunk/scp/latest).",
        "# Note: the provider exposes IPv4 allowlists via scp_ip_allowlists; IPv6",
        "# lists must continue to be managed through the ACS CLI / acs ip-allowlist-v6.",
        "",
        'terraform {',
        '  required_providers {',
        '    scp = {',
        '      source  = "splunk/scp"',
        '    }',
        '  }',
        '}',
        "",
        'provider "scp" {',
        '  stack          = var.stack',
        '  authentication = var.scp_auth_token',
        "}",
        "",
    ]
    for feature, sets in sorted(plan["features"].items()):
        if sets["ipv4"]:
            # Provider docs require the resource name to match the feature
            # name to avoid duplicate-resource errors.
            tf_name = feature.replace("-", "_")
            lines.append(f'resource "scp_ip_allowlists" "{tf_name}" {{')
            lines.append(f'  feature = "{feature}"')
            ipv4_block = ", ".join(f'"{s}"' for s in sets["ipv4"])
            lines.append(f"  subnets = [{ipv4_block}]")
            lines.append("}")
            lines.append("")
        if sets["ipv6"]:
            lines.append(f"# IPv6 allowlist for feature '{feature}' is not exposed by")
            lines.append("# splunk/scp at this time. Manage it via:")
            ipv6_csv = ",".join(sets["ipv6"])
            lines.append(f"#   acs ip-allowlist-v6 create {feature} --subnets '{ipv6_csv}'")
            lines.append("")
    return "\n".join(lines)


def render_all(args: argparse.Namespace) -> dict:
    plan = build_plan(args)

    output_dir = Path(args.output_dir).expanduser().resolve()
    render_dir = output_dir / "allowlist"
    render_dir.mkdir(parents=True, exist_ok=True)
    clean_render_dir(render_dir)

    artifacts = {
        "README.md": render_readme(plan),
        "metadata.json": render_metadata(args, plan),
        "plan.json": render_plan_json(plan),
        "preflight.sh": render_preflight(plan),
        "apply-ipv4.sh": render_apply(plan, ipv6=False),
        "apply-ipv6.sh": render_apply(plan, ipv6=True),
        "wait-for-ready.sh": render_wait_for_ready(),
        "audit.sh": render_audit(),
    }
    if args.emit_terraform == "true":
        artifacts["terraform-snippets.tf"] = render_terraform_snippets(plan)

    for name, content in artifacts.items():
        path = render_dir / name
        write_file(path, content, executable=name.endswith(".sh"))

    return {
        "render_dir": str(render_dir),
        "files": sorted(artifacts.keys()),
        "plan": plan,
    }


def main() -> None:
    args = parse_args()
    if args.dry_run:
        plan = build_plan(args)
        if args.json:
            print(json.dumps({"plan": plan}, indent=2, sort_keys=True))
        else:
            print(json.dumps(plan, indent=2, sort_keys=True))
        return
    result = render_all(args)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Rendered {len(result['files'])} ACS allowlist asset(s) to {result['render_dir']}")
        for name in result["files"]:
            print(f"  - {name}")


if __name__ == "__main__":
    main()
