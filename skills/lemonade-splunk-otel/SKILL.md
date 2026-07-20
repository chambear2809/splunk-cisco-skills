---
name: lemonade-splunk-otel
description: "Use when installing or upgrading Lemonade, checking its telemetry, configuring a loopback OTLP receiver,
  or preparing Lemonade telemetry for Splunk or Galileo fan-out. Upgrade and operate Lemonade Server on
  Debian or AMD Ryzen AI hosts, enable its native OpenTelemetry traces, and route them through the Splunk
  Distribution of the OpenTelemetry Collector with secure credentials, privacy controls, rollback, and
  backend validation."
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-07-02"
---

# Lemonade Splunk OpenTelemetry

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

- Installing or upgrading Lemonade, checking its telemetry, configuring a loopback OTLP receiver, or preparing
  Lemonade telemetry for Splunk or Galileo fan-out.
- Preview and review the lemonade splunk otel workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/lemonade-splunk-otel/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/lemonade-splunk-otel/scripts/validate.sh --help
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

Use this skill as the host and collector foundation for a Lemonade Server on
Debian or an AMD Ryzen AI developer box. It owns discovery, upgrade safety,
native telemetry, a single rendered collector configuration, validation, and
rollback. For Galileo routing and application-side agent traces, compose it
with `$galileo-lemonade-instrumentation-setup`.

The tested baseline is Lemonade v10.10 with Splunk OTel Collector v0.156 on
Linux; preserve the exact installed distro's component IDs.

Run the render/review tools with Python 3 plus PyYAML. On Debian install
`python3-yaml`; in this repository use the isolated `requirements-dev.txt`
environment (for example, `.venv/bin/python`) rather than the macOS system
interpreter. The shell entrypoints use the first `python3` on `PATH`.

Lemonade v10.10 emits OTLP **traces** for inference requests. It does not emit
OTLP logs or metrics. Journald collection is a separate, opt-in logs path.

## Safety Contract

- Discover the live service, package source, config path, collector binary,
  collector config, and bound ports before changing anything.
- Render to a staging path. Never layer a second YAML file containing pipeline
  lists over the live collector config.
- Back up the Lemonade and collector configs and record service state before
  apply. Validate with the exact installed collector binary before restart.
- Keep OTLP receivers on loopback unless an explicit network threat model and
  firewall policy authorize remote ingestion.
- Keep `telemetry.hide_inputs`, `hide_outputs`, and `hide_thinking` enabled by
  default. Disabling them is content-export approval, not a debugging toggle.
- Lemonade v10.10 can place a raw upstream/model error in span
  `status.message` even while hide flags are on. Keep the rendered conditional
  privacy transform and validate a failed non-sensitive request.
- Never place a Splunk token or Galileo key on argv, in chat, or in generated
  YAML. Source each secret into a dedicated `0600` runtime file owned by the
  service identity that reads it; use root ownership only for a root service.
  Rendering and validation reject literal credential-bearing YAML fields,
  including inherited exporter tokens and sensitive headers; use only exact
  uppercase environment placeholders.
- Use separate least-privilege Splunk organization tokens: an Ingest-scoped
  token for the Collector and an API-scoped `read_only` token for backend
  validation. Never deploy a user API session token to the Collector. Follow
  the fail-closed creation, rotation, and cutover transaction in
  [references/keychain.md](references/keychain.md); a disclosed or combined
  API-and-Ingest token is not production-ready until it is replaced and the
  old token or secret is no longer accepted.
- Do not infer success from a service restart alone. Require source, collector,
  exporter, and backend evidence.

## Workflow

1. Read [reference.md](reference.md), then load only the detailed reference
   needed for the task.
2. Inventory the host using the commands in
   [references/debian-runbook.md](references/debian-runbook.md). Confirm the
   health URL and OpenAI-compatible base URL from the live server; do not
   assume a port.
3. If upgrading, record the installed version, package candidate, APT origin,
   held packages, config checksum, and service state. Back up first and keep a
   downgrade path.
4. Configure Lemonade through `telemetry.otlp.*`; Lemonade does not consume the
   standard per-signal OTLP endpoint/protocol environment variables. Set both
   `openinference` and `otel_genai` semantics. On v10.10, after backing up the
   discovered `config.json`, the concrete CLI operation is:

   ```bash
   lemonade config set telemetry.enabled=true \
     telemetry.hide_inputs=true \
     telemetry.hide_outputs=true \
     telemetry.hide_thinking=true \
     telemetry.otlp.endpoint=http://127.0.0.1:4318/v1/traces \
     telemetry.otlp.protocol=http/protobuf \
     telemetry.otlp.semantics='["openinference","otel_genai"]'
   ```

   Verify the live snapshot through `lemonade config` or the loopback-only
   `/internal/config` endpoint without printing `telemetry.otlp.headers`.
5. Render one full collector config from the live base:

   ```bash
   bash skills/lemonade-splunk-otel/scripts/setup.sh \
     --base /etc/otel/collector/agent_config.yaml \
     --output /tmp/lemonade-agent_config.yaml \
     --deployment-environment lemonade-dev
   ```

   If a config produced by the earlier personal skill contains the known
   shared `resource/lemonade` component, the renderer fails closed. Review the
   detected shape, keep the backup, and rerun with
   `--migrate-legacy-lemonade-renderer`; unknown/conflicting shapes are never
   removed automatically. The explicit migration accepts only the exact legacy
   topology: one final processor entry in the selected `traces[/name]` pipeline
   and one final processor entry in the selected `logs[/name]` pipeline.
   Duplicate, reordered, wrong-field, metrics, foreign-pipeline, missing, or
   additional references fail closed.
   Preserve the installed distro's resource-detection component ID and
   detector configuration.

   Repeated renders recognize only this skill's exact current privacy and
   optional journald component shapes, references, and ordering. A foreign,
   partial, dangling, duplicated, reordered, or tampered managed ID fails
   closed; reconcile it from the retained source backup instead of forcing an
   overwrite. The existing privacy processor must remain referenced by the
   same selected `--traces-pipeline`; changing that selector is not an implicit
   move operation. To move it, start from the retained clean source or
   deliberately remove the previously reviewed exact managed component and
   reference, then render and validate the complete diff again.

6. Review the diff. Validate the staged file with both this skill and the exact
   installed collector binary:

   PyYAML normalizes formatting and does not preserve vendor comments. Keep the
   original backup and use the value-free semantic summary to make review
   tractable before inspecting the full diff:

   ```bash
   python3 skills/lemonade-splunk-otel/scripts/config_change_summary.py \
     --before /etc/otel/collector/agent_config.yaml \
     --after /tmp/lemonade-agent_config.yaml
   ```

   ```bash
   bash skills/lemonade-splunk-otel/scripts/validate.sh \
     --collector-config /tmp/lemonade-agent_config.yaml \
     --collector-binary /usr/bin/otelcol \
     --production
   ```

   Use `--production` for an apply candidate; it refuses to pass without an
   explicit absolute path to the exact installed collector binary. Omit it
   only for offline static inspection.

7. Apply the already-validated staged bytes with the packaged Linux/root-only
   transaction helper. Derive every path, service name, and loopback collector
   health URL from the live unit; the values below are examples:

   ```bash
   STAGED_SHA256="$(sha256sum /tmp/lemonade-agent_config.yaml | cut -d ' ' -f 1)"
   COLLECTOR_SHA256="$(sha256sum /usr/bin/otelcol | cut -d ' ' -f 1)"
   sudo python3 skills/lemonade-splunk-otel/scripts/transactional_apply.py apply \
     --staged /tmp/lemonade-agent_config.yaml \
     --live /etc/otel/collector/agent_config.yaml \
     --service splunk-otel-collector.service \
     --health-url http://127.0.0.1:13133/ \
     --expected-sha256 "$STAGED_SHA256" \
     --collector-binary /usr/bin/otelcol \
     --collector-binary-sha256 "$COLLECTOR_SHA256" \
     --state-root /var/lib/lemonade-otel-config-transactions
   ```

   Retain the returned root-only schema-v2 manifest. Before taking a snapshot,
   the helper requires `systemctl show` to resolve the exact requested service
   ID with `LoadState=loaded`, `ActiveState` exactly `active` or `inactive`, and
   `UnitFileState` exactly `enabled` or `disabled`; it rejects transitional,
   failed, runtime-only, static, alias, linked, indirect, and masked states.
   The exact `ActiveState` must agree with `systemctl is-active`. It binds the
   transaction to a hashed machine ID, exact package versions, the supplied
   collector binary path, device/inode, and hash, and a hash-only systemd
   unit/drop-in fingerprint. It snapshots exact live bytes, ownership, mode,
   ACL/SELinux/extended attributes, and exact service state before atomically
   installing and restarting. An explicit later rollback is:

   ```bash
   sudo python3 skills/lemonade-splunk-otel/scripts/transactional_apply.py \
     restore --manifest /absolute/root-only/transaction/manifest.json
   ```

   Explicit restore is resumable and accepts only the exact staged hash or the
   exact backup hash for the current transaction generation. It fails closed
   for unknown config drift, a stale/copied manifest, host/package/binary/unit
   drift, or a missing exact loaded service. A root-only current-generation
   pointer and phase journal survive abrupt termination; retry the same restore
   after an interrupted rollback. A new apply refuses to supersede an
   incomplete generation. Do not bypass these gates—restore the recorded
   runtime provenance or investigate the drift. Automatic in-process recovery
   may overwrite an indeterminate partial install with the verified backup.

   The helper rechecks packages, collector binary identity/hash, unit
   fingerprint, and exact service state before install, before and after
   restart, before and after health, and immediately before the terminal
   `applied` checkpoint. If one of those checks drifts after config replacement,
   it restores only the verified prior config bytes, performs no rollback
   service actions, records `recovery_required`, and exits with sanitized
   evidence. Restore the recorded package/binary/unit provenance and retry the
   same manifest; do not start another apply.

   Require the live config, state root, collector binary, systemd unit, and
   their ancestors to be root-owned and not group/other-writable. The staged
   input may be operator-owned, but it must remain the same inode and hash
   through the mutation boundary. If ACL, SELinux, or extended attributes
   cannot be read and restored exactly, the helper stops before replacement.

   This transaction covers the collector config and collector service state;
   snapshot and restore any package, systemd drop-in, or environment-file
   change separately.
8. Send the privacy-safe canary, run a real non-sensitive Lemonade completion,
   flush `/internal/telemetry/flush`, then perform the validation ladder and
   organization-bound, all-segment Splunk APM readback in
   [references/validation.md](references/validation.md). Use a separate
   protected API-scoped read token; the Collector ingest token is not a
   backend-read credential.

## Native Telemetry Settings

Use the live Lemonade configuration mechanism discovered on the host. The
equivalent settings are:

```yaml
telemetry:
  enabled: true
  hide_inputs: true
  hide_outputs: true
  hide_thinking: true
  otlp:
    endpoint: http://127.0.0.1:4318/v1/traces
    protocol: http/protobuf
    semantics: [openinference, otel_genai]
```

Lemonade has one native OTLP endpoint and creates a new root trace for every
request. It does not extract W3C `traceparent`, so its spans cannot join a
caller's agent trace without source changes.

## Delegations

- Fresh or fleet collector installation: use
  `$splunk-observability-otel-collector-setup`.
- Galileo project/Log stream lifecycle and tenant readiness: use
  `$galileo-platform-setup`.
- Galileo fan-out, source-selection, agent instrumentation, and readback: use
  `$galileo-lemonade-instrumentation-setup`.

## Completion Gate

Report the Lemonade version and health, privacy flags, receiver bind address,
collector validation, exact accepted/failed/refused and
sent/send-failed/enqueue-failed deltas, queue/in-flight state, Splunk readback,
and the retained transaction manifest or tested restore artifact. Never report
backend delivery from collector counters alone.
