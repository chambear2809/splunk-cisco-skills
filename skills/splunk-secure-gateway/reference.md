# Splunk Secure Gateway / Mobile Reference

Splunk Secure Gateway (`splunk_secure_gateway`) is the required platform app that
connects Splunk Connected Experiences apps — Splunk Mobile, Splunk TV, and
Splunk AR — to a Splunk Enterprise or Splunk Cloud instance. It routes encrypted
traffic through **Spacebridge**, a Splunk-hosted relay, so there are no inbound
firewall rules, port mappings, or domain registrations to manage.

## Connectivity Requirements

- **Outbound 443 only** to `prod.spacebridge.spl.mobi` (WebSocket). No inbound
  ports are opened.
- HTTPS health check: `https://prod.spacebridge.spl.mobi/health_check`.
- Regional health-check endpoints (when using a regional Spacebridge):
  `https://http.<region>.spacebridge.splunkcx.com/health_check`, for regions
  such as `us-east-1`, `eu-central-1`, `eu-west-1`, `eu-west-2`, and
  `ap-southeast-2`.
- WebSocket upgrade test (from the search head):

  ```
  curl -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" \
    -H "Host: prod.spacebridge.spl.mobi" \
    -H "Origin: https://prod.spacebridge.spl.mobi" \
    https://prod.spacebridge.spl.mobi/mobile
  ```

- If a proxy performs SSL decryption, it must support WebSockets or exempt
  `prod.spacebridge.spl.mobi`. Use a true passthrough proxy.

The rendered `connectivity-preflight.sh` runs the health checks and the
WebSocket test. Run it before enabling or registering.

## App Enablement And Token Auth

- On **Splunk Enterprise**, `splunk_secure_gateway` ships with the platform;
  enable it if disabled (`splunk enable app splunk_secure_gateway` or Settings >
  Apps). On **Splunk Cloud**, Secure Gateway is managed by Splunk.
- **Token (JWT) authentication must be enabled** (Settings > Tokens) for the
  Connected Experiences apps and registration to work. If a user's Splunk
  credentials change, their device is unregistered and must re-register.

The rendered `enable.sh` enables the app (Enterprise) and reads the token-auth
state so you can confirm readiness. It does not mint tokens.

## Device Registration

Two registration paths:

1. **In-app registration** — the Connected Experiences app shows an
   authentication code (or scannable QR); the user enters/scans it via
   **Apps > Splunk Secure Gateway > Register a device** in Splunk Web. All
   registration data passes through Spacebridge, encrypted with Libsodium over
   TLS 1.2.
2. **MDM** — push a Managed App Configuration to devices via your MDM (Intune,
   Jamf, Workspace ONE, etc.). You can also restrict login to MDM-configured
   devices only.

`register.sh` prints the in-app steps and prerequisites. `mdm-appconfig.xml` is a
**template**: confirm the exact AppConfig keys for your Splunk Mobile version
against the Splunk "Set up MDM and in-app registration" documentation before
deploying, since key names can change between releases.

## Security Model

- Spacebridge identifies client devices and encrypts data in transit and at rest.
- During registration the device and the app exchange an authentication code,
  public keys, and encrypted credentials, all relayed through Spacebridge.
- No ingress firewall rules or device login details are exposed to the Splunk
  instance.

## Troubleshooting

- Use the Secure Gateway troubleshooting dashboards (Value Test, End-to-End
  WebSocket Test) — the WebSocket test requires JWT enabled.
- Connection failures usually mean blocked outbound 443, a proxy that breaks
  WebSockets, or disabled token auth.
- Search the Secure Gateway logs (`index=_internal sourcetype=splunkd
  component=*SecureGateway*` and the app's own logs) when registration fails.

## Out Of Scope And Handoffs

- Mobile-delivered alerts and dashboards content authoring: build dashboards with
  `splunk-dashboard-studio`; build saved searches/alerts with
  `splunk-knowledge-objects`.
- Roles/capabilities for mobile users: `splunk-cloud-acs-admin-setup` (Cloud) or
  the platform role tooling.
- TLS/PKI for splunkd: `splunk-platform-pki-setup`.
- This skill is platform mobile access, not Splunk Observability Cloud Mobile
  (see `splunk-observability-deep-native-workflows`) or AppDynamics EUM.
