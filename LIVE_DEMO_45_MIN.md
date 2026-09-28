# Live 45-Minute Demo: From Cisco Request to Validated Splunk Visibility

## Demo promise

Show one repeatable operator motion rather than touring the full skills catalog:

1. discover the right workflow,
2. resolve a Cisco product to its supported Splunk path,
3. inspect a real Splunk target safely,
4. create one private, reviewable dashboard from live Splunk data, and
5. validate the result and explain what remains incomplete.

The preferred target is a disposable Splunk Enterprise search tier. Splunk Cloud
works when ACS access and search-tier REST access are already prepared.

The live mutation in the core path is a private Dashboard Studio view over
`index=_internal`. Cisco-specific onboarding is a read-only branch unless a
real Cisco endpoint, installed TA, and separately approved secret files are
already prepared.

## Demo contract

Say this before touching the target:

> This is a real target, so the repo's safety model is part of the demo. We will
> keep secrets in local files, use read-only checks first, render before apply,
> keep the dashboard private, and validate the exact live object afterward. We
> will not install an unreviewed package, create a global object, restart a
> production stack, or pretend that package presence equals working telemetry.

Use a unique dashboard name such as `codex_skills_demo_20260919`. Do not use a
production dashboard name. Do not put passwords, API keys, HEC tokens, device
passwords, or session keys in the terminal transcript.

## Rehearse before the meeting

Select a named credentials profile with:

- an explicitly known `enterprise` or `cloud` platform;
- a search-tier or standalone REST target;
- an `https://` search API URI;
- `SPLUNK_VERIFY_SSL=true`, or a trusted `SPLUNK_CA_CERT` instead of disabling
  certificate verification;
- permissions to read `_internal`, list apps, read `data/ui/views`, and create
  a private dashboard;
- for Cloud, a working ACS context and a search API allowlist entry for the
  presenter workstation.

The profile name is non-secret. The password remains in the project
`credentials` file or the normal local credential store.

```bash
export DEMO_PROFILE="replace-with-a-named-profile"
export DEMO_PLATFORM="enterprise"       # enterprise or cloud
export SPLUNK_PROFILE="$DEMO_PROFILE"
export DEMO_OUTPUT="/tmp/splunk-skills-demo"
export DEMO_DASHBOARD="codex_skills_demo_$(date +%Y%m%d)"

bash skills/splunk-admin-doctor/scripts/setup.sh --help
bash skills/cisco-product-setup/scripts/setup.sh --help
bash skills/splunk-dashboard-studio-setup/scripts/setup.sh --help

python3 skills/splunk-admin-doctor/scripts/live_validate_all.py \
  --profile "$DEMO_PROFILE" \
  --platform "$DEMO_PLATFORM" \
  --skill splunk-admin-doctor \
  --output-dir "$DEMO_OUTPUT/admin-doctor" \
  --plan-only --json
```

Run one read-only rehearsal after the plan looks correct:

```bash
python3 skills/splunk-admin-doctor/scripts/live_validate_all.py \
  --profile "$DEMO_PROFILE" \
  --platform "$DEMO_PLATFORM" \
  --skill splunk-admin-doctor \
  --output-dir "$DEMO_OUTPUT/admin-doctor" \
  --max-retained-runs 10 \
  --once --json
```

If this fails on TLS, DNS, the network path, or a Cloud allowlist, stop and fix
the profile. Do not work around it with `SPLUNK_VERIFY_SSL=false` during the
demo. If live access cannot be repaired, use the render-only fallback below.

## Run of show

| Time | Segment | Live proof |
|---|---|---|
| 0:00–0:03 | Frame the problem | A Splunk admin needs a repeatable Cisco-to-Splunk onboarding path |
| 0:03–0:08 | Repo and agent discovery | The agent finds the skill, template, validator, and safety gates |
| 0:08–0:14 | Cisco routing | A product request resolves to an actual child skill and required inputs |
| 0:14–0:21 | Splunk health and inventory | Admin Doctor and installed-app inventory read the real target |
| 0:21–0:27 | Data readiness | The repo checks whether Cisco evidence is actually present |
| 0:27–0:35 | Render and apply | A private Dashboard Studio view is rendered, reviewed, and applied |
| 0:35–0:41 | Validate | Exact dashboard content/ACL and live search evidence are read back |
| 0:41–0:45 | Cisco branch and close | Show TA completion evidence or an honest gap/handoff |

## 0:00–0:03 — Opening narration

“The request is not ‘install a Cisco app.’ The request is ‘give operators
usable Cisco visibility in Splunk.’ This repository turns that into a repeatable
motion: choose the right workflow, collect non-secret inputs, keep secrets out
of chat, render the plan, apply only the approved change, and validate data and
consumers afterward.”

Show the top of `README.md`, then point to:

- `SKILL_UX_CATALOG.md` for product-first routing;
- `CLOUD_DEPLOYMENT_MATRIX.md` for Cloud versus Enterprise placement;
- `skills/shared/ta_completion_gate.md` for the rule that installation alone is
  not completion.

## 0:03–0:08 — Agent discovery and safety

If the local `splunk-cisco-skills` MCP server is connected, use read-only tools
in this order:

1. `credential_status` — prove only that the credential route exists and is
   private; never read its values.
2. `get_server_status` — show execution enabled for planning while generic
   execution and mutation remain disabled.
3. `search_skills` with `query="dashboard"` or `product="Splunk Platform"`.
4. `get_skill_manifest` for `splunk-dashboard-studio-setup`.
5. `read_skill_file` for its `SKILL.md` and `template.example`.

Say:

“The local MCP server is a bounded discovery and planning surface. It can find
and explain a workflow, but the normal registration does not authorize generic
mutation. That separation is visible to the audience and makes the approval
boundary concrete.”

If MCP is unavailable, use the shell fallback:

```bash
rg -n "Dashboard Studio|Admin Doctor|Cisco ACI|completion gate" \
  SKILL_UX_CATALOG.md README.md skills/shared/ta_completion_gate.md
sed -n '1,180p' skills/splunk-dashboard-studio-setup/SKILL.md
```

## 0:08–0:14 — Resolve a Cisco request

Use Cisco ACI as the primary example because it resolves to an automated
workflow with a visible app, inputs, and dashboards:

```bash
bash skills/cisco-product-setup/scripts/setup.sh \
  --product "Cisco ACI" \
  --dry-run --json
```

Call out the output fields:

- `primary_skill`: `cisco-dc-networking-setup`;
- app ID and package name;
- required non-secret values: account name, APIC hostname, username;
- secret requirement: password file only;
- dashboard names and target index;
- planned phases: install, configure, validate.

Then show the repo refusing to overclaim on a different collection path:

```bash
bash skills/cisco-product-setup/scripts/setup.sh \
  --product "Cisco ASA syslog" \
  --dry-run --json
```

Narration:

“ASA syslog is a receiver-owned handoff, not an excuse for the agent to open a
listener or claim that the TA is complete. The plan says what is automated and
what still requires SC4S or syslog ownership.”

Do not execute Cisco setup in this segment. The point is product-aware routing,
not typing a device password into a live call.

## 0:14–0:21 — Inspect the real Splunk target

Run the bounded read-only Admin Doctor sweep:

```bash
python3 skills/splunk-admin-doctor/scripts/live_validate_all.py \
  --profile "$DEMO_PROFILE" \
  --platform "$DEMO_PLATFORM" \
  --skill splunk-admin-doctor \
  --output-dir "$DEMO_OUTPUT/admin-doctor" \
  --max-retained-runs 10 \
  --once --json
```

Open the printed `final-report.md` and point to the distinction between:

- evidence collected versus evidence not assessed;
- report validity versus platform health;
- direct findings versus delegated fixes.

Then inventory installed Cisco apps without installing anything:

```bash
bash skills/splunk-app-install/scripts/setup.sh \
  --list --filter cisco
```

Narration:

“This is the point where a live demo becomes honest. We now know what the
target says about itself, what Cisco packages are actually installed, and which
claims still need data evidence.”

## 0:21–0:27 — Check Cisco data readiness

First list the source-pack contract:

```bash
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh \
  --phase source-packs --source-pack cisco_asa --json
```

For a target where Cisco ASA data is expected, mint a temporary session key in
the presenter shell without printing it:

```bash
source skills/shared/lib/credential_helpers.sh
load_splunk_credentials
DEMO_SPLUNK_URI="${SPLUNK_SEARCH_API_URI:-${SPLUNK_URI}}"
DEMO_SPLUNK_USER="$SPLUNK_USER"

DEMO_SESSION_KEY_FILE="$(mktemp -t splunk-skills-demo-session.XXXXXX)"
chmod 600 "$DEMO_SESSION_KEY_FILE"
trap 'rm -f "$DEMO_SESSION_KEY_FILE"' EXIT
get_session_key "$DEMO_SPLUNK_URI" > "$DEMO_SESSION_KEY_FILE"
```

Collect bounded, read-only evidence:

```bash
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh \
  --phase collect \
  --platform "$DEMO_PLATFORM" \
  --splunk-uri "$DEMO_SPLUNK_URI" \
  --session-key-file "$DEMO_SESSION_KEY_FILE" \
  --source-pack cisco_asa \
  --max-searches 12 \
  --max-rows 20 \
  --collect-timeout-seconds 20 \
  --output-dir "$DEMO_OUTPUT/readiness" \
  --json
```

If `cisco:asa` events exist, show the event, source type, index, latency, CIM,
and dashboard/readiness evidence. If they do not exist, say so plainly:

“The router and TA may be correct, but the completion gate is still open. The
next action belongs to the receiver or source owner, not to wishful narration.”

If the target has Meraki or ACI data instead, select the matching source pack or
run the installed child validator in the final segment.

## 0:27–0:35 — Render, review, and apply one private dashboard

Use a query that is available on a normal Splunk target and does not depend on a
Cisco device:

```bash
bash skills/splunk-dashboard-studio-setup/scripts/setup.sh \
  --phase render \
  --output-dir "$DEMO_OUTPUT/dashboard" \
  --app-name search \
  --dashboard-name "$DEMO_DASHBOARD" \
  --title "Splunk Skills Demo - Platform Signals" \
  --search 'index=_internal | stats count by sourcetype | sort - count | head 20' \
  --viz-type splunk.table \
  --sharing user \
  --owner "$DEMO_SPLUNK_USER" \
  --json
```

Show both generated artifacts before any live write:

```bash
sed -n '1,220p' "$DEMO_OUTPUT/dashboard/dashboard-studio/dashboard.json"
sed -n '1,120p' "$DEMO_OUTPUT/dashboard/dashboard-studio/view.xml"
```

Read-only live preflight:

```bash
bash skills/splunk-dashboard-studio-setup/scripts/setup.sh \
  --phase preflight \
  --output-dir "$DEMO_OUTPUT/dashboard-preflight" \
  --app-name search \
  --dashboard-name "$DEMO_DASHBOARD" \
  --definition-file "$DEMO_OUTPUT/dashboard/dashboard-studio/dashboard.json" \
  --owner "$DEMO_SPLUNK_USER" \
  --sharing user \
  --read-roles '*' \
  --write-roles '' \
  --json
```

Pause for explicit audience approval before the single live mutation:

```bash
bash skills/splunk-dashboard-studio-setup/scripts/setup.sh \
  --phase apply \
  --output-dir "$DEMO_OUTPUT/dashboard-apply" \
  --app-name search \
  --dashboard-name "$DEMO_DASHBOARD" \
  --definition-file "$DEMO_OUTPUT/dashboard/dashboard-studio/dashboard.json" \
  --owner "$DEMO_SPLUNK_USER" \
  --sharing user \
  --read-roles '*' \
  --write-roles '' \
  --accept-overwrite \
  --json
```

Open the dashboard in Splunk Web while the audience can see that it is a real
view, not a screenshot. Keep it private to the presenter account.

## 0:35–0:41 — Validate exact live state

Use the dashboard skill's live status check; this reads the exact content and
ACL and fails on drift:

```bash
bash skills/splunk-dashboard-studio-setup/scripts/setup.sh \
  --phase status \
  --app-name search \
  --dashboard-name "$DEMO_DASHBOARD" \
  --definition-file "$DEMO_OUTPUT/dashboard/dashboard-studio/dashboard.json" \
  --owner "$DEMO_SPLUNK_USER" \
  --sharing user \
  --read-roles '*' \
  --write-roles '' \
  --json
```

Show the live search result in Splunk Web or through the official Splunk MCP
server if it is configured:

```spl
index=_internal
| stats count by sourcetype
| sort - count
| head 20
```

Narration:

“The proof is not that a POST returned 200. The proof is that the view, ACL,
search, and live result all agree.”

## 0:41–0:45 — Cisco completion branch and close

Choose the installed Cisco path from the inventory output. These validators are
read-only diagnostics; `--completion` makes missing evidence visible instead of
silently calling the setup successful.

```bash
# Cisco Meraki, if Splunk_TA_cisco_meraki is installed:
bash skills/cisco-meraki-ta-setup/scripts/validate.sh --completion

# Cisco DC Networking, if cisco_dc_networking_app_for_splunk is installed:
bash skills/cisco-dc-networking-setup/scripts/validate.sh --completion

# Cisco ASA, if the rendered ASA packet and TA are present:
bash skills/cisco-asa-ta-setup/scripts/validate.sh \
  --rendered-dir cisco-asa-ta-rendered \
  --live --completion
```

Close with:

“We did not confuse a package with a working integration. We resolved the
product, inspected the target, checked data evidence, created a governed live
consumer, and read it back exactly. Where Cisco evidence is missing, the repo
leaves an actionable handoff instead of claiming success.”

## Optional 5-minute ACI live branch

Use this only when the Cisco DC Networking app is already installed, the APIC is
reachable, and a device password file was prepared locally before the meeting.
Do not improvise this branch on a production stack.

```bash
ACI_ACCOUNT="ACI_DEMO"
ACI_HOST="replace-with-apic-hostname"
ACI_USER="replace-with-device-user"
ACI_PASSWORD_FILE="/tmp/aci_demo_password"

bash skills/cisco-dc-networking-setup/scripts/configure_account.sh \
  --type aci \
  --name "$ACI_ACCOUNT" \
  --hostname "$ACI_HOST" \
  --username "$ACI_USER" \
  --password-file "$ACI_PASSWORD_FILE" \
  --verify-ssl

bash skills/cisco-dc-networking-setup/scripts/setup.sh \
  --enable-inputs \
  --account "$ACI_ACCOUNT" \
  --index cisco_aci \
  --input-type aci

bash skills/cisco-dc-networking-setup/scripts/validate.sh --completion
```

The expected story is account creation, selected inputs, events in `cisco_aci`,
and the Cisco DC Networking dashboards returning data. Delete the temporary
device password file after the approved setup window.

## Failure branches to rehearse

| Symptom | Demo response |
|---|---|
| TLS verification or DNS fails | Stop live work; show `--plan-only` and render artifacts, then explain the profile/network fix |
| Cloud search API returns 403 | Explain the search API allowlist; do not weaken TLS or bypass ACS |
| Admin Doctor finds issues | Show the finding, its delegated skill, and the rendered fix plan; do not apply an unrelated fix live |
| No Cisco app installed | Keep Cisco routing as the plan-only story and use the `_internal` dashboard for the live consumer |
| No Cisco events | Show the readiness gap and TA completion gate; do not claim ingestion |
| Dashboard name already exists | Pick a new unique name; never overwrite an existing object during a timed demo |
| Apply/read-back fails | Stop, preserve the evidence directory, and show reconciliation guidance; do not retry blindly |

## What not to do in the live meeting

- Do not paste or read secrets aloud.
- Do not use `SPLUNK_VERIFY_SSL=false` as a demo shortcut.
- Do not install a package from a moving “latest” URL.
- Do not create a global dashboard or a broad ACL.
- Do not create an HEC token unless the token file, index, receiver, and cleanup
  plan are prepared and the audience explicitly approves it.
- Do not claim a Cisco TA is complete without event and dashboard/readiness
  evidence.
