# Beginner ITSI Quickstart

Use this guide when the operator knows the service or product they care about, but
does not know ITSI object schemas yet.

## Plain-Language Goal

Help the user get from "I need ITSI for this environment" to one of these safe,
previewable outcomes:

- Install or validate a supported ITSI content pack.
- Build a small service tree with clear parent and child services.
- Add a few KPIs that use known SPL searches, indexes, or macros.
- Validate the result and produce a handoff report.

Keep the first pass intentionally small. A useful ITSI starter is usually one
business service, two or three supporting services, and one or two KPIs per
service. Expand after preview and validation are clean.

## Minimum Intake

Ask for missing non-secret values only:

- Splunk platform: `enterprise` or `cloud`.
- Splunk management URL, such as `https://splunk.example.com:8089`.
- Whether ITSI and the Splunk App for Content Packs are already installed.
- Business service name, such as `Branch Network`, `Payments`, or `Campus WiFi`.
- Supported product domains already sending data: AWS, Cisco Data Center, Cisco Enterprise Networks, Cisco ThousandEyes, Linux, AppDynamics, Splunk Observability Cloud, VMware, or Windows.
- Indexes, sourcetypes, or macro values for the relevant data.
- Service dependencies in plain order, such as `Branch Network depends on WAN Edge and Secure Access`.
- KPI signals the user understands, such as availability, error count, latency, packet loss, CPU, memory, or interface errors.

Never ask for passwords, API keys, tokens, client secrets, or Splunkbase
credentials in chat. If credentials are missing, use the repository credential
setup workflow described in the root `AGENTS.md`.

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

Start from:

```bash
bash scripts/setup.sh --workflow content-packs --spec templates/beginner.content-pack.yaml
```

Then apply only after the preview looks right:

```bash
bash scripts/setup.sh --workflow content-packs --spec templates/beginner.content-pack.yaml --apply
bash scripts/validate.sh --workflow content-packs --spec templates/beginner.content-pack.yaml
```

For Splunk Cloud, preview and validate can identify missing apps, but installing
the Splunk App for Content Packs may require a Splunk Support or Cloud App
Request.

## Fast Path: Service Tree

Start from:

```bash
bash scripts/setup.sh --workflow topology --spec templates/beginner.topology.yaml
```

Then apply only after the preview looks right:

```bash
bash scripts/setup.sh --workflow topology --spec templates/beginner.topology.yaml --apply
bash scripts/validate.sh --workflow topology --spec templates/beginner.topology.yaml
```

Keep services disabled in the first pass unless the user explicitly wants ITSI
health scoring and alerting enabled immediately.

## Beginner Spec Checklist

Before preview, confirm:

- `connection.base_url` points at the Splunk management API, usually port `8089`,
  or it is blank and `SPLUNK_SEARCH_API_URI` is set in the credential file.
- `connection.platform` is set to `enterprise` or `cloud`.
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
- Ready to create/update: <services, KPIs, dependencies, packs>
- Needs attention before apply: <missing apps, indexes, macros, searches>
- Will stay manual: <content-pack module steps or dashboard tuning>
- Recommended next command: <apply or validate command>
```

## Success Criteria

A beginner setup is ready to hand off when:

- Preview has no unexpected destructive actions.
- Apply finishes without prerequisite errors.
- Validate passes or returns only known manual follow-up items.
- The generated report identifies installed packs, created services, dependency
  edges, and remaining module or dashboard steps.
