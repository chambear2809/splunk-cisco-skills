# Galileo validation and rollback

## Contents

- [Preflight](#preflight)
- [Canary and real request](#canary-and-real-request)
- [Galileo readback](#galileo-readback)
- [Cutover evidence and key finalization](#cutover-evidence-and-key-finalization)
- [Rollback](#rollback)

## Preflight

1. Confirm the user-provided Galileo instance and `/v2/healthcheck` route.
2. Resolve immutable project and Log stream IDs using
   `skills/galileo-lemonade-instrumentation-setup/scripts/galileo_target_discovery.py`;
   when lifecycle creation or a project-scoped runtime key is required, use
   the phased `galileo_bootstrap_transaction.py` workflow in
   [runtime-credentials.md](runtime-credentials.md). It stops before old-key
   revocation.
3. Confirm protected API-key file ownership/mode without reading it to output.
4. Validate the staged collector config with the exact installed binary.
   Production validation must include `--production`, `--queue-policy
   persistent`, `--destination-fingerprint`, the matching fingerprinted
   `--queue-storage-directory`, and `--galileo-proxy-url` matching the rendered
   exporter and runtime environment. Protected tinyproxy binary/config/filter
   evidence must match the installed files, and bounded allow/deny CONNECT
   probes must pass without any credential. The environment endpoint, expected
   origin, selectors, destination fingerprint, queue path, and proxy must all
   agree. For `server-fanout`, also document and pass
   `--allow-server-shared-receiver`.
5. Record the existing Splunk trace exporter counters and a Splunk readback
   baseline before adding Galileo.

## Canary and real request

Run `send_galileo_canary.py --mode server` for `server-fanout` or its default
client mode for the dedicated 14318 receiver. Record its unique trace ID,
name, and `CREATED_AFTER` value. The canary includes non-secret `galileo.*`
route-override probes; debug/pre-export evidence must show that the final route
guard removed them. Then:

- confirm receiver accepted count increased;
- for `server-fanout`, confirm Splunk and Galileo exporter sent counts
  increased independently;
- for default `client-fanout`, confirm only the Galileo exporter increments for
  the synthetic client canary, then confirm native Splunk export still
  increments for the real Lemonade request;
- use exact v0.156 metrics rather than assuming a generic retry/drop counter:
  `receiver_accepted`, `receiver_failed`, `receiver_refused`, `exporter_sent`,
  `exporter_send_failed`, `exporter_enqueue_failed`, queue size/capacity, and
  in-flight requests;
- inspect collector logs for 401, 404, 415, and 422 responses;
- remember that a collector receiver response cannot expose a downstream
  Galileo `partialSuccess` body.

Capture deterministic before/after evidence without exposing exporter URLs or
response bodies:

```bash
python3 skills/lemonade-splunk-otel/scripts/collector_evidence.py \
  --receiver-label otlp/lemonade_galileo_client \
  --exporter-label otlp_http/galileo_lemonade > /tmp/galileo-before.json

python3 skills/lemonade-splunk-otel/scripts/collector_evidence.py \
  --receiver-label otlp/lemonade_galileo_client \
  --exporter-label otlp_http/galileo_lemonade \
  --before /tmp/galileo-before.json > /tmp/galileo-after.json
```

Use the exact labels observed in the target collector. The helper accepts only
loopback health/metrics URLs, disables ambient proxies and redirects, and emits
only allowlisted metrics.

Run one real non-sensitive Lemonade chat request. For streaming, include usage
when supported and consume the stream completely. Flush Lemonade at
`/internal/telemetry/flush`; force-flush/shutdown the application tracer.

## Galileo readback

Use the bounded helper with IDs and a root/user-owned `0600` API-key file:

```bash
python3 skills/galileo-lemonade-instrumentation-setup/scripts/galileo_readback.py \
  --api-base https://api.galileo.ai \
  --expected-origin https://api.galileo.ai \
  --api-key-file /secure/path/galileo_api_key \
  --api-key-header Splunk-AO-API-Key \
  --project-id PROJECT_UUID \
  --log-stream-id LOG_STREAM_UUID \
  --expected-name TRACE_NAME \
  --created-after CREATED_AFTER \
  --require-span-type agent \
  --require-span-type tool \
  --require-span-type llm \
  --forbidden-content-file /secure/path/synthetic-prompt-marker \
  --forbidden-content-file /secure/path/synthetic-output-marker \
  --require-redacted-content
```

The generated v2 API pages and the OTLP ingest guidance use different key
headers. The helper therefore requires an explicit choice: public v2 endpoint
pages currently show `Splunk-AO-API-Key`, while OTLP ingest uses
`Galileo-API-Key`. Follow the target tenant's authoritative API guidance.

The helper pins the API base to a separately supplied exact HTTPS origin,
follows bounded pagination, requires every supplied identifier, a creation-time
bound, and a complete search record. It then calls Get Trace with the returned
Galileo UUID, scans every response for the protected synthetic markers, and
emits only sanitized span-type/count/privacy-state evidence.

The API Get Trace result—not an inferred Console state—must prove the expected
hierarchy/kind and selected content policy. Content absence or a redacted
marker is a required assertion when hiding is enabled. When a signed-in browser
is actually available, separately review model, provider, token counts,
duration, status/error fields, hierarchy, and privacy in Console. If no such
browser observation occurred, report Console review as `not_observed`; never
translate API readback into a Console assertion.

Explicitly verify that Agent and Tool spans retain only constant `[REDACTED]`
input/output and tool argument/result fields, and that no `galileo.*` resource,
span, or event attribute changed the fixed project/Log stream. Live backend
readback of the expected Agent/Tool/LLM hierarchy remains a release gate even
after collector validation and counter success.

## Cutover evidence and key finalization

If a bootstrap transaction minted the runtime key, finalization requires a
fresh schema-v2 protected document based on the actual results above. Start
from `assets/galileo-bootstrap-cutover-evidence.example.json`, bind the exact
transaction/API/project/Log-stream/runtime-key IDs, and use a current UTC
timestamp. Required `true` gates are:

- runtime key installed, exact collector config validated, service active, and
  the retained rollback procedure tested;
- successful OTLP write, Galileo API trace readback, API hierarchy proof, and
  privacy assertions;
- unchanged Splunk backend readback after cutover.

The transaction accepts no claim that Console was observed. Omit
`console_review` or retain `{"status":"not_observed"}`. Store any real
signed-in browser evidence separately. Protect the cutover document as a
current-user-owned, single-link `0600` file and record it with
`record-cutover-evidence`; then run `finalize` as a distinct invocation. The
default maximum age is 900 seconds and the hard maximum is 3600 seconds.

Finalize revalidates the evidence file's path, inode, size, hash, timestamp,
and exact bindings; re-proves runtime-key scope and `log_data`; verifies a
distinct exact unscoped revoker; journals intent before revocation; deletes
only the exact old key ID through that revoker; reconciles exact absence from a
complete owner-key inventory; requires the old credential to return 401
Unauthorized from both `GET /v2/current_user` and `GET /v2/token`; and
re-proves the runtime key before `FINALIZED`. A crash or uncertain response
after deletion resumes from the journal without selecting a different key.
Neither DELETE response nor inventory absence alone proves revocation. See
[runtime-credentials.md](runtime-credentials.md) for the commands, phase table,
and the no-DELETE recovery restricted to the exact retired legacy journal
schema.

## Rollback

If Galileo export fails or Splunk regresses, restore the exact current
Collector-YAML manifest first, the runtime-bundle manifest second, the proxy
manifest third, and the queue manifest last. Validate the restored full config
with the installed binary, restart, and prove Splunk readback again.
Do not leave a failing Galileo exporter consuming queue/memory while debugging.
Restore the routing environment, proxy identity evidence, proxy config/filter,
wrapper, tinyproxy unit, and collector systemd drop-in through their owning
transactions; never edit one managed file by hand.
Never attach a queued database to a different
destination fingerprint; drain the old queue or quarantine it with the old
target configuration.

Before `OLD_KEY_REVOKED`, also run the bootstrap transaction's separate
`rollback` command. It reconciles pending POSTs through full inventories and
deletes only exact transaction-owned IDs, preserving explicitly adopted
targets. Once the old-key delete attempt is journaled as started, transaction
rollback is deliberately forbidden even if the response was uncertain; resume
`finalize` so the project-scoped runtime key is not deleted after the old key
may already be gone. Use the already-tested host configuration restoration path
while keeping that valid runtime key.
