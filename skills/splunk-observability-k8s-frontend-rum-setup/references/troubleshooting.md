# Troubleshooting

## RUM data not appearing in the UI

### 1. Verify the snippet is in the served HTML

```bash
curl -fsSL https://your-frontend.example.com | grep -c 'SplunkRum.init('
```

Expected: 1 (or higher if multiple injections collided). Zero means the
sub_filter / initContainer / runtime-config did not run.

For mode A.i (nginx-configmap):
- Confirm the ConfigMap was applied: `kubectl get configmap splunk-rum-nginx-<workload> -n <namespace>`.
- Confirm the deployment has the volume mount: `kubectl get deployment <name> -n <namespace> -o yaml | grep -A5 splunk-rum-nginx-conf`.
- Tail nginx logs: `kubectl logs deploy/<name> -n <namespace> -c <nginx-container>` — sub_filter parse errors show up here.
- Confirm sub_filter is not bypassed by gzip (see "sub_filter does nothing" below).

For mode A.ii (ingress-snippet):
- Confirm the controller's ConfigMap allows snippets: `kubectl -n ingress-nginx get configmap ingress-nginx-controller -o yaml | grep allow-snippet`.
- Confirm the annotation landed on the Ingress: `kubectl get ingress <name> -o yaml | grep configuration-snippet`.
- Tail the ingress-nginx controller logs: `kubectl -n ingress-nginx logs deploy/ingress-nginx-controller`.

For mode C (init-container):
- Confirm the initContainer ran: `kubectl describe pod <name> -n <namespace> | grep -A5 splunk-rum-rewriter`.
- Read the rewriter logs: `kubectl logs <pod> -c splunk-rum-rewriter -n <namespace>`.

For mode B (runtime-config):
- Confirm the bootstrap snippet is in the served `index.html`.
- Confirm `/rum-config.js` resolves: `curl -fsSI https://your-frontend.example.com/rum-config.js`.
- Confirm `window.SPLUNK_RUM_CONFIG` is set in the browser console after page load.

### 2. Verify the agent loaded

In the browser DevTools console:

```javascript
window.SplunkRum && SplunkRum.getSessionId()
```

Expected: a 32-character hex session ID. If `SplunkRum` is undefined:
- An ad-blocker likely blocked the CDN script. Try in an incognito window
  with extensions disabled.
- The CSP `script-src` does not allow the CDN host (see [csp-and-https.md](csp-and-https.md)).
- The page is not HTTPS — the agent only runs on HTTPS pages.
- The CDN URL returned 404 — check your `agent_version` pin.

### 3. Verify beacons are being sent

Open DevTools Network tab, filter by `rum-ingest`. You should see POSTs to
`rum-ingest.<realm>.observability.splunkcloud.com/v1/rum` (or `/v1/rumotlp` if
you set `exporter.otlp: true`).

If beacons are blocked:
- CSP `connect-src` does not allow the beacon host (see [csp-and-https.md](csp-and-https.md)).
- A corporate proxy intercepts and drops outbound TLS to splunkcloud.com.
- DNS does not resolve `rum-ingest.<realm>.observability.splunkcloud.com` from
  the user's network.

### 4. Verify in the Splunk RUM UI

- Open Splunk Observability Cloud > RUM > Browser.
- Filter by your `applicationName` (the value passed to `SplunkRum.init`).
- New sessions take ~1–2 minutes to appear. If still empty after 10 minutes
  AND beacons are visible in DevTools AND status code is 200, file a support
  ticket.

## sub_filter does nothing (mode A.i)

### Symptom

`curl` confirms the served HTML contains `</head>` but no `SplunkRum.init`
above it. nginx logs are clean. ConfigMap and volume mount are correct.

### Cause and fix

`sub_filter` only operates on plain-text response bodies. It is bypassed
when:

1. **Upstream gzip**: the upstream server (the proxied Node app, etc.)
   returned a `Content-Encoding: gzip` body. The rendered ConfigMap includes
   `proxy_set_header Accept-Encoding "";` to disable upstream gzip; verify
   this directive is in the actual config: `kubectl exec <pod> -c <nginx-container> -- nginx -T | grep Accept-Encoding`.

2. **Static-file gzip**: nginx's own `gzip on; gzip_types text/html;`
   compresses the file BEFORE sub_filter sees it. Either remove `text/html`
   from `gzip_types` or set `gzip off;` in the location block:
   ```nginx
   location / {
       gzip off;
       try_files $uri $uri/ /index.html;
       sub_filter '</head>' '<the snippet></head>';
   }
   ```

3. **Pre-compressed `.html.gz` files**: if your build emits `index.html.gz`
   alongside `index.html` and `gzip_static on;` is enabled, nginx serves
   the `.gz` directly without sub_filter. Disable `gzip_static` for HTML or
   delete the `.gz` files in your build output.

4. **Mismatched content-type**: the rendered config sets
   `sub_filter_types text/html;` but if the upstream returns
   `application/xhtml+xml`, sub_filter doesn't match. Either change the
   upstream Content-Type header or add the alt MIME type to `sub_filter_types`.

## ingress-nginx ignores the configuration-snippet (mode A.ii)

### Symptom

`kubectl get ingress` shows the annotation but `curl` returns the original
HTML without the snippet. ingress-nginx controller logs show nothing.

### Cause and fix

CVE-2021-25742 hardening. As of ingress-nginx 1.0.1+, snippets are disabled
by default. Patch the controller's ConfigMap:

```bash
kubectl -n ingress-nginx patch configmap ingress-nginx-controller \
    --type merge -p '{"data":{"allow-snippet-annotations":"true"}}'
```

For ingress-nginx 1.9.0+, also lower the annotations risk floor:

```bash
kubectl -n ingress-nginx patch configmap ingress-nginx-controller \
    --type merge -p '{"data":{"annotations-risk-level":"Critical"}}'
```

If your security policy forbids enabling snippets, switch to mode A.i or C.

## initContainer rewriter fails (mode C)

### Symptom

Pod stuck in `Init:Error`. `kubectl describe pod` shows
`splunk-rum-rewriter` exited non-zero.

### Cause and fix

Read the rewriter logs:

```bash
kubectl logs <pod> -c splunk-rum-rewriter
```

Common errors:

- `source HTML not found at /usr/share/nginx/html/index.html` — the source
  path is wrong for your image. Set `serve_path` and `html_file` in the
  workload spec to match where the image actually serves HTML from.
- `permission denied` — the rewriter container ran as root by default; the
  shared `emptyDir` should accept writes. If your cluster's PSS forbids root,
  the rewriter image needs a non-root variant. Override `rewriter_image` to
  one that runs as non-root.
- `awk: not found` — extremely minimal images. Override `rewriter_image` to
  `busybox:1.36` or `alpine:3.19`.

## CSP blocks the agent

### Symptom

Browser console shows `Refused to load the script 'https://cdn.observability.splunkcloud.com/...' because it violates the following Content Security Policy directive`.

### Fix

See [csp-and-https.md](csp-and-https.md). Add the CDN host to `script-src`
and the beacon host to `connect-src`.

## Inline script blocked by CSP `'unsafe-inline'` exclusion

### Symptom

Agent script loads (CDN OK) but `SplunkRum.init` is never called. Browser
console shows `Refused to execute inline script because it violates the
following Content Security Policy directive: "script-src 'self' ..."`.

### Fix

The rendered snippet uses an inline `<script>...</script>` to call init.
Strict CSPs disallow inline scripts. Three options:

1. Add a CSP nonce to your middleware and inject it into the snippet
   (manual; this skill does not auto-generate nonces).
2. Switch to mode B (runtime-config) — the init call lives in your bundled
   JS, not inline.
3. Add `'unsafe-inline'` to `script-src` (not recommended).

## Stack traces are mangled

### Cause and fix

You haven't uploaded source maps. See [source-maps.md](source-maps.md).

## Session Replay shows but is incomplete

### Cause and fix

- Network bandwidth: large segments may drop on slow networks. Try setting
  `session_replay.max_export_interval_ms: 3000` to flush more often.
- Multiple browser tabs: the Splunk RUM UI shows tabs at the top of the
  session view. Click the tab you care about — segments are per-tab.
- Cross-origin iframes are never recorded. The recorder shows a placeholder.
- Pre-existing CSP `script-src` blocks the recorder. Confirm
  `cdn.observability.splunkcloud.com` is allowlisted for the recorder script
  too, not just the agent script.

## Anti-virus / corporate proxy intercepts beacons

### Symptom

Beacons go out from DevTools but the RUM UI shows zero data. POST returns
`200 OK` from a non-Splunk server.

### Fix

A corporate proxy (Zscaler, Forcepoint, custom) is intercepting the
RUM beacon and returning a fake 200 without forwarding. Add
`*.observability.splunkcloud.com` (or `*.signalfx.com` for legacy) to the
proxy allowlist for direct passthrough.

## Distinguishing this skill from AppDynamics BRUM

If you find yourself looking for AppDynamics-specific configuration (like
`adrum.js`, EUM cookies, or AppDynamics Browser RUM rate-limit settings),
you have the wrong skill. This skill is **Splunk Browser RUM** only. For
AppDynamics Browser RUM, see [cisco-appdynamics-setup](../../cisco-appdynamics-setup/SKILL.md).
