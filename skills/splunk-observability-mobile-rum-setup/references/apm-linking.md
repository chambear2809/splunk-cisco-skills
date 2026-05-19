# RUM-To-APM Linking

Splunk RUM links mobile frontend traces to backend APM traces through the
`Server-Timing` response header:

```text
Server-Timing: traceparent;desc="00-<32 hex trace id>-<16 hex span id>-01"
```

Validation:

```bash
bash skills/splunk-observability-mobile-rum-setup/scripts/validate.sh \
  --output-dir splunk-observability-mobile-rum-rendered \
  --check-server-timing https://api.example.com/health
```

Rules:

- `traceparent` must use version `00`, a 32-hex trace id, a 16-hex span id,
  and sampled flag `01`.
- If several valid traceparent values are present, the last valid header wins.
- Mobile cross-origin callers may also need backend CORS exposure for
  `Server-Timing`, depending on client access pattern.
- When missing, use the generated `handoff-auto-instrumentation.sh` to route
  backend response-header setup to the owning APM/auto-instrumentation skill.
