---
name: splunk-observability-browser-rum-setup
description: >-
  Render, validate, apply, and hand off generic Splunk Observability Cloud Browser RUM
  and Session Replay setup for web applications outside the Kubernetes injection
  path, including CDN snippets, npm/TypeScript initialization, Next.js/Vite/
  Webpack source-map upload helpers, CSP headers, Session Replay privacy
  controls, RUM-to-APM Server-Timing trace linking validation, and dashboard or
  detector handoffs. Use when the user asks for Splunk Browser RUM, JavaScript
  RUM, @splunk/otel-web, source maps, frontend Session Replay, DXA prerequisites,
  or non-Kubernetes browser instrumentation.
---

# Splunk Observability Browser RUM Setup

Use this skill for Browser RUM instrumentation that belongs in the web app
source tree, build pipeline, CDN HTML template, or server-rendered frontend. For
Kubernetes pod-side, ingress, or initContainer injection, use
`splunk-observability-k8s-frontend-rum-setup`.

The workflow is render-first. It does not embed RUM token values. Rendered
snippets reference a build-time variable or placeholder and keep the
server-to-server Observability API token for source-map upload in
`SPLUNK_O11Y_TOKEN_FILE`.

## Workflow

1. Render snippets for the framework or deployment path:

```bash
bash skills/splunk-observability-browser-rum-setup/scripts/setup.sh --render \
  --application-name checkout-web \
  --environment prod \
  --realm us1 \
  --version 1.42.0 \
  --framework vite \
  --enable-session-replay
```

2. Review `browser-rum-plan.md`, `cdn-snippet.html`,
   `npm-init.ts`, `source-map-upload.sh`, and `csp-header.txt`.

3. Add the selected snippet to the application build or HTML template. Keep the
   same `applicationName` and `version` values in source-map uploads.

4. Validate the deployed site and endpoint reachability:

```bash
bash skills/splunk-observability-browser-rum-setup/scripts/validate.sh \
  --rendered-dir splunk-observability-browser-rum-rendered \
  --check-url https://shop.example.com
```

5. After reviewing the rendered helper, inject and upload source maps from a
   completed frontend build:

```bash
chmod 600 /path/to/o11y-token
bash skills/splunk-observability-browser-rum-setup/scripts/setup.sh \
  --upload-source-maps \
  --output-dir splunk-observability-browser-rum-rendered \
  --assets-dir /path/to/app/dist \
  --token-file /path/to/o11y-token
```

6. Hand off dashboards to `splunk-observability-dashboard-builder`, detectors to
   `splunk-observability-native-ops`, and missing backend trace headers to the
   appropriate APM or auto-instrumentation skill.

## Guardrails

- Never paste RUM tokens or Observability API tokens into chat or argv.
- Session Replay requires explicit privacy review before enablement.
- Source maps are server-to-server uploads; use an org/API token file, not the
  browser-embedded RUM token.
- `--upload-source-maps` requires an existing rendered helper, an existing build
  directory, and a token file with mode `0600` or `0400`; it never accepts a
  token value on argv.
- Keep CSP `script-src` and `connect-src` aligned with the selected CDN and
  `rum-ingest.<realm>.observability.splunkcloud.com`.
