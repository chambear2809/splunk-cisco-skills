# WideField Google SecOps Reference

## Public Sources

- Google SecOps supported default parsers: https://docs.cloud.google.com/chronicle/docs/ingestion/parser-list/supported-default-parsers
- WideField platform page: https://www.widefield.ai/
- WideField demo room: https://www.widefield.ai/demo-room

The parser list includes WideField with log type `WIDEFIELD_SECURITY`.

## Mutation Boundary

This skill renders feed/webhook/parser intent and validates evidence. It does
not create Google SecOps feeds because this repository has not captured an
official documented API path for that exact operation. `--apply` fails closed
until a documented API path is added here.

## Validation Evidence

Evidence should include:

- Feed name and source.
- Log type `WIDEFIELD_SECURITY`.
- Parser/default-parser visibility.
- Sample normalized events or UDM search results.
- Coverage evidence for identity posture, non-human identity ownership, human
  MFA posture, connected application permission risk, AI identity access, and
  authentication/session analysis.

`validate.sh` and `setup.sh --validate` require `--evidence-file`. The file
must be valid JSON and must contain the exact `WIDEFIELD_SECURITY` marker;
missing evidence or a marker mismatch exits nonzero. Use `--dry-run` to inspect
the intended validation without supplying evidence.
