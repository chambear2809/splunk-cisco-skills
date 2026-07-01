---
name: widefield-google-secops-setup
description: >-
  Render and validate Google SecOps ingestion, webhook/feed, parser, and
  evidence assets for WideField Security log type WIDEFIELD_SECURITY. Use when
  the user asks to ingest WideField Security into Google Security Operations,
  verify the WideField default parser, prepare feed handoffs, or collect
  parser evidence while failing closed for undocumented Google SecOps live
  feed mutation.
---

# WideField Google SecOps Setup

Render Google SecOps assets for the public `WIDEFIELD_SECURITY` parser entry.
Live feed creation is disabled until a documented Google SecOps API path is
added to `reference.md`.

## Workflow

```bash
bash skills/widefield-google-secops-setup/scripts/setup.sh --render \
  --google-secops-project example-project \
  --google-secops-region us \
  --feed-name widefield-security
```

Validate supplied evidence:

```bash
bash skills/widefield-google-secops-setup/scripts/validate.sh \
  --evidence-file ./widefield-google-secops-evidence.local.json
```

Evidence should show the feed name, log type `WIDEFIELD_SECURITY`, parser
visibility, and sample events. Validation fails closed when `--evidence-file`
is omitted, is not valid JSON, or does not contain `WIDEFIELD_SECURITY`.
`--dry-run` is the only validation mode that does not require evidence.
