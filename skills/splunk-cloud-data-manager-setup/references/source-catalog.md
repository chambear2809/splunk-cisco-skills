# Data Manager Source Catalog

This reference mirrors the researched Data Manager 1.16 source coverage used by
the renderer. Keep detailed catalogs here, not in `SKILL.md`.

## HEC ACK Required Sources

Indexer acknowledgement is required only for:

- CloudTrail
- GuardDuty
- SecurityHub
- IAM Access Analyzer
- CloudWatch Logs

Special token names:

- `scdm-scs-hec-token` - AWS S3, Azure Event Hub, and CrowdStrike FDR.
- `scdm-scs-promote-hec-token` - AWS S3 Promote.

## AWS Source Types

These are the exact Data Manager 1.16 source types in the source-type
overview. AWS CloudWatch Logs covers several documented data sources such as
API Gateway, CloudHSM, DocumentDB, EKS, Lambda, RDS, and VPC Flow Logs.

- `aws:s3:accesslogs`
- `aws:cloudtrail`
- `aws:cloudwatch:guardduty`
- `aws:cloudwatchlogs`
- `aws:accessanalyzer:finding`
- `aws:iam:credentialreport`
- `aws:metadata`
- `aws:securityhub:finding`
- `aws:cloudfront:accesslogs`
- `aws:elb:accesslogs`

Custom CloudWatch Logs source types use the documented `aws:cloudwatchlogs:`
prefix. Custom Amazon S3 source types are user-defined through the Data
Manager custom source-type workflow and local `props.conf` / `transforms.conf`
preparation. Amazon Security Lake is not a Data Manager input catalog item in
the 1.16 manual; hand it off to the Splunk Cloud Federated Analytics / Amazon
Security Lake provider workflow.

## Azure Source Types

- `azure:monitor:aad`
- `azure:monitor:activity`
- `azure:monitor:resource`
- `mscs:azure:eventhub`

## GCP Source Types

- `google:gcp:pubsub:access_transparency`
- `google:gcp:pubsub:audit:admin_activity`
- `google:gcp:pubsub:audit:data_access`
- `google:gcp:pubsub:audit:policy_denied`
- `google:gcp:pubsub:audit:system_event`

Other Splunk Add-on for Google Cloud Platform source types are adjacent
add-on coverage, not Data Manager 1.16 source catalog entries.

## CrowdStrike Source Types

- `crowdstrike:events:sensor`
- `crowdstrike:events:external`
- `crowdstrike:events:ztha`
- `crowdstrike:inventory:aidmaster`
- `crowdstrike:inventory:managedassets`
- `crowdstrike:inventory:notmanaged`
- `crowdstrike:inventory:appinfo`
- `crowdstrike:inventory:userinfo`
