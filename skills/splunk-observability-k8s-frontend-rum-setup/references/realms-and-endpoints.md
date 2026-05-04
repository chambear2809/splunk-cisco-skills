# Realms and Endpoints

## Supported realms

The Splunk Browser RUM agent (and Session Replay) supports the following
Splunk Observability Cloud realms:

| Region | Realms |
|--------|--------|
| United States | `us0`, `us1`, `us2` |
| Europe | `eu0`, `eu1`, `eu2` |
| Asia-Pacific | `au0`, `jp0` |

The renderer enforces this list. A spec with a realm outside the set fails
preflight with `realm-supported: FAIL`.

To find the realm for your organization, sign in to Splunk Observability
Cloud, open the navigation menu, select Settings, then your username; the
realm appears in the Organizations section.

## FedRAMP / GovCloud

Splunk Browser RUM is **not currently supported** on FedRAMP-Moderate or
FedRAMP-High organizations. The CDN host (`cdn.observability.splunkcloud.com`
or legacy `cdn.signalfx.com`) is not accessible from FedRAMP networks, and
the corresponding RUM ingest endpoint is not provisioned. If your
organization is FedRAMP, this skill does not apply — file a support ticket
to request the feature for your tier.

## Endpoint domain transition

As of March 24, 2026, both legacy and new API/service endpoint URLs work in
parallel. The renderer defaults to the new domain.

| Endpoint type | Default (new) | Legacy |
|---------------|---------------|--------|
| Agent CDN | `https://cdn.observability.splunkcloud.com/o11y-gdi-rum/<version>/splunk-otel-web.js` | `https://cdn.signalfx.com/o11y-gdi-rum/<version>/splunk-otel-web.js` |
| Session Recorder CDN | `https://cdn.observability.splunkcloud.com/o11y-gdi-rum/<version>/splunk-otel-web-session-recorder.js` | `https://cdn.signalfx.com/o11y-gdi-rum/<version>/splunk-otel-web-session-recorder.js` |
| RUM beacon ingest | `https://rum-ingest.<realm>.observability.splunkcloud.com/v1/rum` | `https://rum-ingest.<realm>.signalfx.com/v1/rum` |

To opt into the legacy `signalfx` domain (only relevant for organizations
that haven't completed the migration on their own infra):

```yaml
endpoints:
  domain: signalfx
```

The renderer emits a deprecation WARN whenever `domain: signalfx` is chosen.

## Self-hosted CDN

For air-gapped clusters or strict CSP environments, you can host
`splunk-otel-web.js` and `splunk-otel-web-session-recorder.js` on your own
CDN. Set:

```yaml
endpoints:
  cdn_base: "https://cdn.example.com/splunk-rum"
```

The renderer emits `<script src="https://cdn.example.com/splunk-rum/o11y-gdi-rum/<version>/splunk-otel-web.js">`
with the same path layout the Splunk CDN uses (so you can mirror the GitHub
release files 1:1).

When using a self-hosted CDN:

1. Download the release tarball from
   `https://github.com/signalfx/splunk-otel-js-web/releases`.
2. Unpack into your CDN at the path layout `o11y-gdi-rum/<version>/`.
3. Update your CSP `script-src` to your CDN host instead of the Splunk one.

## Beacon endpoint override

The agent computes the beacon endpoint from `realm` + `domain` automatically.
Override it only when you have a corporate proxy or some other unusual
network setup:

```yaml
endpoints:
  beacon_endpoint_override: "https://corp-proxy.example.com/rum"
```

When set, the rendered `SplunkRum.init({ beaconEndpoint: ... })` uses that
URL instead of the auto-derived one. The agent stops using the realm for URL
construction in this mode (but the realm still flows into the rendered
`SplunkRum.init({ realm })` for tagging purposes).

## Agent version pinning policy

| Pin shape | Behavior | Recommended for |
|-----------|----------|-----------------|
| `v1` | Latest 1.x release. Auto-updates on patch + minor; never auto-updates major. | Production default. |
| `v2` | Latest 2.x release. | After you've validated 2.x in pre-prod. |
| `v2.5` | Latest 2.5.x release. Auto-updates on patch only. | Conservative production. |
| `v2.5.0` | Pinned to exact 2.5.0. SRI hash is meaningful. | Air-gapped / regulated. |
| `latest` | Latest release across all majors. Can break on major bumps. | **Pre-prod only.** Renderer rejects unless `--allow-latest-version`. |

The renderer's preflight enforces:

- `latest` requires `--allow-latest-version`. Otherwise FAIL.
- Exact-version pins (`vX.Y.Z`) emit a WARN if no SRI hash was supplied. The
  hash comes from the GitHub release page (each release lists the
  `sha384-...` integrity values). The renderer cannot fetch them.

## SRI hashes

Subresource Integrity (SRI) protects your users when the CDN is compromised
or returns a different file than expected. The browser refuses to execute the
script if the fetched bytes don't hash to the expected value.

Render with operator-supplied SRI hashes:

```bash
bash skills/splunk-observability-k8s-frontend-rum-setup/scripts/setup.sh \
    --render \
    --agent-version v2.5.0 \
    --agent-sri "sha384-..." \
    --session-recorder-sri "sha384-..."   # only when Session Replay is enabled
```

The rendered `<script>` tag includes the integrity attribute:

```html
<script src="https://cdn.observability.splunkcloud.com/o11y-gdi-rum/v2.5.0/splunk-otel-web.js"
        integrity="sha384-..."
        crossorigin="anonymous"></script>
```

For non-exact pins (`v1`, `v2`, `v2.5`), SRI is not meaningful — the resolved
file changes over time, so a hash would always fail validation. The renderer
silently drops the integrity attribute for non-exact pins.

## IE11 legacy build

For organizations that still need to support IE11 (rare in 2026), the agent
publishes a separate legacy build:

```yaml
legacy_ie11_build: true
```

The renderer emits a second `<script>` tag wrapped in IE-conditional comments:

```html
<!--[if IE]><script src="https://cdn.observability.splunkcloud.com/o11y-gdi-rum/v1/splunk-otel-web-legacy.js" crossorigin="anonymous"></script><![endif]-->
```

Modern browsers ignore the conditional comment; IE11 fetches the legacy build
in addition to (or instead of) the modern one. The legacy build supports a
narrower instrumentation set (no Web Vitals, no SocketIO, no thrashed-cursor
detection).
