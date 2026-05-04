# CSP + HTTPS Requirements

## HTTPS is mandatory

The Splunk Browser RUM agent works only on pages served over HTTPS. Mixed
content (HTTPS page loading HTTP scripts) is blocked by every modern browser
before the agent can even initialize. The renderer enforces HTTPS in two
places:

1. The rendered `<script src=>` tags always use `https://`. There is no flag
   to override this.
2. The static validation pass (`validate.sh`) refuses to pass a rendered
   manifest where any `<script src=>` URL starts with `http://`.

If your frontend is served over HTTP, fix that first. The RUM agent will not
work, and the validation will not pass.

## Content Security Policy (CSP)

If your frontend uses a CSP header (and it should), four directives need
adjustment for Splunk RUM to work:

| Directive | Default endpoint domain | Legacy endpoint domain |
|-----------|------------------------|------------------------|
| `script-src` | `cdn.observability.splunkcloud.com` | `cdn.signalfx.com` |
| `connect-src` | `rum-ingest.<realm>.observability.splunkcloud.com` | `rum-ingest.<realm>.signalfx.com` |
| `worker-src` | `'self'` (only when Session Replay `backgroundServiceSrc` is set) | same |
| `style-src` | (your existing rules; RUM doesn't add styles) | n/a |

`<realm>` is your Splunk Observability realm (`us0`, `us1`, `us2`, `eu0`,
`eu1`, `eu2`, `au0`, `jp0`).

### Example CSP header (default endpoint domain)

```
Content-Security-Policy:
  default-src 'self';
  script-src 'self' cdn.observability.splunkcloud.com;
  connect-src 'self' rum-ingest.us1.observability.splunkcloud.com;
  worker-src 'self';
  style-src 'self' 'unsafe-inline';
  img-src 'self' data:;
  base-uri 'self';
  form-action 'self';
  frame-ancestors 'none';
  upgrade-insecure-requests;
```

### Example CSP header (legacy endpoint domain — only when explicitly chosen)

```
Content-Security-Policy:
  ...
  script-src 'self' cdn.signalfx.com;
  connect-src 'self' rum-ingest.us1.signalfx.com;
```

### Self-hosted CDN

When the agent is hosted on your own CDN (`endpoints.cdn_base` set in the spec),
the `script-src` allowlist entry is your CDN host instead of the Splunk one:

```
script-src 'self' cdn.example.com;
```

## CSP for Session Replay

When Session Replay is enabled with `features.background_service_src`, add the
hosting page to `worker-src`:

```
worker-src 'self' https://background-service.example.com;
```

If the background service host differs from your origin, you may also need
`frame-src` (some browsers route Web Worker hosts through the iframe
allowlist when sandboxed):

```
frame-src 'self' https://background-service.example.com;
```

## Inline script execution

The rendered RUM snippet contains an inline `<script>...</script>` block that
calls `SplunkRum.init(...)`. Strict CSPs that disallow `'unsafe-inline'` for
`script-src` will block this script. Three workarounds:

1. **Add a nonce**: edit your CSP middleware to emit a nonce per request and
   wire it into the rendered snippet:
   ```
   script-src 'self' 'nonce-<random>' cdn.observability.splunkcloud.com;
   ```
   Then inject `nonce="<random>"` into the `<script>` tag in the snippet.
   This skill does not auto-generate nonces (CSP nonces are per-request, not
   per-render); the operator must wire it through their middleware.

2. **Use the npm bundle path (mode B)**: with mode B the init call lives in
   your bundled JS, not in an inline script tag, so a no-`'unsafe-inline'`
   CSP works without nonce setup.

3. **Add `'unsafe-inline'` for `script-src`**: works but loses XSS protection.
   Not recommended.

## Ad-blockers

The Splunk RUM agent loads from `cdn.observability.splunkcloud.com`. Some
ad-blocker rule lists block hosts under `cdn.observability.splunkcloud.com`.
When the script fails to load, `window.SplunkRum` is undefined.

The skill's manual-instrumentation snippets all use `if (window.SplunkRum)`
guards so blocked agents don't break your application code. The trade-off is
that telemetry from ad-blocker users is missing — there is no fix on the
Splunk side for that.

## CSP advisory in the rendered preflight

The renderer always includes a CSP advisory in `preflight-report.md`:

```
INFO  csp-advisory  Add to your existing CSP:
                    script-src cdn.observability.splunkcloud.com;
                    connect-src rum-ingest.us1.observability.splunkcloud.com.
```

Operators should treat this as a checklist item before pushing to production.
The skill does NOT modify ingress headers automatically — too risky.

## Live CSP probe

```bash
bash splunk-observability-k8s-frontend-rum-rendered/scripts/validate.sh \
  --live --check-csp https://your-frontend.example.com
```

`--check-csp` does an HTTP HEAD against the URL, parses the
`Content-Security-Policy` header, and verifies both:

- The `script-src` directive includes the CDN host.
- The `connect-src` directive includes the `rum-ingest.<realm>` host.

When either is missing, the probe FAILs with a clear error. When the page
emits no CSP at all, the probe WARNs (no CSP is permissive but unusual in
production; you probably want at least a basic CSP).
