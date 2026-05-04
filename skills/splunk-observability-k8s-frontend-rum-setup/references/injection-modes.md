# Injection Modes

Splunk Browser RUM is delivered as a JavaScript snippet in the page `<head>`.
Getting that snippet into a Kubernetes-served frontend without modifying
application source means picking one of four injection modes. The skill renders
manifests for whichever mode each workload picks.

## Mode A.i: nginx pod-side ConfigMap (default)

**Pick this when**: the frontend is served by an nginx container in the pod
(typical for React / Vue / Angular SPAs built into a `nginx:alpine` image).

**What gets rendered**:

- `nginx-rum-configmap-<workload>.yaml` — a ConfigMap with a server-block
  snippet that includes:
  ```nginx
  sub_filter '</head>' '<the-rendered-snippet></head>';
  sub_filter_types text/html;
  sub_filter_once on;
  proxy_set_header Accept-Encoding "";
  ```
- `nginx-deployment-patch-<workload>.yaml` — a strategic-merge patch that
  mounts the ConfigMap into `/etc/nginx/conf.d/splunk-rum.conf` inside the
  nginx container.

**Container path notes**:

- Official `nginx` image reads `*.conf` from `/etc/nginx/conf.d/`. This is the
  default the renderer uses.
- `nginxinc/nginx-unprivileged` reads from the same path but runs as a
  non-root user (UID 101). The mount works the same way; no additional
  permissions changes needed.

**Gzip pitfall**: `sub_filter` does NOT work on gzipped responses. The
rendered config disables `proxy_set_header Accept-Encoding ""` for proxied
flavors so the upstream returns plain text. If your nginx serves static files
directly AND has `gzip on; gzip_types text/html;` in its main config,
sub_filter will silently do nothing because the response body is already gzip
bytes by the time sub_filter runs. Either:

- Remove `text/html` from `gzip_types`, OR
- Enable `gzip_static off;` for the index files, OR
- Switch to mode C (initContainer) which rewrites the file at startup.

**Pre-existing server blocks**: the rendered ConfigMap creates a new server
block on port 80. If your nginx already defines a server block for the same
port, the operator must merge the ConfigMap manually or remove the existing
block. The renderer prints a WARN in `preflight-report.md` when this
combination is plausible.

## Mode A.ii: ingress-nginx `configuration-snippet` annotation

**Pick this when**: the cluster runs `ingress-nginx` and the operator owns
the Ingress object that fronts the workload.

**What gets rendered**:

- `ingress-snippet-patch-<workload>.yaml` — a strategic-merge patch on the
  named Ingress that adds the `nginx.ingress.kubernetes.io/configuration-snippet`
  annotation containing the same `sub_filter` directives as mode A.i.

**Critical security gate**: since CVE-2021-25742, `ingress-nginx` defaults
`allow-snippet-annotations: "false"` on the controller's ConfigMap. With that
default in place, the rendered annotation is silently ignored. To make this
mode work, the cluster admin must:

1. Patch the `ingress-nginx-controller` ConfigMap:
   ```bash
   kubectl -n ingress-nginx patch configmap ingress-nginx-controller \
       --type merge -p '{"data":{"allow-snippet-annotations":"true"}}'
   ```
2. (ingress-nginx 1.9.0+) Also adjust `annotations-risk-level` if it filters
   out `Critical`-rated annotations:
   ```bash
   kubectl -n ingress-nginx patch configmap ingress-nginx-controller \
       --type merge -p '{"data":{"annotations-risk-level":"Critical"}}'
   ```

These changes have **multi-tenant security implications** (CVE-2021-25742 lets
operators with Ingress create/update permission read all cluster Secrets).
Many security-conscious clusters run with snippets disabled for that reason.
If your cluster does, pick mode A.i (pod-side) or mode C (initContainer)
instead. The renderer emits a WARN in `preflight-report.md` for any workload
that picks `ingress-snippet`.

## Mode C: initContainer HTML rewriter (distroless-safe)

**Pick this when**: the frontend container is distroless or otherwise lacks a
shell, OR when the served HTML lives at a non-standard path, OR when you
prefer to avoid modifying nginx config.

**What gets rendered**:

- `initcontainer-configmap-<workload>.yaml` — a ConfigMap containing the
  rendered RUM snippet plus a tiny `rewrite.sh` (`awk`-based, idempotent).
- `initcontainer-patch-<workload>.yaml` — a strategic-merge patch that adds:
  - An initContainer (default `busybox:1.36`) that reads the original HTML,
    injects the snippet before `</head>`, and writes the result to a shared
    `emptyDir` volume.
  - A `subPath` mount that overlays the rewritten file at the original served
    path inside the main container.

**Distroless detection**: the renderer scans the workload's `image` field
(when supplied in the spec) for distroless patterns (`gcr.io/distroless/`,
`cgr.dev/chainguard/`, or any image containing `distroless`). When a match is
found, the rewriter image is auto-injected into the patch and a WARN is added
to `preflight-report.md` so the operator knows the utility-image fallback is
active. To override the rewriter image (e.g., to pin to a private mirror):

```yaml
workloads:
  - kind: Deployment
    namespace: prod
    name: distroless-app
    injection_mode: init-container
    rewriter_image: my-registry.example.com/busybox:1.36
```

**Idempotency**: the rewriter writes a sentinel comment after the injected
snippet. On re-runs (operator restart, sidecar relaunch), it skips re-writing
if the sentinel is already present. This makes the initContainer safe to run
on every pod boot.

**Trade-offs vs A.i**:

- Mode C copies the HTML on every pod start; mode A.i applies sub_filter on
  every HTTP response. Mode C has lower request-time overhead but slightly
  higher pod-start cost.
- Mode C produces a single rewritten file. If your app serves multiple HTML
  entry points from the same nginx, mode A.i (which rewrites every served
  HTML response) is more general.

## Mode B: runtime-config ConfigMap (for npm-bundled apps)

**Pick this when**: the app already bundles `@splunk/otel-web` via npm and
just needs realm + RUM token + applicationName + environment + version
delivered at runtime (so the same image can run in dev / staging / prod
without a rebuild).

**What gets rendered**:

- `runtime-config-configmap-<workload>.yaml` — a ConfigMap containing
  ```javascript
  window.SPLUNK_RUM_CONFIG = { realm, rumAccessToken, applicationName, ... };
  window.SPLUNK_RUM_SESSION_REPLAY_CONFIG = { ... };  // when Session Replay enabled
  ```
- `runtime-config-deployment-patch-<workload>.yaml` — a patch that mounts the
  ConfigMap at `/usr/share/nginx/html/rum-config.js` (configurable).
- `bootstrap-snippet-<workload>.html` — a copy-pasteable snippet for the
  operator to drop into the app's index.html. It loads the agent script,
  loads `rum-config.js`, and calls `SplunkRum.init(window.SPLUNK_RUM_CONFIG)`.

**Caveat**: this mode requires the operator to add the `bootstrap-snippet`
to the app's source `index.html` once. After that, deploys never need code
changes — the ConfigMap delivers the runtime config.

## Istio service mesh

**Not rendered**. Istio EnvoyFilter / Lua body-rewrite injection is a viable
alternative for mesh-native injection, but the operational surface (admission
control, version skew, EnvoyFilter ordering, debugging) is significantly
more complex than the four modes above. Mesh users should pick mode A.i
(pod-side) — it works identically inside or outside a mesh.

## Multi-workload mixed-mode

A single spec can mix all four modes across different workloads. Per-workload
`injection_mode` overrides the spec's default. See
[multi-workload.md](multi-workload.md).

## Mode picker

| Symptom | Pick |
|---------|------|
| Standard React/Vue/Angular SPA on `nginx:alpine` | A.i nginx-configmap |
| App on distroless / scratch / chainguard | C init-container |
| nginx in pod plus pre-existing server block you can't edit | C init-container |
| ingress-nginx with snippets enabled (and you accept the CVE-2021-25742 trade-off) | A.ii ingress-snippet |
| App already imports `@splunk/otel-web` via npm | B runtime-config |
| Need different config per environment from same image | B runtime-config |
| Multi-page MPA on httpd | A.i (nginx in front) or C (rewrite per page) |
