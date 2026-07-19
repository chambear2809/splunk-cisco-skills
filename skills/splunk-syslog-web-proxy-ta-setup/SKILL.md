---
name: splunk-syslog-web-proxy-ta-setup
description: "Use when the user asks to onboard, configure, render, or validate these web, proxy, DNS/DHCP, ADC, or
  appliance logs in Splunk. Shared render, install, and validation workflow for Splunk Supported Add-on
  parser and web/proxy profiles: Apache, NGINX, IIS, Tomcat, HAProxy, Squid, Blue Coat ProxySG, Forcepoint
  Web Security, Check Point Log Exporter, F5 BIG-IP, Citrix NetScaler, and Infoblox. Renders product-
  specific local file/UF, Windows UF, or SC4S/syslog transport handoffs with package-backed source types."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-07-02"
---

# Syslog, Web, And Proxy Supported Add-on Setup

## Prerequisites

| Tool or access | Purpose | Verify |
|---|---|---|
| Bash and Python 3 | Run bundled setup and validation helpers | `bash --version && python3 --version` |
| Required product/platform access | Inspect or configure the selected target | Complete the documented preflight |
| Credential files for live modes | Keep secrets out of chat | Verify paths only |

## Workflow Overview

```text
┌───────────┐   ┌───────────────┐   ┌───────────────┐   ┌─────────────────┐
│ Preflight │ → │ Render/review │ → │ Apply/handoff │ → │ Validate evidence │
└───────────┘   └───────────────┘   └───────────────┘   └─────────────────┘
```

## When to Activate

- Onboard, configure, render, or validate these web, proxy, DNS/DHCP, ADC, or appliance logs in Splunk.
- Preview and review the splunk syslog web proxy ta setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-syslog-web-proxy-ta-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-syslog-web-proxy-ta-setup/scripts/validate.sh --help
```

Expected output: offline, live, and completion options are displayed when the
skill supports them; help exits without mutation.

## Troubleshooting

| Issue | Cause | Resolution |
|---|---|---|
| Preflight fails | A required tool or access path is missing | Resolve it before rendering or applying |
| Rendered assets are incomplete | Required non-secret inputs are absent | Complete intake and render again |
| Apply is blocked | Review, credentials, or explicit acceptance is missing | Use the documented handoff |
| Validation is incomplete | Live evidence is unavailable | Record the gap and keep completion open |

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

Shared render-first workflow for parser and web/proxy add-ons where the primary
work is transport ownership and exact package source-type stamping. Web-server
profiles default to local file/Universal Forwarder monitors, IIS defaults to a
Windows UF handoff, and network/proxy/security appliances default to SC4S or
syslog handoff.

Tomcat is a compatibility exception for the repository's current Splunk Cloud
`10.5` target: as of July 2, 2026, Splunkbase app `2911` advertises versions
only through `10.4`. When `tomcat` is selected for a `10.5` Cloud stack, record
the warning and keep the workflow render-only. The shared installer refuses
app `2911` on a `10.5` target before mutation. Use
`--accept-unsupported-platform` only when vendor approval and the operator's
exception record explicitly cover that package and target.

## Workflow

```bash
bash skills/splunk-syslog-web-proxy-ta-setup/scripts/setup.sh --render \
  --products apache,nginx,iis,tomcat,haproxy,bluecoat --index web --syslog-index netproxy
```

Review `inputs.local.conf.template` for host-local file monitors and
`transport-handoff.md` for appliance/syslog profiles.

To install the selected packages through the shared installer after rendering:

```bash
bash skills/splunk-syslog-web-proxy-ta-setup/scripts/setup.sh --install \
  --products apache,nginx,iis,tomcat,haproxy,bluecoat
```

```bash
bash skills/splunk-syslog-web-proxy-ta-setup/scripts/validate.sh --index web --syslog-index netproxy
```
