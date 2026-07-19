# Cisco DefenseClaw Deskside Setup Reference

Read [SKILL.md](SKILL.md) first. This index summarizes the bundled operator
entry points and the evidence required to complete the workflow.

## Bundled entry points

- `scripts/setup.sh` performs read-only preflight by default. `--apply` requires
  an explicit DefenseClaw release, a pinned SSH `known_hosts` file, and any
  additional mutation acknowledgements shown by `--help`.
- `scripts/validate.sh` checks the remote DefenseClaw configuration, Lemonade's
  stable loopback API, connector health, and the expected guardrail mode.

## Stable defaults

- Lemonade management origin: `http://127.0.0.1:13305`
- OpenAI-compatible model API: `http://127.0.0.1:13305/api/v1`
- Model registration: `Qwen3.6-27B-GGUF`
- Initial guardrail mode: `observe`

Backend model ports are dynamic and must not be written into DefenseClaw or
Codex configuration. Keep both Lemonade endpoints on loopback.

## Completion evidence

Record the resolved immutable DefenseClaw release, SSH host-key fingerprint,
selected model, stable endpoint, scanner and rule-pack health, Codex connector
health, and validation output for the expected guardrail mode. Enabling
`action` mode requires a clean observe-mode Codex canary and a separate,
explicit apply.
