# AWS Data Manager Reference

AWS Data Manager coverage includes push-based CloudFormation/StackSet flows,
pull-based S3/SQS flows, single account, multiple accounts, Organizations/OUs,
CloudWatch Logs custom logs, Amazon S3 custom source types, and S3 Promote
historical ingestion. Amazon Security Lake is classified as a handoff to
Splunk Cloud Federated Analytics, not Data Manager.

## Guardrails

- Use only Data Manager-generated CloudFormation/StackSet templates.
- Validate templates with AWS CLI before apply. The generated wrapper applies
  single CloudFormation stacks; StackSet execution stays a handoff.
- Scope Organizations/OUs to documented supported source families and require
  an overlap check for account/input type combinations.
- For Organizations/OUs, use the documented CloudWatch Logs service families
  (API Gateway, CloudHSM, DocumentDB, EKS, Lambda, or RDS). Do not treat a
  generic `cloudwatch_logs` selector or VPC Flow Logs as automatically covered.
- CloudWatch Logs custom log groups cannot be onboarded more than once.
- Amazon S3 custom source types require index-time configuration files such as
  `props.conf` and `transforms.conf` before data starts flowing.
- S3 Promote historical jobs require Ingest Processor and ingest actions routing
  review before scheduling the job.
- Track `SplunkDMVersion` drift for StackSet resources after dataset changes.

## External Services

Provider APIs and services commonly involved include CloudFormation,
EventBridge, IAM, Kinesis Data Firehose, Lambda, CloudWatch Logs, S3, SQS,
CloudTrail, Security Hub, GuardDuty, and IAM Access Analyzer.
