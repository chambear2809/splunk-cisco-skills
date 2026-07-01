---
name: splunk-appdynamics-eum-setup
description: >-
  Render and validate Splunk AppDynamics End User Monitoring workflows,
  including Browser RUM, Mobile RUM, IoT RUM, EUM account and application keys,
  JavaScript injection, iOS, Android, React Native, Flutter, .NET MAUI snippets,
  Browser Session Replay, Mobile Session Replay, mapping, source-map upload, and beacon validation. Use when
  the user asks for AppDynamics EUM, Browser RUM, BRUM, Mobile RUM, IoT RUM,
  app keys, JavaScript injection, Session Replay, Mobile Session Replay, source maps, mobile SDKs, or
  EUM beacon validation.
---

# Splunk AppDynamics EUM Setup

The wrapper does not edit application source or upload mappings; `--apply`
fails closed. Render mode writes Browser RUM, mobile SDK, Browser Session
Replay, Mobile Session Replay, and operator/CI source-upload runbooks.

```bash
bash skills/splunk-appdynamics-eum-setup/scripts/setup.sh --render
bash skills/splunk-appdynamics-eum-setup/scripts/validate.sh
```
