---
name: splunk-cloud-data-manager-setup
description: >-
  Render, doctor, apply supported cloud-side artifacts for, and validate Splunk
  Cloud Platform Data Manager onboarding across AWS, Azure, GCP, and
  CrowdStrike with Data Manager 1.16 source coverage, HEC ACK/token guardrails,
  Data Manager-generated CloudFormation/ARM/Terraform template handling,
  provider prerequisite checks, health searches, migration warnings, and
  secret-file-only handoffs. Use when the user asks to set up Splunk Cloud Data
  Manager, onboard cloud data sources through Data Manager, validate Data
  Manager prerequisites, handle Data Manager CloudFormation or ARM or Terraform
  templates, diagnose Data Manager ingestion health, migrate Azure Event Hubs
  from MSCS, promote historical AWS S3 data, or onboard CrowdStrike FDR data.
---

# Splunk Cloud Data Manager Setup

This skill is a render-first workflow for Splunk Cloud Platform Data Manager.
It covers AWS, Azure, GCP, and CrowdStrike onboarding guardrails, but it does
not claim private Data Manager APIs or Terraform CRUD for Data Manager inputs.
When Data Manager requires UI creation, render the exact handoff and validate
the surrounding prerequisites and generated artifacts.

## Safety Rules

- Never ask for or print Splunk tokens, Azure client secrets, GCP keys,
  CrowdStrike/FDR AWS secret access keys, passwords, or API keys.
- Never pass secrets as command-line arguments or environment-variable prefixes.
- Use spec file fields such as `azure.client_secret_file`,
  `gcp.json_key_file`, `crowdstrike.aws_access_key_id_file`, and
  `crowdstrike.aws_secret_access_key_file`.
- Reject specs that contain raw `password`, `secret`, `token`, `api_key`,
  `access_key`, or `private_key` values unless the field name ends in `_file`
  or `_path`.
- Do not invent Data Manager REST endpoints or Terraform resources. Splunk
  Cloud input creation remains a UI handoff unless Splunk publishes a supported
  API.

## Workflow

1. Copy or adapt `template.example` with only non-secret values and secret file
   paths.
2. Render a plan:

   ```bash
   bash skills/splunk-cloud-data-manager-setup/scripts/setup.sh \
     --phase render \
     --spec skills/splunk-cloud-data-manager-setup/template.example
   ```

3. Review `splunk-cloud-data-manager-rendered/`, especially
   `coverage-report.json`, `apply-plan.json`, provider runbooks, and
   `doctor-report.md`.
4. Run offline validation:

   ```bash
   bash skills/splunk-cloud-data-manager-setup/scripts/validate.sh
   ```

5. Apply only supported user-supplied or Data Manager-downloaded artifacts:

   ```bash
   bash skills/splunk-cloud-data-manager-setup/scripts/setup.sh \
     --phase apply \
     --spec my-data-manager.yaml \
     --accept-apply
   ```

## Phases

- `render` - default. Writes deterministic artifacts and never mutates.
- `doctor` - render plus prioritized issue/fix report.
- `status` - summarizes rendered status commands and health checks.
- `apply` - requires `--accept-apply`, a fresh apply plan, and enabled
  Data Manager-generated artifact paths.
- `validate` - checks rendered artifacts and policy guardrails.
- `all` - render, doctor, validate.

## What It Renders

Under `splunk-cloud-data-manager-rendered/`:

- `README.md` - operator summary and safe next commands.
- `coverage-report.json` - `ui_handoff`, `artifact_validate`,
  `artifact_apply`, `splunk_validate`, `cloud_validate`, `handoff`, or
  `not_applicable` for every covered feature.
- `apply-plan.json` - apply ordering, required accept gates, and artifact paths.
- `doctor-report.md` - prioritized readiness and drift findings.
- `health-searches.spl` - source-type/index searches for post-onboarding checks.
- `provider-runbooks/` - AWS, Azure, GCP, CrowdStrike, HEC, source catalog, and
  migration runbooks.
- `scripts/` - validation/apply wrappers for Data Manager-generated
  CloudFormation, ARM, and Terraform artifacts.

## References

Read only the reference needed for the user request:

- [reference.md](reference.md) - complete workflow, source coverage, and guardrails.
- [references/aws.md](references/aws.md) - AWS CloudFormation, StackSets, S3,
  custom logs, Organizations/OUs, and S3 Promote.
- [references/azure.md](references/azure.md) - Azure ARM, Entra ID, Activity
  Logs, Event Hubs, Monitor, and MSCS migration.
- [references/gcp.md](references/gcp.md) - GCP Terraform templates, Pub/Sub,
  Dataflow, project/folder/org overlap checks, and edit/delete.
- [references/crowdstrike.md](references/crowdstrike.md) - CrowdStrike FDR
  S3/SQS onboarding, event families, and delete cleanup.
- [references/source-catalog.md](references/source-catalog.md) - official source
  type and HEC ACK/token catalog.
- [references/iac-and-terraform.md](references/iac-and-terraform.md) - what is
  supported vs adjacent Terraform.
- [references/research-ledger.md](references/research-ledger.md) - source URLs
  used to build this skill.
