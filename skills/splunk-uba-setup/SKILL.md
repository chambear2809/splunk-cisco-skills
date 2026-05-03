---
name: splunk-uba-setup
description: >-
  Use when validating Splunk UBA / UEBA readiness, optional UBA Kafka ingestion
  app placement, and migration guidance to Splunk Enterprise Security Premier
  UEBA without installing standalone UBA servers.
---

# Splunk UBA Setup

Use this skill when the user asks for **Splunk User Behavior Analytics (UBA)** or
UEBA readiness. Standalone Splunk UBA is end-of-sale and this repo must not
pretend to automate a supported UBA server installation. This skill provides:

- Existing UBA/UEBA support-app and index validation
- Optional Splunk UBA Kafka Ingestion App install (`Splunk-UBA-SA-Kafka`,
  Splunkbase `4147`)
- Explicit end-of-sale/end-of-support reporting
- Migration guidance toward Splunk Enterprise Security Premier UEBA

## Workflow

1. Read this file and `reference.md`.
2. Start with a dry run:

   ```bash
   bash skills/splunk-uba-setup/scripts/setup.sh --dry-run --json
   ```

3. Validate an existing UBA/UEBA integration:

   ```bash
   bash skills/splunk-uba-setup/scripts/validate.sh
   ```

4. Install the UBA Kafka ingestion app only when the deployment still requires
   it and the package is available:

   ```bash
   bash skills/splunk-uba-setup/scripts/setup.sh --install-kafka-app
   ```

5. Use local package install for restricted or pre-downloaded packages:

   ```bash
   bash skills/splunk-uba-setup/scripts/setup.sh \
     --install-kafka-app \
     --source local \
     --file /path/to/splunk-uba-kafka-ingestion-app.tgz
   ```

## Guardrails

- Do not install standalone UBA servers from this skill.
- Do not claim that UBA is newly purchasable. Report the published standalone
  UBA end-of-sale and end-of-support dates.
- Prefer ES Premier UEBA migration guidance for new work.
- Treat Kafka app installation as optional and legacy/readiness-focused.
