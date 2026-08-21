---
name: cisco-defenseclaw-deskside-setup
description: "Use when deploying, upgrading, configuring, or validating DefenseClaw on an AMD Ryzen AI or other
  Lemonade-backed deskside. Install or upgrade the official Cisco AI Defense DefenseClaw release on a
  Linux Lemonade deskside, select a local Qwen model, configure the stable OpenAI-compatible API, wire the
  supported Codex hook connector, and verify observe or action enforcement."
compatibility: >-
  No direct Splunk Platform runtime dependency. This workflow can be used
  alongside Splunk Cloud Platform 10.5.2605 through its documented external
  APIs or handoffs.
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-08-20"
---

# Cisco DefenseClaw Deskside Setup

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

- Deploying, upgrading, configuring, or validating DefenseClaw on an AMD Ryzen AI or other Lemonade-backed deskside.
- Preview and review the cisco defenseclaw deskside setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/cisco-defenseclaw-deskside-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/cisco-defenseclaw-deskside-setup/scripts/validate.sh --help
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

Use this skill for the native, signed Cisco release. The public Cisco release
does not publish an OCI runtime image; do not substitute a mutable third-party
container tag for the release artifacts.

## Safety Contract

- Require a pre-pinned SSH host key. The scripts use `StrictHostKeyChecking=yes`
  and never use TOFU.
- Keep the Lemonade and DefenseClaw inference endpoints on loopback. Do not add
  an API key to a local provider that does not require one.
- Use Lemonade's stable server API on port 13305. Backend ports such as 8001 or
  8002 are assigned dynamically and must not be persisted in DefenseClaw.
- Require `--replace-active-model` before replacing an already loaded Lemonade
  model. Model loading can interrupt active requests.
- Begin DefenseClaw in observe mode. Require an explicit
  `--guardrail-mode action` apply after a clean Codex canary before blocking.
- Do not place credentials in argv, chat, or generated files.

## Workflow

Run a non-mutating preflight first:

```bash
bash skills/cisco-defenseclaw-deskside-setup/scripts/setup.sh \
  --host 192.168.68.90 --user cisco
```

Apply the current Cisco release and switch Lemonade to the desired model:

```bash
bash skills/cisco-defenseclaw-deskside-setup/scripts/setup.sh \
  --host 192.168.68.90 --user cisco \
  --release latest \
  --model Qwen3.6-27B-GGUF \
  --replace-active-model --apply
```

The apply path requires an explicit release selection. Prefer a concrete version
for repeatable deployments; `--release latest` resolves it once and then uses
that immutable release tag. The vendor installer verifies release checksums.
The script waits for Lemonade's asynchronous model download, configures the
credential-free `lm_studio` compatibility adapter against
`http://127.0.0.1:13305/api/v1`, initializes Cisco's scanners and default rule
pack, and wires Codex hooks, native OTel, and notify telemetry. It pins Codex
to the Lemonade registration after connector setup so a managed config rewrite
cannot restore a different cached model. `Qwen3.6-27B-GGUF` is the registration
used by the stable API; do not persist a dynamically assigned backend port or
GGUF filename in Codex configuration.

Before changing the DefenseClaw LLM config, the script creates a timestamped
copy beside `~/.defenseclaw/config.yaml`. If a later configuration or gateway
step fails, it restores that config and reloads the previous model when it had
replaced one. Downloaded model files remain cached by Lemonade.

Validate the model endpoint, configured judge, and gateway afterward:

```bash
bash skills/cisco-defenseclaw-deskside-setup/scripts/validate.sh \
  --host 192.168.68.90 --user cisco --live --check-inference \
  --expect-mode observe
```

After a clean observe-mode Codex canary, explicitly enable enforcement:

```bash
bash skills/cisco-defenseclaw-deskside-setup/scripts/setup.sh \
  --host 192.168.68.90 --user cisco \
  --release 0.8.3 --model Qwen3.6-27B-GGUF \
  --replace-active-model --guardrail-mode action --apply

bash skills/cisco-defenseclaw-deskside-setup/scripts/validate.sh \
  --host 192.168.68.90 --user cisco --live --check-inference \
  --expect-mode action
```

Codex is a hook connector: model traffic remains direct to Lemonade while
DefenseClaw inspects prompts and lifecycle/tool events through Codex hooks. In
action mode, supported policy hits return a native deny verdict. A disabled
OpenClaw fleet uplink and closed proxy port are expected for this standalone
Codex architecture; require the sidecar API, Codex connector, guardrail, local
judge, scanners, and rule pack to be healthy instead.
