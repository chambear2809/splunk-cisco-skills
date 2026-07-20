# Splunk Secure Gateway Reference

## Research Basis

Based on current Splunk Secure Gateway documentation:

- Splunk Secure Gateway (`splunk_secure_gateway`) connects the Connected
  Experiences mobile apps to a Splunk platform instance by routing encrypted
  data through Spacebridge, hosted on Splunk's common cloud infrastructure.
- It requires outbound port 443 to `prod.spacebridge.spl.mobi` for a
  bidirectional WebSocket connection. No inbound ports are opened.
- Device registration exchanges an authentication code, public keys, and
  credentials through Spacebridge using Libsodium over TLS 1.2. Registration is
  done with an auth code or a QR code and is inherently interactive.
- Deployment settings are configured in Splunk Web (Administration > Deployment
  configuration > Advanced settings), including the deployment name, the apps
  whose dashboards appear in the mobile apps, mobile notifications, device
  management, and Spacebridge location/region.
- MDM distribution uses an Instance ID File generated in Secure Gateway and
  added as a custom app configuration in the MDM provider. Multiple instances
  can be concatenated into one file.
- Private Spacebridge (Splunk platform 9.0+ with Secure Gateway 3.0+) is
  configured through the onboarding workflow or deployment settings; the
  Instance ID File uses an `endpoint_config` clause with `custom_endpoint_id`,
  `custom_endpoint_hostname`, `custom_endpoint_grpc_hostname`, and
  `client_cert_required`.

## Apply Transport

App enable/disable uses the Splunk REST `apps/local/<app>` endpoint
(`disabled=0|1`) via the shared session-key helpers only for Splunk Enterprise.
There is no public REST API for Spacebridge device registration or for most
deployment settings, so this skill validates egress and renders the Splunk Web /
MDM runbooks. Enabling the app opens outbound Spacebridge connectivity and is
gated behind `--accept-spacebridge-egress`.

## Splunk Cloud Managed Boundary

Splunk Cloud manages Secure Gateway app state and Spacebridge configuration.
`scripts/setup.sh` accepts `--platform auto|cloud|enterprise` and defaults to
`auto`. The configured target is resolved through platform settings before
rendering; this classification does not authenticate. A Cloud preflight,
status, apply, all, or render-with-apply request is refused before artifacts,
probes, session authentication, or live requests and exits `2`. Plain render is
allowed and emits review-only skeletons/runbooks plus an egress script that
itself exits `2` with the managed-service handoff.

For Splunk Cloud Platform 10.5.2605, render the managed-service readiness bundle
with:

```bash
bash skills/splunk-secure-gateway-setup/scripts/setup.sh \
  --platform cloud --phase render
```

Run egress validation from an Enterprise search head only. On Splunk Cloud,
connectivity originates from Splunk-managed infrastructure and must be handled
through the Cloud readiness/support workflow.

## Validation

Static validation confirms the rendered assets exist. The `--live` validation
runs the egress preflight to confirm the Spacebridge host is reachable on 443.
