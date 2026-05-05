# AWS Namespaces Catalog

Splunk Observability Cloud has built-in support for the AWS service namespaces
listed in the [supported AWS namespaces table](https://help.splunk.com/en/splunk-observability-cloud/manage-data/available-data-sources/supported-integrations-in-splunk-observability-cloud/cloud-services-aws).
Run `bash setup.sh --list-namespaces --json` to print the live list.

## Compute

`AWS/EC2`, `AWS/EC2Spot`, `AWS/AutoScaling`, `AWS/ECS`, `AWS/EKS`,
`AWS/Lambda`, `AWS/ElasticBeanstalk`, `AWS/AppStream`, `AWS/GameLift`,
`AWS/OpsWorks`, `AWS/Robomaker`.

## Storage

`AWS/EBS`, `AWS/S3`, `AWS/S3/Storage-Lens`, `AWS/EFS`, `AWS/FSx`,
`AWS/Backup`, `AWS/StorageGateway`.

## Database

`AWS/RDS`, `AWS/DynamoDB`, `AWS/ElastiCache`, `AWS/DocDB`, `AWS/Neptune`,
`AWS/Redshift`, `AWS/Cassandra` (Keyspaces; uses special-case IAM Resource
ARN list -- see `iam-permissions.md`).

## Networking

`AWS/ApplicationELB`, `AWS/NetworkELB`, `AWS/GatewayELB`, `AWS/ELB`,
`AWS/ApiGateway` (requires detailed CloudWatch metrics enabled AWS-side),
`AWS/CloudFront`, `AWS/Route53`, `AWS/GlobalAccelerator`,
`AWS/NetworkFirewall`, `AWS/NATGateway`, `AWS/VPN`, `AWS/DX`,
`AWS/NetworkFlowMonitor` (newer namespace).

## Messaging / streaming

`AWS/SQS`, `AWS/SNS`, `AWS/AmazonMQ`, `AWS/Kinesis`, `AWS/KinesisAnalytics`,
`AWS/KinesisVideo`, `AWS/Firehose`, `AWS/Kafka` (MSK).

## Containers & orchestration

`AWS/ECS`, `AWS/EKS`, `AWS/MWAA` (Apache Airflow component metrics),
`AmazonMWAA` (environment metrics).

## Security

`AWS/WAFV2`, `AWS/CertificateManager`, `AWS/ACMPrivateCA`, `AWS/KMS`,
`AWS/Inspector`, `AWS/DDoSProtection`, `AWS/CloudHSM`, `WAF` (WAF Classic).

## ML / GenAI / data

`AWS/Bedrock` (GenAI -- adds Splunk AI Infrastructure Monitoring navigators
when the four Bedrock IAM permissions are added; metrics include
`InputTokenCount`, `OutputTokenCount`, `Invocations`, `InvocationLatency`),
`AWS/SageMaker` (and the five sub-namespaces: `Endpoints`,
`InferenceComponents`, `InferenceRecommendationsJobs`, `TrainingJobs`,
`TransformJobs`), `AWS/ML`, `AWS/Lex`, `AWS/Polly`, `AWS/Translate`,
`AWS/Textract`, `AWS/ThingsGraph`.

## Analytics

`AWS/Athena`, `AWS/ElasticMapReduce`, `Glue`, `AWS/CloudSearch`,
`AWS/ES` (Elasticsearch Service).

## Other

`AWS/Lambda`, `AWS/States` (Step Functions), `AWS/SES`, `AWS/SWF`,
`AWS/SDKMetrics`, `AWS/Connect`, `AWS/Cognito`, `AWS/CodeBuild`,
`AWS/Polly`, `AWS/Translate`, `AWS/WorkMail`, `AWS/WorkSpaces`,
`AWS/IoT`, `AWS/IoTAnalytics`, `AWS/Logs` (CloudWatch Logs metadata only;
log content goes through `Splunk_TA_AWS`), `AWS/Events`,
`AWS/MediaConnect`, `AWS/MediaConvert`, `AWS/MediaPackage`,
`AWS/MediaTailor`, `MediaLive`, `AWS/TrustedAdvisor`,
`AWS/ElasticTranscoder`, `AWS/ElasticInference`, `AWS/Billing`.

## Custom (built-in support but operator-driven content)

`CWAgent` (CloudWatch Agent default; see [`SKILL.md`](../SKILL.md) for the
OTel collector alternative), `System/Linux`.

## API Gateway gotcha

`AWS/ApiGateway` charts populate only when the operator enables **Detailed
CloudWatch Metrics** on the API Gateway side. Without that, charts are
empty even though the integration is healthy. See:
https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-metrics-and-dimensions.html#api-gateway-metricdimensions
