# Splunk Observability Kubernetes Frontend RUM — Reference

Companion to [SKILL.md](SKILL.md). This file documents every CLI flag, every
rendered output file, and every preflight/static check.

## Files in This Skill

```
skills/splunk-observability-k8s-frontend-rum-setup/
├── SKILL.md                     # Operator-facing skill summary
├── reference.md                 # This file
├── template.example             # Canonical YAML spec
├── agents/
│   └── openai.yaml              # Agent display metadata
├── scripts/
│   ├── setup.sh                 # Orchestrator: render | guided | discover | apply | uninstall | validate
│   ├── render_assets.py         # Python renderer (the meat)
│   └── validate.sh              # Static + --live validation
└── references/
    ├── injection-modes.md
    ├── session-replay-privacy.md
    ├── frustration-signals.md
    ├── manual-instrumentation.md
    ├── source-maps.md
    ├── apm-linking.md
    ├── csp-and-https.md
    ├── discovery-workflow.md
    ├── realms-and-endpoints.md
    ├── framework-notes.md
    ├── multi-workload.md
    ├── troubleshooting.md
    └── gitops-mode.md
```

## Rendered Layout

Default output directory: `splunk-observability-k8s-frontend-rum-rendered/`.

```
splunk-observability-k8s-frontend-rum-rendered/
├── k8s-rum/
│   ├── nginx-rum-configmap.yaml          # Mode A.i
│   ├── nginx-deployment-patch.yaml       # Mode A.i
│   ├── ingress-snippet-patch.yaml        # Mode A.ii
│   ├── initcontainer-patch.yaml          # Mode C
│   ├── runtime-config-configmap.yaml     # Mode B
│   ├── runtime-config-deployment-patch.yaml  # Mode B
│   ├── bootstrap-snippet.html            # Mode B
│   ├── injection-backup-configmap.yaml
│   ├── apply-injection.sh                # omitted in --gitops-mode
│   ├── uninstall-injection.sh            # omitted in --gitops-mode
│   ├── verify-injection.sh
│   └── status.sh
├── discovery/                            # only with --discover-frontend-workloads
│   ├── workloads.yaml
│   └── services.yaml
├── source-maps/                          # only when source_maps.enabled: true
│   ├── sourcemap-upload.sh               # omitted in --gitops-mode
│   ├── github-actions.yaml               # only when ci_provider: github_actions
│   ├── gitlab-ci.yaml                    # only when ci_provider: gitlab_ci
│   └── splunk.webpack.js                 # only when bundler: webpack
├── runbook.md
├── preflight-report.md
├── handoff-dashboards.sh                 # when handoffs.dashboard_builder: true
├── handoff-detectors.sh                  # when handoffs.native_ops: true
├── handoff-cloud-integration.sh          # when handoffs.cloud_integration: true
├── handoff-auto-instrumentation.sh       # when --check-server-timing fails or handoffs.auto_instrumentation: true
└── metadata.json
```

Mode-specific files are only rendered for workloads that select that mode.

## `setup.sh`

### Modes (pick one; `--render` is default)

| Flag | Description |
|------|-------------|
| `--render` | Render assets (no cluster mutation). Default. |
| `--guided` | Interactive Q&A walk-through covering every SplunkRum.init knob, every Session Replay knob, every Frustration Signals knob. Writes a populated spec, then renders. |
| `--discover-frontend-workloads` | Read-only `kubectl get svc,deploy,daemonset,statefulset` scan. Flags candidate frontend workloads (image patterns: nginx, httpd, node; service ports 80/8080/3000) and emits a starter `discovery/workloads.yaml`. |
| `--apply-injection` | Apply rendered manifests + rollout restart. Requires `--accept-frontend-injection`. |
| `--uninstall-injection` | Reverse patches from `injection-backup-configmap.yaml`, rollout restart, delete ConfigMaps. Requires `--accept-frontend-injection`. |
| `--validate` | Forwarded to `validate.sh` against the rendered output. |

### Common options

| Flag | Description |
|------|-------------|
| `--spec PATH` | YAML or JSON spec. Defaults to `template.example`. |
| `--output-dir DIR` | Rendered output directory. |
| `--dry-run` | Show plan without writing. Composable with `--render` / `--apply-injection` / `--uninstall-injection`. |
| `--json` | Emit JSON metadata + plan. |
| `--explain` | Print plan in plain English. |
| `--gitops-mode` | Render YAML manifests only. Omits `apply-injection.sh`, `uninstall-injection.sh`, and `sourcemap-upload.sh`. |
| `--kube-context CTX` | Forwarded to `kubectl` invocations. |

### Identity

| Flag | Description |
|------|-------------|
| `--realm REALM` | Override `spec.realm`. |
| `--application-name NAME` | Override `spec.application_name`. |
| `--deployment-environment ENV` | Override `spec.deployment_environment`. |
| `--version VERSION` | Override `spec.version` (lands as `app.version`). |
| `--cluster-name NAME` | Override `spec.cluster_name`. |
| `--cookie-domain DOMAIN` | Override `spec.cookie_domain`. |
| `--rum-token-file PATH` | Override `spec.rum_token_file`. Token files must be `chmod 600`; `--allow-loose-token-perms` overrides with WARN. |
| `--o11y-token-file PATH` | Override `SPLUNK_O11Y_TOKEN_FILE` for the source-map upload helper. |

### Endpoints + agent versioning

| Flag | Description |
|------|-------------|
| `--endpoint-domain DOMAIN` | `splunkcloud` (default) or `signalfx` (legacy; deprecation WARN). |
| `--cdn-base URL` | Override the auto-derived CDN URL prefix. Use for self-hosted CDNs. |
| `--beacon-endpoint-override URL` | Override the auto-derived `rum-ingest` beacon URL. |
| `--agent-version VERSION` | `v1` default. `latest` requires `--allow-latest-version`. |
| `--allow-latest-version` | Permit `agent_version: latest`. Refuses without it. |
| `--agent-sri SHA384` | Operator-supplied SRI hash for the exact-version `<script>` tag. |
| `--session-recorder-sri SHA384` | Same for the session recorder script. |
| `--legacy-ie11-build` | Emit the IE11 fallback `<script>`. |

### Workload selection (multi-workload, mixed-mode)

| Flag | Description |
|------|-------------|
| `--workload Kind/NS/NAME=mode` | Repeatable. mode is one of `nginx-configmap`, `ingress-snippet`, `init-container`, `runtime-config`. Adds to / overrides `spec.workloads`. |
| `--inventory-file PATH` | Read workloads from a previously rendered `discovery/workloads.yaml`. |

### SplunkRum.init knobs

`--debug`, `--no-debug-bots-frameworks`, `--persistance MODE`,
`--user-tracking-mode MODE`, `--global-attribute KEY=VAL` (repeatable),
`--ignore-url URL_OR_REGEX` (repeatable), `--exporter-otlp`,
`--sampler-type TYPE`, `--sampler-ratio RATIO`,
`--spa-metrics-enabled`, `--spa-quiet-time-ms MS`,
`--module-disable MODULE` (repeatable), `--module-enable MODULE` (repeatable),
`--interactions-extra-event NAME` (repeatable),
`--socketio-target NAME`.

### Frustration Signals 2.0

`--rage-click-disable`, `--rage-click-count N`, `--rage-click-timeframe-seconds N`,
`--rage-click-ignore-selector CSS` (repeatable),
`--enable-dead-click`, `--dead-click-time-window-ms MS`, `--dead-click-ignore-url URL` (repeatable),
`--enable-error-click`, `--error-click-time-window-ms MS`, `--error-click-ignore-url URL` (repeatable),
`--enable-thrashed-cursor`, `--thrashed-cursor-threshold FLOAT`, `--thrashed-cursor-throttle-ms MS`,
plus the full thrashed-cursor knob set under `--thrashed-cursor-*`.

### Browser RUM privacy

`--mask-all-text`, `--no-mask-all-text`, `--privacy-rule mask|unmask|exclude=CSS_SELECTOR` (repeatable).

### Session Replay (enterprise tier)

`--enable-session-replay`, `--accept-session-replay-enterprise` (REQUIRED gate),
`--session-replay-recorder splunk|rrweb`,
`--session-replay-mask-all-inputs`, `--session-replay-mask-all-text`,
`--session-replay-rule mask|unmask|exclude=CSS_SELECTOR` (repeatable),
`--session-replay-max-export-interval-ms MS`,
`--session-replay-sampler-ratio RATIO`,
`--session-replay-feature canvas|video|iframes|pack-assets|cache-assets` (repeatable),
`--session-replay-pack-asset styles|fonts|images` (repeatable),
`--session-replay-background-service-src URL`.

### Source maps

`--source-maps-enable`, `--source-maps-disable`,
`--source-maps-bundler cli|webpack`,
`--source-maps-injection-target-dir DIR`,
`--source-maps-ci github_actions|gitlab_ci|none`.

### CSP advisory

`--csp-emit-advisory`, `--csp-no-emit-advisory`.

### APM linking

`--apm-linking-enable`, `--apm-linking-disable`,
`--apm-linking-backend-url URL`.

### Hand-offs

`--no-handoff-dashboards`, `--no-handoff-detectors`, `--no-handoff-cloud-integration`,
`--enable-handoff-auto-instrumentation`.

### Apply gates

`--accept-frontend-injection` (REQUIRED for `--apply-injection` and `--uninstall-injection`),
`--accept-session-replay-enterprise` (REQUIRED when Session Replay is enabled).

### Rejected flags

The following are explicitly rejected. They are token-shaped and would either
expose secrets in shell history or bypass the file-path-only credential model:

- `--rum-token`, `--access-token`, `--token`, `--bearer-token`, `--api-token`,
  `--o11y-token`, `--sf-token`, `--hec-token`, `--platform-hec-token`, `--api-key`.

## `validate.sh`

### Static checks

- Every rendered YAML file parses (PyYAML when available, fallback parser otherwise).
- Every rendered `<script src=>` URL is HTTPS.
- Agent version is pinned (refuses `latest` unless `--allow-latest-version` was set during render).
- When agent version is `vX.Y.Z` exact pin, the script tag includes `integrity="sha384-..."`. WARN (not FAIL) when the operator did not supply an SRI hash.
- When Session Replay is enabled with `recorder: splunk`, the rrweb-legacy options (`maskTextSelector`, `maskInputOptions`, `maskTextClass`, `inlineImages`, `collectFonts`) are NOT present.
- Mode A.i nginx config includes `sub_filter_types text/html;` and either `proxy_set_header Accept-Encoding "";` (for proxied flavors) or a documented gzip note (static-file).
- Mode C initContainer uses the utility image (default `busybox:1.36`) when the target image looks distroless.
- Workload patches target only the specified workload kind/namespace/name.
- Rendered scripts do not echo secrets.
- `realm` is in the supported list (`us0`, `us1`, `us2`, `eu0`, `eu1`, `eu2`, `au0`, `jp0`).
- `applicationName` and `deploymentEnvironment` are non-empty.

### `--live` checks

| Flag | Description |
|------|-------------|
| `--check-injection URL` | `curl -sL URL` and grep for `SplunkRum.init(`. |
| `--check-session-replay URL` | Same plus `SplunkSessionRecorder.init(` when Session Replay is enabled. |
| `--check-csp URL` | `curl -I URL` and parse `Content-Security-Policy` for required `script-src` and `connect-src` allowlist entries. |
| `--check-rum-ingest` | DNS + TCP probe of `rum-ingest.<realm>.<endpoint-domain>:443`. |
| `--check-server-timing BACKEND_URL` | `curl -sI BACKEND_URL` and grep for `Server-Timing.*traceparent`. If absent, emits `handoff-auto-instrumentation.sh`. |
| `--check-source-maps` | Runs `splunk-rum sourcemaps verify --path <dist>` (when source-map helper rendered). |

## Preflight Catalog

The renderer emits `preflight-report.md` with one section per check. Each
finding is one of `OK`, `WARN`, `FAIL`. A FAIL aborts render unless explicitly
acknowledged.

| ID | Severity | Description |
|----|----------|-------------|
| `https-only` | FAIL | The rendered `<script src=>` URLs all use HTTPS. The Splunk Browser RUM agent requires HTTPS-served pages and assets. |
| `version-pinned` | FAIL | `agent_version` is not `latest`, OR `--allow-latest-version` was set. |
| `sri-emitted` | WARN | When `agent_version` is `vX.Y.Z`, an `agent_sri` (and `session_recorder_sri` when Session Replay is enabled) is supplied. |
| `realm-supported` | FAIL | `realm` is one of `us0`, `us1`, `us2`, `eu0`, `eu1`, `eu2`, `au0`, `jp0`. |
| `endpoint-domain-supported` | FAIL | `endpoints.domain` is `splunkcloud` or `signalfx`. Legacy `signalfx` emits a deprecation WARN. |
| `session-replay-gated` | FAIL | When `session_replay.enabled: true`, `--accept-session-replay-enterprise` was set. |
| `session-replay-recorder` | WARN | `recorder: rrweb` triggers a deprecation WARN; recommends migrating to `recorder: splunk`. |
| `frontend-injection-gated` | FAIL | `--apply-injection` / `--uninstall-injection` requires `--accept-frontend-injection`. |
| `mode-vs-image` | WARN | Mode A.i picked but the workload's primary container image does not match nginx patterns; or mode C picked but image looks like nginx (mode A.i would be cleaner). |
| `distroless-detected` | WARN | Target image looks distroless (e.g. `gcr.io/distroless/*`); auto-routes mode C through the utility image and warns operator. |
| `ingress-nginx-cve` | WARN | Mode A.ii picked but `kubectl get configmap -n ingress-nginx` shows `allow-snippet-annotations: "false"` (default since CVE-2021-25742). Operator must enable snippets or pick a different mode. |
| `gzip-warning` | WARN | Mode A.i picked: rendered `nginx-rum-configmap.yaml` includes `proxy_set_header Accept-Encoding "";` for proxied flavors and notes the gzip pitfall for static-file flavors. |
| `csp-advisory` | INFO | When `csp.emit_advisory: true`, the report repeats the script-src + connect-src + worker-src lines for the chosen endpoint domain and Session Replay backgroundServiceSrc. |
| `apm-linking-server-timing` | INFO | Documents the `Server-Timing` header expectation; live probe lives under `validate.sh --check-server-timing`. |
| `multi-workload-mixed-mode` | INFO | Reports per-workload injection_mode pairings. |
| `dotnet-framework` | n/a | Not applicable — this is browser RUM, not .NET. |

## `metadata.json` Schema

```json
{
  "skill": "splunk-observability-k8s-frontend-rum-setup",
  "version": "1",
  "spec_digest": "<sha256-of-spec-after-cli-overrides>",
  "realm": "us0",
  "application_name": "acme-checkout",
  "deployment_environment": "prod",
  "agent_version": "v1",
  "endpoint_domain": "splunkcloud",
  "session_replay_enabled": false,
  "source_maps_enabled": true,
  "targets": [
    {
      "kind": "Deployment",
      "namespace": "prod",
      "name": "checkout-web",
      "injection_mode": "nginx-configmap"
    }
  ],
  "rendered_files": ["..."],
  "preflight_summary": {
    "ok": 8,
    "warn": 1,
    "fail": 0
  },
  "handoffs": ["dashboards", "detectors", "cloud_integration"]
}
```
