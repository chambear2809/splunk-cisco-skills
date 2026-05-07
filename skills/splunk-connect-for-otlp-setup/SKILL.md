---
name: splunk-connect-for-otlp-setup
description: >-
  Install, administer, validate, diagnose, repair, and render sender handoffs for
  Splunk Connect for OTLP (`splunk-connect-for-otlp`, Splunkbase app 8704). Use
  when the user asks to deploy the OTLP modular input, expose OTLP gRPC/HTTP
  listeners, configure OTel SDK or Collector senders to Splunk Platform, verify
  HEC token/index routing, or troubleshoot Splunk Connect for OTLP.
---

# Splunk Connect for OTLP Setup

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
`10.3`.

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

1. Install or update the app through the shared installer:

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
  --listen-address 0.0.0.0
```

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

## Cloud And Topology

Use the hybrid-gated model:

- Splunk Cloud Victoria: direct modular-input configuration is allowed only
  after topology and inbound reachability checks prove OTLP senders can reach
  the listener.
- Splunk Cloud Classic: do not run the add-on on the Cloud search tier; use IDM
  when available or a customer-managed heavy forwarder.
- If senders are outside the Splunk Cloud network path, default to a
  customer-managed heavy forwarder with explicit firewall, load balancer, and
  TLS validation.

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

Render explicit `com.splunk.index` sender configuration and smoke-test routing
before claiming default-index behavior. The inspected `0.4.1` binary validates
token allowed indexes but does not pass the HEC token default index into the
exporter path.

Read `reference.md` for REST endpoints, repair IDs, package caveats, and sender
configuration details.
