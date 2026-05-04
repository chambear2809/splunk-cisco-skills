# Session Replay + Privacy

Splunk Session Replay reconstructs what a real user saw and did during a session,
which is invaluable for debugging UX bugs but obviously sensitive from a privacy
standpoint. This skill exposes every privacy and feature knob the Splunk
recorder offers; you decide how aggressive to be.

## Prerequisites

- **Enterprise tier subscription** — Session Replay is not available on
  Standard. The renderer refuses to emit `SplunkSessionRecorder.init(...)`
  unless `--accept-session-replay-enterprise` is passed.
- **Splunk RUM browser agent v0.23.1+** for Session Replay support, and v1.0.0+
  for the new Splunk recorder format (`recorder: 'splunk'`).

## Splunk recorder vs legacy rrweb recorder

Splunk RUM browser agent v1.0.0 (Oct 2025) deprecated the rrweb recorder and
introduced the Splunk-native recorder. The new recorder produces smaller
segments, has a richer privacy API (`sensitivityRules`), and is the recommended
choice for all new deployments.

| Legacy rrweb option | Splunk recorder equivalent | Migration support |
|--------------------|---------------------------|-------------------|
| `blockClass` | `sensitivityRules` (`exclude`) | Partial — regex blockClass cannot migrate |
| `blockSelector` | `sensitivityRules` (`exclude`) | Full |
| `ignoreClass` | `sensitivityRules` (`exclude`) | Partial |
| `maskTextClass` | `sensitivityRules` (`mask`) | Partial |
| `maskTextSelector` | `sensitivityRules` (`mask`) | Full |
| `maskAllInputs` | `maskAllInputs` | Full |
| `maskInputOptions` | n/a | Manual; renderer surfaces a WARN |
| `maskInputFn` | n/a | Manual |
| `maskTextFn` | n/a | Manual |
| `inlineStylesheet` | `features.packAssets.styles` | Full |
| `inlineImages` | `features.packAssets.images` | Full |
| `collectFonts` | `features.packAssets.fonts` | Full |
| `recordCanvas` | `features.canvas` | Full |

The renderer emits a WARN in `preflight-report.md` when `recorder: rrweb` is
chosen so you can plan a migration.

## Default safety posture

```yaml
session_replay:
  enabled: true
  recorder: splunk
  mask_all_inputs: true   # all <input> values replaced with animations
  mask_all_text: true     # all text replaced with black bars
  sensitivity_rules: []   # no overrides
```

This is the safest starting point. From here you selectively `unmask` content
you know is non-sensitive (product names, headings) and `exclude` regions that
should not be recorded at all (payment forms, user profiles).

## Sensitivity rules

`sensitivity_rules` is an ordered list. Later rules override earlier ones.

```yaml
session_replay:
  enabled: true
  mask_all_text: true
  sensitivity_rules:
    - rule: unmask
      selector: "h1, h2, h3"     # show headings (safe)
    - rule: unmask
      selector: ".product-name"  # show product names (safe)
    - rule: mask
      selector: ".product-name .private-info"  # but not nested private bits
    - rule: exclude
      selector: "#user-profile"  # don't record user profile interactions at all
    - rule: exclude
      selector: "input[type=password]"  # never record password inputs
```

| Rule | Behavior |
|------|----------|
| `mask` | Replace text with black bars. User input still triggers events but content is hidden. |
| `unmask` | Show element content even when `mask_all_text: true`. |
| `exclude` | Render a placeholder DIV of the same size; record no interactions on it. Cannot be overridden by later rules. |

## Sampling

Session Replay segment volume is significant. Use the sampler to control cost.

```yaml
session_replay:
  enabled: true
  sampler_ratio: 0.5  # record ~50% of sessions; the other half collects RUM only
```

`sampler_ratio` is session-based: a session is fully recorded or fully not
recorded, not partially. Set to `0.0` to disable recording without disabling
the recorder entirely (useful for keeping the snippet shape stable while
ramping). Set to `1.0` to record every session.

## Features

`features` toggles media and asset capture.

| Feature | Default | What it does |
|---------|---------|--------------|
| `canvas` | false | Record `<canvas>` content. Can dramatically increase segment size. |
| `video` | false | Record `<video>` element state (not pixel data). |
| `iframes` | false | Record same-origin `<iframe>` content. Cross-origin iframes are never recorded. |
| `pack_assets.styles` | true | Inline CSS into the segment so playback is faithful. |
| `pack_assets.fonts` | false | Inline font files. Big payload increase. |
| `pack_assets.images` | false | Inline image files as base64. Very big payload increase. |
| `cache_assets` | false | Store seen asset URLs in localStorage to skip re-packing on subsequent loads. |
| `background_service_src` | empty | URL to a hosted `background-service.html` page. When set, segment processing runs in a Web Worker hosted at that URL. |

When you enable `pack_assets.images` or `pack_assets.fonts`, also set
`cache_assets: true` to amortize the cost across page loads in the same session.

## Background service page

For high-traffic apps, the segment-processing work the recorder does on the
main thread can cause main-thread jank. Splunk supports hosting that processing
in a Web Worker page you serve from your own origin:

1. Download `background-service.html` from the GitHub Releases page of
   `signalfx/splunk-otel-js-web`.
2. Serve it from a path the browser can reach — typically a static file in
   the same nginx ConfigMap that serves the SPA.
3. Set `features.background_service_src` to that URL (must be same-origin
   for the recorder to use it).

## Session lifecycle

- **Maximum session duration**: 4 hours. After that, the recorder rotates to
  a new session ID.
- **Idle timeout**: 15 minutes after last user interaction. After that, the
  next interaction starts a new session.
- **Tabs**: each tab in the same browser shares the session ID via a cookie.
  When `persistance: localStorage` is set, sessions don't share across tabs
  (no cookie storage).

## Cookie-consent and legal note

You are responsible for using Splunk Observability Cloud in compliance with
applicable laws, including providing notice to and obtaining any necessary
consent from individuals whose data will be collected. This skill does NOT
integrate with cookie-consent banners. Operators should:

- Add a checkbox or banner that gates Session Replay opt-in for users in
  jurisdictions that require consent (EU GDPR, California CCPA, etc.).
- When the user has not consented, set `sampler_ratio: 0.0` at runtime via
  custom JS — easiest in mode B (runtime-config) where the operator can
  flip a cookie value before `SplunkSessionRecorder.init()` is called.

## CSP and Session Replay

When Session Replay is enabled with `features.background_service_src`, the
operator must add the worker source to CSP:

```
worker-src 'self' <background-service-host>;
script-src ... cdn.observability.splunkcloud.com;
connect-src ... rum-ingest.<realm>.observability.splunkcloud.com;
```

See [csp-and-https.md](csp-and-https.md).
