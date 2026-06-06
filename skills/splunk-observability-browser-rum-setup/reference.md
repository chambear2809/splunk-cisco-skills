# Splunk Observability Browser RUM Setup Reference

This skill covers generic web application Browser RUM setup outside the
Kubernetes injection path. It is source/build-pipeline oriented and emits
reviewable snippets rather than editing application code directly.

## Instrumentation Modes

| Mode | Use when | Rendered asset |
| --- | --- | --- |
| CDN | HTML template can load Splunk's CDN agent before app boot | `cdn-snippet.html` |
| npm | App bundles `@splunk/otel-web` through TypeScript/JavaScript | `npm-init.ts` |
| Next.js | Next app needs client-side init plus source-map upload handoff | `next.config.snippet.js` |
| Vite | Vite app needs env-driven init plus source-map upload helper | `vite.env.example` |
| Webpack | Webpack app can use Splunk RUM source-map build plugin | `webpack-sourcemap-plugin.js` |

## Token Model

- Browser RUM token: safe to embed only as the documented public RUM ingest token
  for the application. The renderer uses placeholders or build-time references.
- Observability API token: used only for source-map uploads and API work. Keep it
  in `SPLUNK_O11Y_TOKEN_FILE`; never embed it in browser bundles.

## Session Replay Privacy

Before enabling Session Replay, review:

- Enterprise/subscription entitlement.
- User consent and privacy notice.
- `maskAllText`, sensitivity rules, and selectors that must never be recorded.
- Canvas/video/iframe capture options.
- Sampling rate and retention expectations.

## RUM To APM Linking

RUM-to-APM correlation depends on backend responses returning a
`Server-Timing: traceparent;desc="<traceparent>"` header for XHR/fetch and page
loads. The rendered validation file contains a curl-based check and a handoff to
runtime or Kubernetes auto-instrumentation skills when the header is missing.

## Source Anchors

- https://help.splunk.com/en/splunk-observability-cloud/manage-data/available-data-sources/supported-integrations-in-splunk-observability-cloud/rum-instrumentation/instrument-browser-based-web-applications/set-up-javascript-source-mapping
- https://help.splunk.com/en/splunk-observability-cloud/monitor-end-user-experience/real-user-monitoring
- https://help.splunk.com/en/splunk-observability-cloud/monitor-end-user-experience/real-user-monitoring/replay-user-sessions
