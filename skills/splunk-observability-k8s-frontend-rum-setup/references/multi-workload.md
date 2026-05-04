# Multi-workload Spec

A single spec can drive injection across multiple frontend workloads in the
same cluster, with a different `injection_mode` per workload. This is the
common case: one nginx-served SPA, one distroless static page, one
ingress-fronted MPA.

## Spec example

```yaml
api_version: splunk-observability-k8s-frontend-rum-setup/v1
realm: us0
application_name: acme
deployment_environment: prod
version: "1.42.0"
agent_version: v1
endpoints:
  domain: splunkcloud

workloads:
  - kind: Deployment
    namespace: storefront
    name: checkout-web
    injection_mode: nginx-configmap
    nginx_container: web
    serve_path: /usr/share/nginx/html
    application_name_override: acme-checkout

  - kind: Deployment
    namespace: storefront
    name: status-page
    injection_mode: init-container
    serve_path: /var/www/html
    rewriter_image: busybox:1.36
    application_name_override: acme-status

  - kind: Deployment
    namespace: marketing
    name: marketing-site
    injection_mode: ingress-snippet
    ingress_name: marketing-site

  - kind: Deployment
    namespace: console
    name: admin-spa
    injection_mode: runtime-config
    runtime_config_path: /rum-config.js
    application_name_override: acme-console

instrumentations:
  user_tracking_mode: anonymousTracking
  modules:
    webvitals: true
    errors: true
    frustrationSignals: true
```

## Per-workload overrides

Each workload entry may override these spec-level fields:

| Field | Default | Per-workload override |
|-------|---------|----------------------|
| `injection_mode` | required | required |
| `application_name` | from spec | `application_name_override` |
| `deployment_environment` | from spec | `deployment_environment_override` |
| `version` | from spec | `version_override` |

The instrumentation surface (modules, frustration signals, privacy, session
replay) is single-spec — every workload gets the same `SplunkRum.init` payload
modulo identity. If you need different RUM modules per workload, run the
skill multiple times with separate specs.

## Rendered output for a multi-workload spec

The renderer emits one set of mode-specific manifests per workload, keyed by
workload name:

```
splunk-observability-k8s-frontend-rum-rendered/
├── k8s-rum/
│   ├── nginx-rum-configmap-checkout-web.yaml
│   ├── nginx-deployment-patch-checkout-web.yaml
│   ├── initcontainer-configmap-status-page.yaml
│   ├── initcontainer-patch-status-page.yaml
│   ├── ingress-snippet-patch-marketing-site.yaml
│   ├── runtime-config-configmap-admin-spa.yaml
│   ├── runtime-config-deployment-patch-admin-spa.yaml
│   ├── bootstrap-snippet-admin-spa.html
│   ├── injection-backup-configmap.yaml
│   ├── apply-injection.sh
│   ├── uninstall-injection.sh
│   ├── verify-injection.sh
│   └── status.sh
```

A single `apply-injection.sh` walks all four workloads, snapshots each,
applies its mode-specific manifests, and rolls each one out. A single
`injection-backup-configmap.yaml` records the targets so `uninstall-injection.sh`
can find them later.

## Targeting subset operations

To apply or uninstall only a subset of workloads:

1. Render only the subset by re-running with explicit `--workload Kind/NS/NAME=mode`
   flags (which override the spec).
2. Or run the rendered scripts manually with `kubectl apply -f <single-file>`
   and `kubectl rollout restart <kind>/<name>`.

The skill does not expose a `--target Kind/NS/NAME` filter on apply/uninstall
because the spec-driven approach is cleaner for GitOps repos: commit the
edited spec and re-render.

## Per-environment overrides

To deploy the same spec to dev and prod with different deployment
environments and sampling, use spec inheritance:

```yaml
# spec.base.yaml
api_version: splunk-observability-k8s-frontend-rum-setup/v1
realm: us0
application_name: acme
agent_version: v1
workloads:
  - kind: Deployment
    namespace: app
    name: web
    injection_mode: nginx-configmap

# spec.dev.yaml
api_version: splunk-observability-k8s-frontend-rum-setup/v1
realm: us0
application_name: acme
deployment_environment: dev
agent_version: v1
workloads:
  - kind: Deployment
    namespace: app-dev
    name: web
    injection_mode: nginx-configmap
instrumentations:
  debug: true

# spec.prod.yaml
api_version: splunk-observability-k8s-frontend-rum-setup/v1
realm: us0
application_name: acme
deployment_environment: prod
agent_version: v1.2.3   # exact pin in prod
agent_sri: sha384-...
workloads:
  - kind: Deployment
    namespace: app-prod
    name: web
    injection_mode: nginx-configmap
session_replay:
  enabled: true
  recorder: splunk
  sampler_ratio: 0.5
```

The skill itself does not implement spec composition — operators are expected
to use Kustomize, Helm post-rendering, or a small wrapper script to materialize
a single spec per environment before invoking the renderer.

## GitOps for multi-workload

When `--gitops-mode` is set, the renderer emits YAML only — no `apply-injection.sh`
or `uninstall-injection.sh`. The rendered tree is then ready to commit to your
GitOps repo and let Argo CD / Flux apply. See [gitops-mode.md](gitops-mode.md).
