# iOS Mobile RUM

- Use the pinned `splunk-otel-ios` release from `Package.swift`.
- Minimum runtime: iOS/iPadOS 15.0.
- Keep the RUM token in build-time configuration, not tracked source.
- Add release attributes: `deployment.environment`, `app.version`,
  `release.name`, `release.build`, and `release.distribution`.
- Enable URLSession, navigation, crash reporting, slow rendering, and
  interaction modules only after reviewing app behavior.
- Use the generated dSYM helper from CI after archive/export.
- WebViews require Browser RUM on the hosted page plus the native bridge snippet
  only for pages the operator controls.

Session Replay:

- Requires `--accept-session-replay-enterprise`.
- Start/stop recording around sensitive screens.
- Verify local-device masking for labels, text fields, screenshots, payment,
  health, profile, and auth screens.
