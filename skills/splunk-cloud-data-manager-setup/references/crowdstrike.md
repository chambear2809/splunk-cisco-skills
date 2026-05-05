# CrowdStrike Data Manager Reference

CrowdStrike Data Manager coverage includes Falcon Data Replicator (FDR) data
from S3/SQS, Splunk Add-on for CrowdStrike FDR prerequisites, event selection,
and delete cleanup.

## Guardrails

- CrowdStrike Data Manager onboarding supports single accounts only.
- Sensor events are mandatory and cannot be turned off.
- Each FDR instance requires a unique AWS access key pair. Use
  `crowdstrike.aws_access_key_id_file` and
  `crowdstrike.aws_secret_access_key_file`; never put either value directly in
  the spec or command line.
- Configure SQS queue URL, visibility timeout, optional notification cutoff
  time, and default index.
- CrowdStrike batches become available after the `_SUCCESS` marker appears.
- Deleting a CrowdStrike input removes the Data Manager input and associated
  Universal Cloud Forwarder connector; already ingested data remains in Splunk.

## Event Families

Covered event families include sensor, external security events, Zero Trust
Host Assessment, aidmaster, managed asset inventory, unmanaged inventory,
application inventory, and user inventory.
