# React Native Mobile RUM

- Minimums: React Native 0.75.0 and React 18.2.0.
- Android runtime floor defaults to API 24; iOS floor is 15.0.
- Bare React Native apps use the native iOS and Android setup paths.
- Expo apps need a development build; Expo Go cannot load custom native
  modules.
- iOS projects need no Podfile linkage change. From agent 1.0.1 the native iOS
  SDK ships as vendored xcframeworks instead of resolving through SPM at
  `pod install`, so `USE_FRAMEWORKS=dynamic` is no longer required and
  `use_frameworks! :linkage => :static` works.
- Use provider or imperative initialization depending on the app architecture.
- Use manual instrumentation for navigation and custom workflows where
  automatic route detection is insufficient.

Session Replay:

- Requires `@splunk/otel-session-replay-react-native` and
  `--accept-session-replay-enterprise`.
- Default sample rate emitted by this skill is `0.2`.
- Configure the module with `SessionReplayModuleConfiguration`, then use
  `SplunkSessionReplay.instance.start()`, `stop()`, `getState()`, and
  `setRecordingMask()` for runtime controls.
- Do not claim Mobile RUM support for React Native JS bundle source-map upload.
  Use native dSYM/mapping upload; use Browser RUM source maps only for WebView
  pages.
