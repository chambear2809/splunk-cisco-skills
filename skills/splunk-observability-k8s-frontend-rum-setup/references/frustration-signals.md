# Frustration Signals 2.0

Splunk Browser RUM 2.x introduced a comprehensive Frustration Signals
instrumentation that detects four distinct user-frustration patterns. The
emitted spans (named `frustration`) carry a `frustration_type` attribute
(`rage`, `dead`, `error`, `thrash`) so dashboards and detectors can slice on
them.

## Default-on / opt-in matrix

| Signal | Default | What it detects |
|--------|---------|-----------------|
| `rageClick` | ON | Multiple rapid clicks on the same element (UI is unresponsive). |
| `deadClick` | OFF | Click on an interactive element produces no DOM change and no network activity. |
| `errorClick` | OFF | Click is followed by a JS error (the click triggered a broken interaction). |
| `thrashedCursor` | OFF | Erratic back-and-forth mouse movement (user is confused or annoyed). |

Three of the four signals are opt-in because they have noticeable false-positive
rates on certain UI patterns (interactive canvases, drawing tools, expected
no-op confirmations). Enable each one selectively after a test run.

## Configuration via spec

```yaml
instrumentations:
  frustration_signals:
    rage_click:
      enabled: true            # default on; can be disabled
      count: 4                 # clicks needed to trigger
      timeframe_seconds: 1     # within this many seconds
      ignore_selectors:
        - "#interactive-canvas"
        - ".game-board"
    dead_click:
      enabled: false           # set true to opt in
      time_window_ms: 1000
      ignore_urls:
        - "/expected-no-response"
    error_click:
      enabled: false
      time_window_ms: 1000
      ignore_urls:
        - "/expected-errors"
    thrashed_cursor:
      enabled: false
      thrashing_score_threshold: 0.6
      throttle_ms: 16
      time_window_ms: 2000
      min_direction_changes: 4
      min_direction_change_degrees: 45
      min_total_distance: 300
      min_movement_distance: 5
      min_average_velocity: 300
      max_velocity: 5000
      max_confined_area_size: 200
      score_weight_direction_changes: 0.4
      score_weight_velocity: 0.3
      score_weight_confined_area: 0.3
      ignore_urls:
        - "/game"
        - "/drawing-tool"
```

## Configuration via CLI flags

| Flag | Effect |
|------|--------|
| `--rage-click-disable` | Turn rage-click detection off entirely. |
| `--rage-click-count N` | Override the click count threshold. |
| `--rage-click-timeframe-seconds N` | Override the time window. |
| `--rage-click-ignore-selector CSS` | Add a selector to the ignore list (repeatable). |
| `--enable-dead-click` | Opt in to dead-click detection. |
| `--dead-click-time-window-ms MS` | How long to wait for DOM/network response. |
| `--dead-click-ignore-url URL` | Ignore dead clicks on these URLs (repeatable). |
| `--enable-error-click` | Opt in. |
| `--error-click-time-window-ms MS` | How long after click to watch for errors. |
| `--error-click-ignore-url URL` | Ignore on these URLs (repeatable). |
| `--enable-thrashed-cursor` | Opt in. |
| `--thrashed-cursor-threshold FLOAT` | Score threshold (0–1). Lower = more sensitive. |
| `--thrashed-cursor-throttle-ms MS` | Sample interval (default 16ms). |

## Tuning recipes

**Calm app with deliberate UX (e.g., dashboard)**: keep defaults; rage-click is
sufficient.

**Game / interactive canvas / drawing tool**: disable rage-click on the
interactive area, keep it elsewhere:
```yaml
rage_click:
  enabled: true
  ignore_selectors:
    - "#game-area"
    - ".drawing-canvas"
```
Or disable thrashed-cursor on the same paths via `ignore_urls`.

**E-commerce checkout**: turn on dead-click and error-click — these often
correlate with conversion-impacting bugs:
```yaml
dead_click:
  enabled: true
  time_window_ms: 800
error_click:
  enabled: true
  time_window_ms: 1500
```

**Marketing site / multi-page app**: rage-click + dead-click, leave error-click
and thrashed-cursor off (low signal-to-noise).

## Span attributes

Each signal emits a span on the `frustration` instrumentation with the
following attributes:

| Attribute | Type | Notes |
|-----------|------|-------|
| `frustration_type` | string | `rage` / `dead` / `error` / `thrash` |
| `interaction_type` | string | `click` / `cursor` (etc.) |
| `target_xpath` | string | XPath of the element involved |
| `target_text` | string | Element text, subject to your privacy settings |

Thrashed-cursor additionally emits:

| Attribute | Type | Notes |
|-----------|------|-------|
| `thrashing_score` | number | 0.0–1.0; how severe the thrashing was |
| `pattern_description` | string | Short summary of detected movement |

## Dashboards + detectors

The skill's `handoff-dashboards.spec.yaml` and `handoff-detectors.spec.yaml`
include starter charts and detectors keyed on `frustration_type`. After
applying them, you can:

- Chart `rate(rum.frustration.count)` filtered by `frustration_type=rage` per
  app to spot UX regressions release-over-release.
- Detect `rate(rum.frustration.count) > 10/min for 5m` per route to alert on
  sudden spikes that indicate a broken interaction.
- Use Tag Spotlight in the RUM UI to drill from a frustration span into the
  exact session that triggered it (and from there into Session Replay if
  enabled).
