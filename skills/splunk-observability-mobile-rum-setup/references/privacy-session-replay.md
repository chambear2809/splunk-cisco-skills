# Privacy And Session Replay

Apply privacy rules to both telemetry and replay.

Telemetry controls:

- Redact query strings and path components that carry identifiers.
- Drop or hash customer IDs before using global attributes.
- Avoid `enduser.*` attributes unless privacy/legal owners approve them.
- Ignore auth, payment, health, profile, and account recovery URLs.

Session Replay controls:

- Enterprise-tier feature; render only with
  `--accept-session-replay-enterprise`.
- Prefer wireframe-only replay modes where available for highly sensitive
  workflows; use native/video rendering only after device-side masking checks.
- Use covering or erasing masks for sensitive views and elements.
- Mark platform-native sensitive elements directly where the SDK exposes
  sensitivity APIs, such as Android `View`/Compose sensitivity and mobile
  recording masks.
- Confirm masks on local devices before production.
- Treat WebViews as browser pages. Hide/show DOM elements with CSS rules and
  configure Browser RUM Session Replay separately for those pages.

Sampling:

- React Native and Flutter default to `0.2`.
- Native snippets expose start, stop, and status controls so apps can disable
  recording around sensitive workflows.
