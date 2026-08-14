---
name: galileo-lemonade-instrumentation-setup
description: "Use when adding Galileo OTLP fan-out to a Lemonade collector, capturing agent/workflow/tool traces
  around Lemonade, avoiding duplicate LLM records, or validating privacy-safe Galileo ingestion from an
  AMD Ryzen AI host. Instrument Lemonade Server inference and OpenAI-compatible calling applications for
  Galileo Observe while preserving Splunk OpenTelemetry delivery, privacy policy, rollback, and end-to-end
  readback."
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-07-02"
---

# Galileo Lemonade Instrumentation Setup

## Prerequisites

| Tool or access | Purpose | Verify |
|---|---|---|
| Bash and Python 3 | Run bundled setup and validation helpers | `bash --version && python3 --version` |
| Required product/platform access | Inspect or configure the selected target | Complete the documented preflight |
| Credential files for live modes | Keep secrets out of chat | Verify paths only |

## Workflow Overview

```text
┌───────────┐   ┌───────────────┐   ┌───────────────┐   ┌─────────────────┐
│ Preflight │ → │ Render/review │ → │ Apply/handoff │ → │ Validate evidence │
└───────────┘   └───────────────┘   └───────────────┘   └─────────────────┘
```

## When to Activate

- Adding Galileo OTLP fan-out to a Lemonade collector, capturing agent/workflow/tool traces around Lemonade,
  avoiding duplicate LLM records, or validating privacy-safe Galileo ingestion from an AMD Ryzen AI host.
- Preview and review the galileo lemonade instrumentation setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/galileo-lemonade-instrumentation-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/galileo-lemonade-instrumentation-setup/scripts/validate.sh --help
```

Expected output: offline, live, and completion options are displayed when the
skill supports them; help exits without mutation.

## Troubleshooting

| Issue | Cause | Resolution |
|---|---|---|
| Preflight fails | A required tool or access path is missing | Resolve it before rendering or applying |
| Rendered assets are incomplete | Required non-secret inputs are absent | Complete intake and render again |
| Apply is blocked | Review, credentials, or explicit acceptance is missing | Use the documented handoff |
| Validation is incomplete | Live evidence is unavailable | Record the gap and keep completion open |

## Purpose

Use this skill after `$lemonade-splunk-otel` has established a healthy,
privacy-safe Lemonade-to-Splunk trace path. It adds Galileo in one of two
explicit modes and proves delivery by backend readback.

The tested baseline is Lemonade v10.10 with Splunk OTel Collector v0.156;
Galileo SaaS and Enterprise still require an exact tenant intake endpoint.
Run the tools from an isolated Python environment containing
`requirements-dev.txt` (PyYAML 6.x). Rendering is safe offline; production
validation also requires the exact installed collector binary.

This skill does **not** treat Lemonade's native inference span as a complete AI
agent trace. Lemonade v10.10 creates one root SERVER span per request, does not
extract `traceparent`, and has no workflow/tool hierarchy.

## Required Intake

Ask for and record the exact Galileo instance console URL. A copied console
link may include a navigation route after the host. Validate that exact link
with `--galileo-console-url`, but pass only its reported HTTPS origin to
`$galileo-platform-setup`. For example,
`https://console.example.invalid/tenant-navigation` normalizes to
`https://console.example.invalid/` for endpoint derivation. Treat the
path as navigation context; never infer a project or Log stream from it.
The demo-v2 deployment used by the production example starts at
`https://console.demo-v2.galileocloud.io/`; still require and validate the
operator's full navigation URL instead of silently assuming that instance.

Resolve the API base, exact OTLP traces endpoint, project, and Log stream
independently. The renderer reports an endpoint candidate but keeps the
runtime value in `GALILEO_OTLP_TRACES_ENDPOINT` until tenant validation.

## Choose One Galileo Source

| Requirement | Mode | Galileo receives | Privacy consequence |
|---|---|---|---|
| No application change; model/latency/token metadata | `server-fanout` | Lemonade's native LLM root spans | With Lemonade hide flags on, input/output/thinking stay `[REDACTED]`; content evaluators are limited. |
| Agent, workflow, tool, session, async, or selective evaluation context | `client-fanout` | Caller-side OpenInference/OTel spans, Galileo-only by default | Recommended for actual agent observability. Native Lemonade remains redacted and Splunk-only. |
| Remove Galileo routing without disturbing Splunk | `splunk-only` | Nothing | Rollback/render cleanup mode. |

Do not send both native and caller-instrumented LLM spans to the same Galileo
Log stream. They have unrelated trace IDs and appear as duplicate observations.
If temporary comparison is required, use separate Log streams and label it.

Direct Lemonade-to-Galileo is technically possible but is not the default: the
server has one OTLP destination, so it displaces Splunk and exposes the
Galileo key to the Lemonade service.

## Safety Contract

- Validate the exact Galileo console URL, normalize a copied navigation link
  to its origin, and do not assume public Galileo Cloud.
- Use `$galileo-platform-setup` for tenant readiness and project/Log stream
  lifecycle. Prefer immutable project and Log stream IDs after discovery.
- Require the exact tenant-supported `traces_endpoint`. Current Galileo docs
  show both `/otel/v1/traces` for raw OTLP POST and `/otel/traces` for several
  exporter/SDK integrations. Do not derive one from the client type or let the
  collector append a path.
- Because Collector v0.156 can forward headers across redirects, pin
  `GALILEO_EXPECTED_ORIGIN` and route only the Galileo exporter through the
  dedicated loopback allow-list proxy. Splunk exporters stay direct. Production
  must validate proxy identity, hashes, permissions, and allow/deny probes
  exactly as defined in
  [references/proxy-bundle-transaction.md](references/proxy-bundle-transaction.md).
- Use the current collector component type `otlp_http`, not legacy
  `otlphttp`. This skill names its instance `otlp_http/galileo_lemonade` so it
  cannot overwrite another application's Galileo exporter.
- Keep Galileo credentials in a dedicated service-user-owned `0600` file
  (root-owned only when the collector runs as root).
  Generated YAML contains only `${env:...}` placeholders.
- When bootstrapping a project-scoped runtime key, use the phased transaction,
  protected secret files, private journal, separate revoker, and post-cutover
  evidence gates in
  [references/runtime-credentials.md](references/runtime-credentials.md).
  Bootstrap must stop at `RUNTIME_KEY_CREATED`; never revoke the old key in the
  same invocation.
- Use `GALILEO_API_KEY_FILE` with the packaged collector runtime wrapper. Do
  not source a plaintext key into an interactive shell or store it in the
  non-secret collector environment file.
- Render one complete config from the live base, review its diff, validate with
  the exact installed collector binary, back up, then apply transactionally.
- Keep both Lemonade and client OTLP receivers loopback-bound.
- Treat `service.name` filtering as classification, not authentication. Use
  `server-fanout` only within a loopback/single-host trust boundary and accept
  its shared-receiver replay risk explicitly during production validation.
- Use the persistent Galileo queue for production. The memory queue is an
  accepted-loss development option and cannot pass `--production` validation.
- Bind each persistent queue to the validated destination fingerprint; never
  reuse it for another destination. Follow
  [references/queue-directory-transaction.md](references/queue-directory-transaction.md).
- Delete every `galileo.*` resource, span, and event attribute immediately
  before the Galileo exporter so in-band project, Log stream, experiment, or
  dataset fields cannot override the fixed exporter headers.
- Never disable content hiding without explicit approval of every backend that
  will receive the affected pipeline.

## Workflow

1. Read [reference.md](reference.md), then load the architecture, application,
   or validation reference required by the chosen mode.
2. Run `$lemonade-splunk-otel` discovery and confirm the existing Splunk path,
   privacy flags, native trace pipeline name, collector config, and receiver.
3. Run `$galileo-platform-setup` readiness for the user-confirmed instance.
   Put the existing bootstrap key in a protected file without printing it and
   identify its exact API-key ID. For read-only inventory, resolve immutable
   project and Log stream IDs without creating objects:

   ```bash
   python3 skills/galileo-lemonade-instrumentation-setup/scripts/galileo_target_discovery.py \
     --api-base "$GALILEO_API_BASE" \
     --api-key-file "$GALILEO_API_KEY_FILE" \
     --api-key-header Splunk-AO-API-Key
   ```

   Filter with exact `--project-name` or `--project-id` when the tenant has
   many projects. Current v2 project/read APIs document
   `Splunk-AO-API-Key`; OTLP ingest separately uses `Galileo-API-Key`.
   Confirm the selected Log stream before rendering.

   When the target or project-scoped runtime key must be created, use the
   phased bootstrap transaction in
   [references/runtime-credentials.md](references/runtime-credentials.md).
   Existing targets require explicit adoption, preferably by exact IDs. The
   default candidate role is `annotator`; it is accepted only if a live API
   probe proves exact project-only visibility and `log_data`. If that probe
   fails, roll back the exact owned key and start a new transaction before
   trying `editor`; do not claim either role is least privilege without the
   live permission proof.
4. State the selected Galileo source and content policy before rendering.
5. With the confirmed endpoint, expected origin, and exactly one selector pair
   set in the protected runtime environment, calculate the non-secret
   destination fingerprint. This command emits only the lowercase digest and
   does not require or print the API key:

   ```bash
   python3 skills/galileo-lemonade-instrumentation-setup/scripts/collector_runtime_wrapper.py \
     --print-destination-fingerprint
   ```

   Record it as `GALILEO_DESTINATION_FINGERPRINT`, and set
   `GALILEO_QUEUE_STORAGE_DIRECTORY` to a new private directory ending with
   that exact digest. Render from the existing full collector config:

   ```bash
   bash skills/galileo-lemonade-instrumentation-setup/scripts/setup.sh \
     --galileo-console-url "$GALILEO_CONSOLE_URL" \
     --base /etc/otel/collector/agent_config.yaml \
     --output /tmp/lemonade-galileo-agent_config.yaml \
     --mode client-fanout \
     --routing ids \
     --galileo-proxy-url http://127.0.0.1:18888 \
     --queue-policy persistent \
     --production \
     --destination-fingerprint "$GALILEO_DESTINATION_FINGERPRINT" \
     --queue-storage-directory "$GALILEO_QUEUE_STORAGE_DIRECTORY"
   ```

6. Review the diff, then apply four independently journaled layers in dependency
   order: create the destination-fingerprinted directory with
   `transactional_queue_directory.py`; install and probe the dedicated
   tinyproxy package/config/filter/unit with `transactional_proxy_bundle.py`;
   render protected proxy identity evidence from those installed assets; and
   install the routing environment, evidence, wrapper, key, and drop-in with
   `transactional_runtime_bundle.py`. Follow
   [references/queue-directory-transaction.md](references/queue-directory-transaction.md),
   [references/proxy-bundle-transaction.md](references/proxy-bundle-transaction.md),
   [references/runtime-bundle-transaction.md](references/runtime-bundle-transaction.md),
   after reading the underlying credential contract in
   [references/runtime-credentials.md](references/runtime-credentials.md).
   Do not apply the collector YAML yet. Start the proxy and run the wrapper's
   `--check`; it must prove the protected assets plus credential-free live
   allow/deny probes. Then validate the staged YAML statically and with the
   installed collector:

   Use `$lemonade-splunk-otel`'s value-free `config_change_summary.py` first;
   PyYAML normalizes formatting and comments, so retain the exact source backup.

   The production validator inspects service-owned queue files and
   collector-group-readable proxy evidence. Run the command under the exact
   Collector UID, primary GID, and supplementary groups, while inheriting the
   protected systemd environment without copying secret values into argv. Do
   not run it as root: root's group set is not proof that the Collector can
   read or safely own those assets.

   ```bash
   # Execute as the discovered Collector service identity, not as root.
   bash skills/galileo-lemonade-instrumentation-setup/scripts/validate.sh \
     --collector-config /tmp/lemonade-galileo-agent_config.yaml \
     --mode client-fanout \
     --queue-policy persistent \
     --production \
     --galileo-proxy-url http://127.0.0.1:18888 \
     --destination-fingerprint "$GALILEO_DESTINATION_FINGERPRINT" \
     --queue-storage-directory "$GALILEO_QUEUE_STORAGE_DIRECTORY" \
     --collector-binary /usr/bin/otelcol
   ```

7. Back up the live collector config and service state, preserving the exact
   original command/arguments. After the three prerequisite transactions and
   service-identity validation pass, use the baseline skill's SHA-gated
   transactional apply helper for the validated YAML and restart,
   with `/etc/splunk-otel-collector/lemonade-agent-config.yaml` as the live
   config path pinned by the runtime manifest.
   The wrapper validates endpoint/origin, selectors, destination fingerprint,
   proxy assets/live probes, and queue before loading the protected key only in
   the collector child. Restore the collector YAML transaction immediately if
   Splunk regresses, then restore the exact Collector YAML manifest, runtime
   manifest, proxy manifest, and queue manifest in that reverse order. Queue
   restore is last and quarantines nonempty or uncertain data; do not roll back
   only one proxy/runtime file or delete a queue database manually.
8. For `client-fanout`, adapt
   `skills/galileo-lemonade-instrumentation-setup/assets/lemonade_openinference_client.py`.
   It sends to the dedicated
   loopback receiver and keeps Galileo credentials out of the application.
   Install its pinned requirements in an isolated environment, then run
   `lemonade_openinference_client.py --check` under the application identity
   before sending the real canary.
9. Send the synthetic canary through the receiver selected by the mode. A
   receiver success is only pipeline evidence; continue to Galileo readback.
10. Follow [references/validation.md](references/validation.md), including a
    real non-sensitive Lemonade request, collector counter deltas, Galileo API
    trace/hierarchy readback, privacy assertions, and unchanged Splunk backend
    readback. Perform Console trace-shape review only when a signed-in browser
    is actually available, and report its absence truthfully.
11. Build a fresh schema-v2 cutover document from the actual host, Galileo API,
    and Splunk backend results. Record it with the transaction's
    `record-cutover-evidence` command. Omit `console_review` or record only
    `{"status":"not_observed"}`; any signed-in UI review is separate evidence.
12. In a distinct invocation, run `finalize` with the same protected bootstrap
    file plus a distinct protected unscoped revoker file and its exact key ID.
    It revalidates the evidence and runtime key, verifies that the revoker is
    neither the old nor runtime key, revokes only the bound old key ID through
    that revoker, reconciles full-inventory absence, requires the old key to
    return 401 Unauthorized from both `/v2/current_user` and `/v2/token`,
    rechecks the runtime key, and reaches `FINALIZED`. Before revocation,
    `rollback` deletes only exact transaction-owned IDs and preserves adopted
    targets. The separately documented `reconcile-legacy-revocation` command
    is only for the exact retired, already-started self-delete journal schema;
    it performs no DELETE and must never replace the fresh revoker policy.

## Rendered Collector Shapes

`server-fanout` leaves the shared native `traces` pipeline's exporters
unchanged and adds `traces/lemonade_galileo_server`. The new branch shares the
reviewed receiver set but fail-closed filters on Lemonade's native
`service.name=lemonade-server` before the Galileo-only exporter and preserves
the baseline Lemonade deployment/privacy transform. The attribute filter does
not establish provenance; production validation rejects externally bound
receivers.

`client-fanout` keeps the native `traces` pipeline Splunk-only and creates:

```text
OpenAI-compatible caller
  -> 127.0.0.1:14318/v1/traces
  -> traces/lemonade_galileo_client
  -> otlp_http/galileo_lemonade
```

This default avoids duplicate LLM/cost records in both backends and permits a
caller-specific Galileo content policy. `--mirror-client-to-native-exporters`
is an explicit exception for users who want the richer caller hierarchy in
Splunk too; it requires `--allow-client-mirror` during validation and an
approved duplicate/content-handling plan.

The renderer inherits only baseline `memory_limiter`, `resource_detection`
(or `resourcedetection` when that is the live distro ID), and `batch`
processor types. Use repeated `--client-processor` only after reviewing
the component for source-specific filters, transforms, and content expansion;
validation then requires `--allow-custom-client-processors`.
Every custom processor must precede the managed client privacy transform. The
privacy transform and Galileo route guard are the final two non-batch
processors, followed only by a terminal batch suffix or direct export;
rendering and validation fail if any processor could mutate spans after them.
The managed resource processor runs after inherited resource detection and
upserts the dedicated client `service.name`; validation rejects an `insert`
action that could retain the host application's identity.

Both modes redact error status text; client mode also deletes known
content-bearing span/event attributes—including multimodal message payloads and
message-level function/tool arguments and results—while retaining roles,
models, providers, structural IDs, and content types. It deletes `user.id` and
arbitrary tags/metadata, but retains opaque `session.id` for session grouping;
never put personal data in that ID. It also redacts exception messages and
stack traces. Agent/Tool `input.value`, `output.value`, and tool call
arguments/results are restored only as the constant `[REDACTED]` after deletion
so required hierarchy fields remain without source content. Source-side
OpenInference hiding remains mandatory as defense in depth, with GenAI semantic
convention duplication explicitly disabled in the reference client.
Lemonade v10.10's native `hide_outputs` does not
cover `status.message`, so removing these transforms can expose an error that
echoes sensitive content.

The renderer strips only an exact recognized prior render before adding the
requested mode, so repeated renders and mode switches are deterministic. It
preserves unrelated components but fails closed on managed drift, foreign
references, every custom Galileo-shaped or Galileo-named exporter/route in all
modes, and any extra pipeline sharing the dedicated client receiver.

## Application Choices

- OpenInference + standard OpenAI instrumentation: preferred for sync/async,
  streaming, OTel context propagation, collector fan-out, and strong hide
  controls. The packaged client demonstrates this path.
- Galileo OpenAI wrapper: smallest synchronous change and supports
  OpenAI-compatible model servers, but captures raw input/output by default.
- Galileo OpenAI Agents tracing processor: best when the application actually
  uses OpenAI Agents and needs generations, tools, and handoffs.
- Galileo manual logger or `@log`: use for custom agent/framework semantics or
  explicit redacted fields.

Read [references/application-instrumentation.md](references/application-instrumentation.md)
before choosing a client library. Content capture is opt-in.

## Completion Gate

Report all of the following:

- chosen mode and why the other source is excluded;
- exact Galileo instance/API endpoint and project/Log stream IDs, with secrets
  omitted;
- Lemonade version, health, semantics, and privacy flags;
- collector config validation, loopback binds, service health, exact
  accepted/failed/refused and sent/send-failed/enqueue-failed deltas,
  queue/in-flight state, and unchanged Splunk readback;
- Galileo API readback proving the expected trace, Agent/Tool/LLM hierarchy,
  and privacy state. Report signed-in Console confirmation separately when it
  was actually observed; otherwise report it as not observed;
- bootstrap transaction phase and sanitized IDs, with `FINALIZED` required
  only after the separate fresh-evidence revocation gate;
- backup and tested rollback path.

Production completion still requires live Galileo backend readback of the
Agent/Tool/LLM hierarchy. Static validation, collector acceptance, and an empty
or healthy queue do not substitute for that deployment gate.

HTTP 200 alone is insufficient: OTLP responses can contain
`partialSuccess.rejectedSpans`, and collector counters do not prove backend
storage.
