---
name: splunk-connect-for-otlp-setup
description: "Use when the user asks to deploy the OTLP modular input, expose OTLP gRPC/HTTP listeners, configure OTel
  SDK or Collector senders to Splunk Platform, verify HEC token/index routing, or troubleshoot Splunk
  Connect for OTLP. Install, administer, validate, diagnose, repair, and render sender handoffs for Splunk
  Connect for OTLP (`splunk-connect-for-otlp`, Splunkbase app 8704)."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-07-02"
---

# Splunk Connect for OTLP Setup

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

- Deploy the OTLP modular input, expose OTLP gRPC/HTTP listeners, configure OTel SDK or Collector senders to Splunk
  Platform, verify HEC token/index routing, or troubleshoot Splunk Connect for OTLP.
- Preview and review the splunk connect for otlp setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-connect-for-otlp-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-connect-for-otlp-setup/scripts/validate.sh --help
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

## Shared add-on completion gate

Whenever this workflow installs, configures, or hands off a registry-listed
Splunk app or add-on, follow the
[shared completion gate](../shared/ta_completion_gate.md). Package delivery
alone is not success; capture applicable configuration, ingest/readiness, and
shipped-view evidence, or explicit package evidence that no dashboards ship.

Use this skill for the full lifecycle of Splunk Connect for OTLP, the Splunk
Platform modular input that accepts OTLP logs, metrics, and traces and emits
HEC-shaped events through Splunk modular-input stdout.

## Safety Rules

- Never ask for HEC token values in chat.
- Never pass token values as argv, URL query strings, or environment-variable
  prefixes.
- Token creation and updates are delegated to `splunk-hec-service-setup`.
- Use local token files for sender examples, for example:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/splunk_otlp_hec_token
```

## Known Package Facts

The audited release is Splunkbase app `8704`, package/app ID
`splunk-connect-for-otlp`, version `0.4.1`, compatible with Splunk `9.4` through
`10.5`.

That platform-version list is not Cloud install approval. The public release
API reports `cloud_compatible=false`, `install_method_single=rejected`, and
`install_method_distributed=rejected`. Do not install `8704` on a Victoria
search tier through ACS. Splunk Cloud 10.5 can be the data destination while
the receiver runs on a customer-managed heavy forwarder or an IDM placement
explicitly approved and coordinated by Splunk Support.

The inspected package contains only conf/UI metadata plus platform binaries:

- `default/app.conf`
- `default/inputs.conf`
- `default/props.conf`
- `default/data/ui/manager/splunk-connect-for-otlp.xml`
- `metadata/default.meta`
- `README/inputs.conf.spec`
- `linux_x86_64/bin/splunk-connect-for-otlp`
- `windows_x86_64/bin/splunk-connect-for-otlp`

There is no dashboard, setup page, KV Store collection, saved search, custom
REST handler, Python runtime, Darwin binary, or default `bin/` executable.

## Primary Workflow

1. On a customer-managed Splunk Enterprise search tier or heavy forwarder,
   install or update the app through the shared installer:

```bash
bash skills/splunk-connect-for-otlp-setup/scripts/setup.sh --install
```

2. Prepare or verify a HEC token with `splunk-hec-service-setup`; keep the token
   value in a local file.

3. Configure the modular input:

```bash
bash skills/splunk-connect-for-otlp-setup/scripts/setup.sh \
  --configure-input \
  --input-name otlp-main \
  --index otlp_events \
  --grpc-port 4317 \
  --http-port 4318 \
  --listen-address 0.0.0.0 \
  --enable-ssl true \
  --server-cert /opt/splunk/etc/auth/otlp/server.pem \
  --server-key /opt/splunk/etc/auth/otlp/server.key
```

Receiver and sender TLS default to enabled. A non-loopback plaintext listener
or sender is rejected unless the operator supplies
`--accept-insecure-plaintext-listener`; reserve that exception for an isolated,
short-lived lab.

4. Render sender assets:

```bash
bash skills/splunk-connect-for-otlp-setup/scripts/setup.sh \
  --render-sender-config \
  --receiver-host otlp-hf.example.com \
  --expected-index otlp_events \
  --hec-token-file /tmp/splunk_otlp_hec_token
```

5. Validate the deployment:

```bash
bash skills/splunk-connect-for-otlp-setup/scripts/validate.sh \
  --expected-index otlp_events \
  --input-name otlp-main
```

6. Diagnose and render conservative repair guidance:

```bash
bash skills/splunk-connect-for-otlp-setup/scripts/setup.sh --doctor
```

`--repair` returns nonzero when a requested fix can only render a HEC or sender
handoff. Run the rendered handoff, validate the resulting state, and rerun the
repair/validation workflow; a rendered packet is not reported as a completed
live repair.

## Cloud And Topology

Use the split-runtime model:

- Splunk Cloud Victoria and Classic: do not ACS-install app `8704` on the
  managed search tier. The listing rejects both Cloud install methods.
- Default to a customer-managed heavy forwarder with explicit firewall, load
  balancer, TLS, HEC allowed-index, and onward Splunk Cloud routing validation.
- An IDM placement is valid only after Splunk Support explicitly approves and
  coordinates it; do not model that as self-service ACS installation.
- The setup script refuses install, uninstall, input configuration, and repair
  mutations when the active credentials resolve to a managed Cloud profile.
  Read-only validation/doctor and sender/HEC handoff rendering remain safe.
- The skill remains conditional for Cloud 10.5 because Cloud is a supported
  destination for events emitted by the customer-managed/approved receiver.

## OTLP Sender Contract

- gRPC receiver endpoint: `host:4317`
- HTTP receiver endpoints:
  - `http(s)://host:4318/v1/logs`
  - `http(s)://host:4318/v1/metrics`
  - `http(s)://host:4318/v1/traces`
- Auth header: `Authorization: Splunk <HEC_TOKEN>`
- Attribute mapping:
  - `com.splunk.index` -> Splunk `index`
  - `com.splunk.sourcetype` -> Splunk `sourcetype`
  - `com.splunk.source` -> Splunk `source`
  - `host.name` -> Splunk `host`

The rendered telemetrygen helper intentionally exits nonzero because its OTLP
header option would expose the HEC token in process arguments. Use the rendered
Collector or SDK profile for an actionable, file-backed sender path.

Render explicit `com.splunk.index` sender configuration and smoke-test routing
before claiming default-index behavior. The inspected `0.4.1` binary validates
token allowed indexes but does not pass the HEC token default index into the
exporter path.

Read `reference.md` for REST endpoints, repair IDs, package caveats, and sender
configuration details.
