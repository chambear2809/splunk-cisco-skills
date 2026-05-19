# Splunk Observability Mobile RUM Reference

Use this skill for Splunk Observability Cloud Mobile RUM only. It is not an
AppDynamics EUM workflow and it is not the Kubernetes Browser RUM injection
workflow.

## Spec Shape

Required fields:

- `api_version: splunk-observability-mobile-rum-setup/v1`
- `realm`
- `platforms[]`

Common platform fields:

- `platform`: `ios`, `android`, `react_native`, or `flutter`
- `app_root`: local app source root, required only for source patch apply
- `app_name`
- `deployment_environment`
- `app_version`
- `release.name`, `release.build`, `release.distribution`
- `privacy.ignore_urls`, `privacy.redact_query_strings`,
  `privacy.user_tracking_mode`
- `session_replay.enabled`, `session_replay.sampling_rate`
- `validation_urls[]` for RUM-to-APM `Server-Timing` checks
- `webviews[]` for Browser RUM handoff pages

## Source Modes

- `render-snippets`: default, writes snippets and runbooks only.
- `render-patches`: writes unified patch files under `source-patches/`.
- `apply-patches`: applies generated patch files with `git apply`; requires
  `--accept-mobile-rum-source-edit`.

Patch files add small bootstrap files only. They do not edit existing app
build files because mobile build layouts vary too much for a safe blind edit.

## Token Handling

Use `rum_token_ref` or `SPLUNK_O11Y_RUM_TOKEN_FILE` for RUM token references.
Use `SPLUNK_O11Y_TOKEN_FILE` for dSYM and Android mapping upload helpers.
Never put token values in the spec or CLI args.

## Artifact Uploads

- iOS dSYMs: `splunk-rum ios upload` and `splunk-rum ios list`.
- Android mapping files: `splunk-rum android upload` and
  `splunk-rum android upload-with-manifest`.
- React Native and Flutter: route native symbols through the iOS and Android
  workflows.
- WebView Browser RUM source maps: hand off to
  `splunk-observability-k8s-frontend-rum-setup`.

## RUM-To-APM Validation

`validate.sh --check-server-timing <url>` checks for:

```text
Server-Timing: traceparent;desc="00-<32 hex>-<16 hex>-01"
```

When several valid values are present, the last valid header wins. Missing or
invalid values emit `handoff-auto-instrumentation.sh`.
