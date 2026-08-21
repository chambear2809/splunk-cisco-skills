# Android Mobile RUM

- Use Maven Central and pin `com.splunk:splunk-otel-android`.
- Pin Android plugin artifacts with the same current default:
  `com.splunk:rum-mapping-file-plugin`,
  `com.splunk:rum-okhttp3-auto-plugin`, and
  `com.splunk:rum-httpurlconnection-auto-plugin`.
- Default runtime floor is API 24. Lower API work requires an explicit force
  flag and extra compatibility testing.
- Agent `2.3.2` renamed the `deployment.environment` resource attribute to
  `deployment.environment.name` and emits only the new key, so queries written
  against the old key return nothing once an app upgrades. The
  `deploymentEnvironment` configuration property is unchanged.
- Enable core library desugaring.
- Review OkHttp, HttpURLConnection, crash, ANR, slow rendering, interaction,
  network monitor, lifecycle, navigation, and WebView modules per app.
- Use mapping upload helpers from CI after release builds.
- Use Gradle plugin id `com.splunk.rum-mapping-file-plugin` for automatic
  mapping upload/build-id injection, pinned to the reviewed plugin version.

Session Replay:

- Requires `--accept-session-replay-enterprise`.
- Use View-level masks for auth, payment, health, profile, and text-heavy
  screens.
- Use `SplunkRum.instance.sessionReplay.start()`, `stop()`, `state.status`,
  rendering-mode preferences, and recording masks for runtime control.
- Validate masking on physical devices and emulators before production rollout.
