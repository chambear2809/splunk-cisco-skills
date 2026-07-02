# Beginner ITSI Quickstart

Use this guide when the operator knows the service or product they care about, but
does not know ITSI object schemas yet.

## Plain-Language Goal

Help the user get from "I need ITSI for this environment" to one of these safe,
previewable outcomes:

- Import or validate a supported ITSI content pack that is already available in
  an existing ITSI Content Library.
- Build a small service tree with clear parent and child services.
- Add a few KPIs that use known SPL searches, indexes, or macros.
- Validate the result and produce a handoff report.

Keep the first pass intentionally small. A useful ITSI starter is usually one
business service, two or three supporting services, and one or two KPIs per
service. Expand after preview and validation are clean.

## Minimum Intake

Ask for missing non-secret values only:

- Splunk platform: `enterprise`, `cloud`, or `auto` when the credential file URL should decide.
- Splunk management URL, such as `https://splunk.example.com:8089`.
- Confirmation that ITSI is already installed, licensed, and healthy. Detect
  this from the target when possible.
- For content packs, confirmation that the version-compatible Content Library
  API/provider and the pack's prerequisite apps are already available. On ITSI
  4.21 this normally means a compatible Splunk App for Content Packs. Missing
  apps are handoffs, not automatic work in this skill.
- Business service name, such as `Branch Network`, `Payments`, or `Campus WiFi`.
- Supported product domains already sending data: AWS, Cisco Data Center, Cisco Enterprise Networks, Cisco ThousandEyes, Linux, AppDynamics, Splunk Observability Cloud, VMware, or Windows.
- Indexes, sourcetypes, or macro values for the relevant data.
- Service dependencies in plain order, such as `Branch Network depends on WAN Edge and Secure Access`.
- KPI signals the user understands, such as availability, error count, latency, packet loss, CPU, memory, or interface errors.

Never ask for passwords, API keys, tokens, client secrets, or Splunkbase
credentials in chat. If credentials are missing, use the repository credential
setup workflow described in the root `AGENTS.md`.

If ITSI itself is absent or unhealthy, stop and hand off to
`splunk-itsi-setup`. Do not continue to apply and do not enable legacy
`install_if_missing` fields.

## Workflow Picker

Use `content-packs` when:

- The user's source product matches a supported profile.
- They want Splunk's packaged dashboards, services, entity discovery, or saved
  searches.
- They can provide the relevant indexes or macro values.

Use `topology` when:

- The user can describe services and dependencies in plain language.
- They need a service tree quickly.
- They have SPL searches or can identify indexes and sourcetypes for KPIs.
- They are not importing exported ITSI JSON payloads.

Use `native` when:

- The user already has ITSI exports or exact payloads.
- They need advanced ITSI objects such as custom NEAPs, glass tables,
  maintenance windows, backup jobs, deep dives, or home views.
- The task is specific object drift management rather than a first ITSI setup.

## Fast Path: Content Pack

Copy the starter to the gitignored local intake file:

```bash
cp skills/splunk-itsi-config/templates/beginner.content-pack.yaml \
  skills/splunk-itsi-config/template.local
```

Replace the example pack/index values. Leave `metadata.template: true` while
editing; set it to `false` only after the preview is reviewed and immediately
before an approved apply.

Lint it without credentials or network access, then run the GET-only preview:

```bash
bash skills/splunk-itsi-config/scripts/setup.sh \
  --workflow content-packs \
  --spec skills/splunk-itsi-config/template.local \
  --mode lint

bash skills/splunk-itsi-config/scripts/setup.sh \
  --workflow content-packs \
  --spec skills/splunk-itsi-config/template.local
```

After explicit approval of the target and preview, apply and validate:

```bash
bash skills/splunk-itsi-config/scripts/setup.sh \
  --workflow content-packs \
  --spec skills/splunk-itsi-config/template.local \
  --apply

bash skills/splunk-itsi-config/scripts/validate.sh \
  --workflow content-packs \
  --spec skills/splunk-itsi-config/template.local \
  --completion
```

For Splunk Cloud, missing prerequisite apps may require a Splunk Support or
Cloud App Request. This skill reports that handoff and makes no package change.
Catalog refresh is also a write: leave it off for preview and validation, and
set `content_library.refresh_catalog: true` only for a separately approved
apply when a refresh is actually required.

## Fast Path: Service Tree

Copy the starter, replace all sample service names/searches/indexes, and lint:

```bash
cp skills/splunk-itsi-config/templates/beginner.topology.yaml \
  skills/splunk-itsi-config/template.local

bash skills/splunk-itsi-config/scripts/setup.sh \
  --workflow topology \
  --spec skills/splunk-itsi-config/template.local \
  --mode lint
```

The apply gate rejects a copied starter while `metadata.template: true` or a
known placeholder remains. Set the marker to `false` only after completing and
reviewing the local spec.

Run the GET-only preview, then apply only after the target and changes are
explicitly approved:

```bash
bash skills/splunk-itsi-config/scripts/setup.sh \
  --workflow topology \
  --spec skills/splunk-itsi-config/template.local

bash skills/splunk-itsi-config/scripts/setup.sh \
  --workflow topology \
  --spec skills/splunk-itsi-config/template.local \
  --apply

bash skills/splunk-itsi-config/scripts/validate.sh \
  --workflow topology \
  --spec skills/splunk-itsi-config/template.local \
  --completion
```

Keep services disabled in the first pass unless the user explicitly wants ITSI
health scoring and alerting enabled immediately.

## Beginner Spec Checklist

Before preview, confirm:

- Bash, Python 3, and Ruby are available; the wrapper uses Ruby's standard YAML
  parser before the Python offline validator.
- Offline lint passes; before apply, the stricter lint gate also confirms
  `metadata.template: false` and no starter placeholder remains.
- `connection.base_url` points at the Splunk management API, usually port `8089`,
  or it is blank and `SPLUNK_SEARCH_API_URI` is set in the credential file.
- `connection.platform` is set to `auto`, `enterprise`, or `cloud`.
- ITSI is already installed, licensed, enabled, and healthy; content-pack
  prerequisites are already installed when that workflow is selected.
- TLS verification is enabled, or a readable private CA bundle is configured.
  A lab-only `verify_ssl: false` target is rejected unless
  `connection.allow_insecure_tls: true` (or
  `SPLUNK_ALLOW_INSECURE_TLS=true`) explicitly acknowledges that risk; it can
  never satisfy production completion.
- The authenticated user has the required ITSI object capability and write
  access to the target team (and Global-team access for Global objects).
- New services have clear names and descriptions.
- Each KPI has a search that returns the `threshold_field`.
- Dependency edges point from the parent service to the service it depends on.
- Content-pack profiles include required indexes, metrics indexes, summary
  indexes, or macro values where the profile requires them.
- The spec does not contain secrets.

## Common Translations

| User phrase | ITSI object to create |
| --- | --- |
| "Show me health for this app" | A service with KPIs |
| "This app depends on database and network" | A service tree with dependencies |
| "Use VMware/Windows/Linux/AWS defaults" | A content-pack profile |
| "Track packet loss or latency" | A KPI search with thresholds |
| "Group these hosts" | Entity rules or entities |
| "Suppress alerts during maintenance" | A maintenance window |
| "Notify when episodes match this pattern" | A custom NEAP |

## Preview Summary Template

When summarizing preview output for a beginner, use this shape:

```text
Preview result:
- Target and detected versions: <stack/host, Splunk, ITSI, Content Library>
- Ready to create/update: <services, KPIs, dependencies, packs>
- Needs attention before apply: <missing apps, indexes, macros, searches>
- Will stay manual: <content-pack module steps without a safe configured_outcome>
- Recommended next command: <apply or validate command>
```

## Success Criteria

A beginner setup is ready to hand off when:

- Lint passed and preview made no writes.
- Preview has no unexpected destructive actions.
- Apply finishes without prerequisite errors.
- Completion validation passes, including bounded data/search checks where
  available, or returns only explicitly owned manual follow-up items.
- The generated report identifies installed packs, created services, dependency
  edges, configured outcomes, target/version evidence, and remaining module
  steps.
