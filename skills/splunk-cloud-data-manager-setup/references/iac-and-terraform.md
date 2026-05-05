# IaC And Terraform Reference

## Supported Data Manager Artifact Paths

- AWS: validate Data Manager-generated CloudFormation or StackSet templates.
  The generated wrapper can apply a single CloudFormation stack. StackSet
  execution is a handoff because deployment targets, permission mode, and
  Organizations scope must be reviewed by the operator.
- Azure: validate/apply Data Manager-generated ARM templates, with `what-if`
  preview first.
- GCP: validate/apply/destroy Data Manager-generated Terraform templates.

## Adjacent Terraform

The Splunk Cloud Platform Terraform provider `splunk/scp` can help with
adjacent prerequisites where the provider supports them, such as indexes, HEC
tokens, roles, and IP allowlists. It must not be represented as Data Manager
input CRUD.

Community Firehose-to-Splunk modules are adjacent custom ingestion patterns,
not Data Manager modules. Render them only as an explicit handoff when the user
asks for a non-Data-Manager path.
