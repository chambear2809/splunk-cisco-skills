# Flutter Mobile RUM

- Minimums: Flutter 3.32.0 and Dart 3.8.0.
- Android runtime floor defaults to API 24; iOS floor is 15.0.
- Use the pinned `splunk_otel_flutter` package; add the pinned
  `splunk_otel_flutter_session_replay` package only when Session Replay is
  enabled.
- Initialize before app startup instrumentation where practical.
- Add route observers and manual spans for workflows that need explicit naming.
- Native release artifacts still use iOS dSYM and Android mapping upload.

Session Replay:

- Requires `--accept-session-replay-enterprise`.
- Default sample rate emitted by this skill is `0.2`.
- Configure the module with `SessionReplayModuleConfiguration`, then use
  `SplunkSessionReplay.instance.start()`, `stop()`, `getStatus()`, and
  `setRecordingMask()` for runtime controls.
- Mask `TextField`, payment, health, profile, auth, and free-form text widgets.
