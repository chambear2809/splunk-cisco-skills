# RUM-to-APM Trace Linking

Splunk Browser RUM links front-end traces (page loads, user interactions,
fetch / XHR calls) to backend APM traces via the `Server-Timing` HTTP response
header. When the linkage is in place, you can click a slow XHR span in the RUM
UI and jump directly to the matching backend trace in APM.

## How it works

The Browser RUM agent watches every fetch / XHR response for a header of the
shape:

```
Server-Timing: traceparent;desc="00-<trace_id>-<span_id>-01"
```

`<trace_id>` is a 32-hex-character W3C Trace Context trace ID; `<span_id>` is
a 16-hex-character span ID. When the agent sees a matching header, it
correlates the RUM span for that fetch / XHR with the backend trace identified
by `<trace_id>`. Subsequent calls in the same trace appear as a single
end-to-end timeline in the Splunk UI.

The exact regex the agent uses:

```
00-([0-9a-f]{32})-([0-9a-f]{16})-01
```

Headers with values that don't match are ignored. Backends that emit malformed
`Server-Timing` headers are NOT a problem — RUM just skips the linkage.

## Backends that emit Server-Timing automatically

The Splunk distributions of OpenTelemetry already emit `Server-Timing` for
every traced response on these languages:

- Java (Splunk Distribution of OpenTelemetry Java)
- Node.js (Splunk Distribution of OpenTelemetry Node.js)
- Python (Splunk Distribution of OpenTelemetry Python, with `splunk-py-trace`)
- .NET (Splunk Distribution of OpenTelemetry .NET)

If your backend services are instrumented via the
[splunk-observability-k8s-auto-instrumentation-setup](../../splunk-observability-k8s-auto-instrumentation-setup/SKILL.md)
skill, `Server-Timing` is on by default for all four. You don't need to do
anything else.

## Manual emission

For backends that aren't instrumented (Go, Rust, anything custom), emit the
header manually from your trace context:

### Go (otel-go)

```go
import (
    "go.opentelemetry.io/otel/trace"
)

func serverTimingMiddleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        spanCtx := trace.SpanContextFromContext(r.Context())
        if spanCtx.IsValid() {
            traceID := spanCtx.TraceID().String()
            spanID := spanCtx.SpanID().String()
            w.Header().Set("Server-Timing",
                fmt.Sprintf("traceparent;desc=\"00-%s-%s-01\"", traceID, spanID))
        }
        next.ServeHTTP(w, r)
    })
}
```

### Rust (tracing-opentelemetry)

```rust
use opentelemetry::trace::TraceContextExt;
use tracing::Span;

fn add_server_timing(response: &mut Response) {
    let span = Span::current();
    let ctx = span.context();
    let span_ref = ctx.span();
    let span_ctx = span_ref.span_context();
    if span_ctx.is_valid() {
        let header = format!(
            "traceparent;desc=\"00-{}-{}-01\"",
            span_ctx.trace_id(), span_ctx.span_id()
        );
        response.headers_mut().insert("server-timing", header.parse().unwrap());
    }
}
```

## CORS considerations

When the front-end and back-end are on different origins (e.g.
`app.example.com` calling `api.example.com`), the browser blocks the front-end
JavaScript from reading the `Server-Timing` header by default. Add it to the
exposed-headers list:

```
Access-Control-Expose-Headers: Server-Timing
```

Without this header, the RUM agent silently fails to link the trace. The
backend response still carries `Server-Timing`, the browser just hides it
from JS.

## Browser support

| Browser | Page-load linking | XHR/fetch linking |
|---------|-------------------|-------------------|
| Chrome | Yes | Yes |
| Edge | Yes | Yes |
| Firefox | Yes | Yes |
| Safari (desktop and iOS) | **No** | Yes |

Safari's Resource Timing API does not expose `Server-Timing` for the document
load, so page-load → backend-trace linking does not work on Safari. XHR and
fetch linking works on Safari like it does everywhere else.

## Validation

The skill's validate.sh has a live probe:

```bash
bash splunk-observability-k8s-frontend-rum-rendered/scripts/validate.sh \
  --live --check-server-timing https://api.example.com/health
```

The probe runs `curl -fsSI <url>` and greps for `Server-Timing.*traceparent`
in the response headers. When the header is missing, validate.sh:

1. Returns exit code 2.
2. Writes `splunk-observability-k8s-frontend-rum-rendered/handoff-auto-instrumentation.sh`
   pointing the operator at the backend instrumentation skill.
3. Logs the probe URL so the operator can re-run after fixing.

When the header is present, validate.sh logs `OK` and exits 0 without
touching the handoff file.

## Common failure modes

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `Server-Timing` present in `curl` but RUM still doesn't link | CORS not allowing the header | Add `Access-Control-Expose-Headers: Server-Timing` |
| `Server-Timing` value parses but doesn't match the regex | Custom format (e.g., `traceparent;desc=01-<...>`) | Use exact `00-<trace_id>-<span_id>-01` shape |
| Linkage works for some routes, not others | Some backend handlers bypass the OTel middleware | Audit middleware ordering; ensure tracing wraps the response writer |
| Linkage works on Chrome, not Safari for page loads | Known Safari limitation | XHR/fetch links still work; document the Safari gap to your team |
| RUM session shows linkage but APM trace UI is empty | Backend trace didn't sample (head-based sampling at 1%) | Increase backend sampling for the test path or use traceidratio at the gateway |
