---
name: splunk-observability-mobile-rum-setup
description: >-
  Render, validate, and optionally apply guarded source patches for Splunk
  Observability Cloud Mobile RUM and mobile-side Digital Experience Analytics
  (DXA) prerequisites across native iOS, native Android, React Native, and
  Flutter apps. Covers pinned agent versions, Session Replay enterprise gating,
  privacy controls, release attributes, dSYM and Android mapping upload helpers,
  React Native and Flutter native artifact handoffs, WebView Browser RUM bridge
  snippets, and RUM-to-APM Server-Timing traceparent validation. Use when
  instrumenting mobile apps with Splunk RUM, preparing Mobile Session Replay,
  preparing mobile-side Digital Experience Analytics (DXA), validating
  RUM-to-APM linking, or rendering mobile source patches. Do not use for
  AppDynamics EUM or Kubernetes Browser RUM injection.
---

# Splunk Observability Mobile RUM

This skill configures **Splunk Observability Cloud Mobile RUM**, separate from
Kubernetes Browser RUM injection and AppDynamics EUM. It is render-first:
snippets and runbooks are the default output; patch files are optional; app
source is changed only when `--apply-patches --accept-mobile-rum-source-edit`
is explicitly used. Use it as the mobile instrumentation handoff when a Digital
Experience Analytics (DXA) request needs supported iOS or Android RUM agents,
user tracking, readable stack traces, or Mobile Session Replay.

## Scope

- Native iOS and iPadOS 15+ with the Splunk iOS agent.
- Native Android with Maven Central dependencies, API 24+ default runtime,
  desugaring, network/crash/ANR/slow-rendering/interaction/lifecycle modules,
  mapping upload, and WebView bridge snippets.
- React Native 0.75.0+ and React 18.2.0+ for bare apps and Expo development
  builds, with native-side dSYM/mapping handoffs.
- Flutter 3.32.0+ and Dart 3.8.0+ with `splunk_otel_flutter`, native-side
  dSYM/mapping handoffs, route/manual instrumentation, and WebView handoff.
- Session Replay behind `--accept-session-replay-enterprise`.
- RUM-to-APM linking validation for
  `Server-Timing: traceparent;desc="00-<32 hex>-<16 hex>-01"`.

## Version Pins

Defaults are pinned to package versions verified on 2026-05-19:

| Component | Default |
| --- | --- |
| iOS agent | `2.2.3` |
| Android agent | `2.3.0` |
| Android Gradle plugins | `2.3.0` |
| React Native agent | `1.0.0` |
| React Native Session Replay | `1.0.0` |
| Flutter agent | `1.0.1` |
| Flutter Session Replay | `1.0.1` |

The renderer rejects `latest`, `+`, ranges, wildcard, and otherwise unpinned
versions unless `--allow-latest-version` is set.

## Workflow

1. Render snippets:

   ```bash
   bash skills/splunk-observability-mobile-rum-setup/scripts/setup.sh \
     --render \
     --spec skills/splunk-observability-mobile-rum-setup/template.example
   ```

2. Review `splunk-observability-mobile-rum-rendered/`:
   - `runbook.md`
   - `preflight-report.md`
   - platform snippet directories
   - `version-lock.json`
   - dSYM/mapping upload helpers
   - Browser RUM and backend auto-instrumentation handoff scripts

3. Optionally render source patches:

   ```bash
   bash skills/splunk-observability-mobile-rum-setup/scripts/setup.sh \
     --render-patches \
     --spec mobile-rum.yaml
   ```

4. Optionally apply source patches after review:

   ```bash
   bash skills/splunk-observability-mobile-rum-setup/scripts/setup.sh \
     --apply-patches \
     --accept-mobile-rum-source-edit \
     --spec mobile-rum.yaml
   ```

5. Validate static output and optional RUM-to-APM response headers:

   ```bash
   bash skills/splunk-observability-mobile-rum-setup/scripts/validate.sh \
     --output-dir splunk-observability-mobile-rum-rendered \
     --check-server-timing https://api.example.com/health
   ```

## Safety Rules

- Never pass raw tokens with CLI flags. `--rum-token`, `--access-token`,
  `--token`, `--bearer-token`, `--api-token`, `--o11y-token`, `--sf-token`,
  `--hec-token`, `--platform-hec-token`, and `--api-key` are rejected.
- RUM tokens are client-exposed after release, but this skill still refuses to
  commit or render raw token values into tracked source. Use token references,
  build-time config, CI secrets, or mobile platform secret delivery.
- Server-to-server dSYM and Android mapping upload helpers use
  `SPLUNK_O11Y_TOKEN_FILE`; they do not accept token literals.
- `source_mode: apply-patches` requires `--accept-mobile-rum-source-edit`.
- Session Replay requires `--accept-session-replay-enterprise` and reviewed
  masking rules.

## References

Read the platform file that matches the app being instrumented:

- [references/ios.md](references/ios.md)
- [references/android.md](references/android.md)
- [references/react-native.md](references/react-native.md)
- [references/flutter.md](references/flutter.md)
- [references/privacy-session-replay.md](references/privacy-session-replay.md)
- [references/apm-linking.md](references/apm-linking.md)

## Hand-offs

- Browser RUM inside WebViews:
  [splunk-observability-k8s-frontend-rum-setup](../splunk-observability-k8s-frontend-rum-setup/SKILL.md)
- Backend response header enablement:
  [splunk-observability-k8s-auto-instrumentation-setup](../splunk-observability-k8s-auto-instrumentation-setup/SKILL.md)
- Dashboards:
  [splunk-observability-dashboard-builder](../splunk-observability-dashboard-builder/SKILL.md)
- Detectors:
  [splunk-observability-native-ops](../splunk-observability-native-ops/SKILL.md)

## Out Of Scope

- AppDynamics EUM, BRUM, MRUM, or AppDynamics Session Replay.
- Kubernetes Browser RUM HTML injection for web frontends.
- Uploading React Native JS bundle source maps as a Mobile RUM artifact.
  Browser source maps only apply to WebView pages instrumented with Browser RUM.
- Running mobile app builds or live Splunk uploads by default.
