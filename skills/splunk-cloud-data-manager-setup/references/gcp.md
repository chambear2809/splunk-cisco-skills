# GCP Data Manager Reference

GCP Data Manager coverage includes Pub/Sub, Dataflow, GCS, IAM prerequisites,
project/folder/organization onboarding, official Data Manager Terraform
templates, and edit/delete workflows.

## Guardrails

- Install Splunk Add-on for Google Cloud Platform 4.1.0 or later for CIM
  normalization.
- Enable Cloud Pub/Sub, Compute Engine, Dataflow, and IAM APIs.
- Use only Data Manager-generated Terraform templates for GCP Data Manager
  resources.
- Check project/folder/organization overlap before onboarding Data Access or
  Access Transparency logs to avoid duplicate ingestion.
- GCP edit/delete requires Terraform template steps. Cleanup cannot be paused
  or canceled once in progress.

## Artifact Handling

The renderer validates a Terraform template directory with `terraform init` and
`terraform validate`. Apply and destroy remain gated by `--accept-apply` plus
spec-level enablement.
