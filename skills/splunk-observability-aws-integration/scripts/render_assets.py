#!/usr/bin/env python3
"""Render Splunk Observability Cloud <-> AWS integration assets.

Reads a YAML or JSON spec (default: ``template.example``) and emits a
numbered, render-first plan tree under ``--output-dir``:

- ``README.md`` + ``architecture.mmd``
- ``00-prerequisites.md`` through ``09-handoff.md``
- ``coverage-report.json``
- ``apply-plan.json``  (idempotency keys; never holds a secret)
- ``payloads/``  (per-step request bodies; never holds a secret; admin token
   referenced as ``${SPLUNK_O11Y_TOKEN_FILE}`` only)
- ``iam/``       (per-use-case IAM JSON: foundation, polling, streams,
   tag-sync, Cassandra-special-case, GovCloud security-token)
- ``aws/``       (CloudFormation regional or StackSets stub + Splunk-side
   Terraform .tf files)
- ``scripts/``   (per-step apply drivers + cross-skill handoff drivers)
- ``state/``     (apply-state.json + idempotency-keys.json placeholders)
- ``support-tickets/``  (rendered when Splunk Support is needed)

The renderer never accepts a secret value as an argument or writes one
into any rendered file. Token files referenced by the spec are written
only as path strings (e.g. ``${SPLUNK_O11Y_TOKEN_FILE}``).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "skills" / "shared" / "lib"))
from yaml_compat import YamlCompatError, load_yaml_or_json  # noqa: E402

# ---------------------------------------------------------------------------
# Constants and tables (single source of truth shared with API clients).
# ---------------------------------------------------------------------------

SKILL_NAME = "splunk-observability-aws-integration"
API_VERSION = f"{SKILL_NAME}/v1"

# Splunk realm <-> AWS STS region mapping. Per the AWS auth & regions doc:
# https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/aws-authentication-permissions-and-regions
REALM_STS_REGION: dict[str, str] = {
    "us0": "us-east-1",
    "us1": "us-west-2",
    "us2": "us-east-1",
    "us3": "us-west-2",
    "eu0": "eu-west-1",
    "eu1": "eu-central-1",
    "eu2": "eu-west-2",
    "au0": "ap-southeast-2",
    "jp0": "ap-northeast-1",
    "sg0": "ap-southeast-1",
}

# AWS-hosted realms only. The GCP-hosted us2-gcp realm has no AWS STS region
# and cannot run the AWSCloudWatch integration. We do NOT include it here.
SUPPORTED_REALMS: tuple[str, ...] = tuple(REALM_STS_REGION)

# Splunk-side AWS account ID per realm. Used to render the IAM trust policy
# Principal. These values are returned by `POST /v2/integration` as the
# `sfxAwsAccountArn` field, and are stable per realm. We seed the map with
# values discovered against live integrations; unknown realms render the
# placeholder `${SPLUNK_AWS_ACCOUNT_ID}` so the operator pulls the live
# value from the create response.
SPLUNK_AWS_ACCOUNT_ID_PER_REALM: dict[str, str] = {
    "us1": "562691491210",  # confirmed via live discover (April 2026)
}

# AWS region inventory (16 regular + 10 optional + 2 GovCloud + 2 China).
REGULAR_REGIONS: tuple[str, ...] = (
    "ap-northeast-1", "ap-northeast-2", "ap-northeast-3",
    "ap-south-1", "ap-southeast-1", "ap-southeast-2",
    "ca-central-1",
    "eu-central-1", "eu-north-1", "eu-west-1", "eu-west-2", "eu-west-3",
    "sa-east-1",
    "us-east-1", "us-east-2", "us-west-1", "us-west-2",
)

OPTIONAL_REGIONS: tuple[str, ...] = (
    "af-south-1",
    "ap-east-1", "ap-south-2", "ap-southeast-3", "ap-southeast-4",
    "eu-central-2", "eu-south-1", "eu-south-2",
    "me-central-1", "me-south-1",
)

GOVCLOUD_REGIONS: tuple[str, ...] = ("us-gov-east-1", "us-gov-west-1")

CHINA_REGIONS: tuple[str, ...] = ("cn-north-1", "cn-northwest-1")

ALL_AWS_REGIONS: frozenset[str] = frozenset(
    REGULAR_REGIONS + OPTIONAL_REGIONS + GOVCLOUD_REGIONS + CHINA_REGIONS
)

CONNECTION_MODES: tuple[str, ...] = (
    "polling",
    "streaming_splunk_managed",
    "streaming_aws_managed",
    "terraform_only",
)

SERVICES_MODES: tuple[str, ...] = (
    "all_built_in",
    "explicit",
    "namespace_filtered",
    "custom_only",
)

AUTH_MODES: tuple[str, ...] = ("external_id", "security_token")

# Sourced from the supported AWS namespaces table:
# https://help.splunk.com/en/splunk-observability-cloud/manage-data/available-data-sources/supported-integrations-in-splunk-observability-cloud/cloud-services-aws
KNOWN_NAMESPACES: tuple[str, ...] = (
    "AWS/ACMPrivateCA", "AWS/AmazonMQ", "AWS/ApiGateway", "AWS/ApplicationELB",
    "AWS/AppStream", "AWS/Athena", "AWS/AutoScaling", "AWS/Backup",
    "AWS/Bedrock", "AWS/Billing", "AWS/Cassandra", "AWS/CertificateManager",
    "AWS/CloudFront", "AWS/CloudHSM", "AWS/CloudSearch", "AWS/CodeBuild",
    "AWS/Cognito", "AWS/Connect", "AWS/DDoSProtection", "AWS/DMS",
    "AWS/DocDB", "AWS/DX", "AWS/DynamoDB", "AWS/EBS", "AWS/EC2",
    "AWS/EC2Spot", "AWS/ECS", "AWS/EFS", "AWS/EKS", "AWS/ElastiCache",
    "AWS/ElasticBeanstalk", "AWS/ElasticInference", "AWS/ElasticMapReduce",
    "AWS/ElasticTranscoder", "AWS/ELB", "AWS/ES", "AWS/Events",
    "AWS/Firehose", "AWS/FSx", "AWS/GameLift", "AWS/GatewayELB",
    "AWS/GlobalAccelerator", "AWS/Inspector", "AWS/IoT", "AWS/IoTAnalytics",
    "AWS/Kafka", "AWS/Kinesis", "AWS/KinesisAnalytics", "AWS/KinesisVideo",
    "AWS/KMS", "AWS/Lambda", "AWS/Lex", "AWS/Logs",
    "AWS/MediaConnect", "AWS/MediaConvert", "AWS/MediaPackage",
    "AWS/MediaTailor", "AWS/ML", "AWS/MWAA", "AWS/NATGateway",
    "AWS/Neptune", "AWS/NetworkELB", "AWS/NetworkFirewall",
    "AWS/NetworkFlowMonitor", "AWS/OpsWorks", "AWS/Polly", "AWS/RDS",
    "AWS/Redshift", "AWS/Robomaker", "AWS/Route53", "AWS/S3",
    "AWS/S3/Storage-Lens", "AWS/SageMaker", "AWS/sagemaker/Endpoints",
    "AWS/sagemaker/InferenceComponents",
    "AWS/sagemaker/InferenceRecommendationsJobs",
    "AWS/sagemaker/TrainingJobs", "AWS/sagemaker/TransformJobs",
    "AWS/SDKMetrics", "AWS/SES", "AWS/SNS", "AWS/SQS", "AWS/States",
    "AWS/StorageGateway", "AWS/SWF", "AWS/Textract", "AWS/ThingsGraph",
    "AWS/Translate", "AWS/TrustedAdvisor", "AWS/VPN", "AWS/WAFV2",
    "AWS/WorkMail", "AWS/WorkSpaces",
    # Custom AWS namespaces that Splunk also lists as supported.
    "CWAgent", "Glue", "MediaLive", "System/Linux", "WAF", "AmazonMWAA",
)

# Default CloudFormation template URLs (signalfx/aws-cloudformation-templates).
CFN_REGIONAL_URL = (
    "https://o11y-public.s3.amazonaws.com/aws-cloudformation-templates/release/"
    "template_metric_streams_regional.yaml"
)
CFN_STACKSETS_URL = (
    "https://o11y-public.s3.amazonaws.com/aws-cloudformation-templates/release/"
    "template_metric_streams.yaml"
)

# Splunk Add-on for AWS minimum version (Splunkbase 1876).
SPLUNK_TA_AWS_MIN_VERSION = "8.1.1"

# Splunk Lambda layer publisher AWS account.
LAMBDA_LAYER_PUBLISHER_AWS_ACCOUNT = "254067382080"

# Splunk Terraform provider pin (latest stable per CHANGELOG: 9.7.2 in April 2026).
TERRAFORM_PROVIDER_VERSION_DEFAULT = "~> 9.0"

# Section ordering for the numbered plan files.
SECTION_ORDER: tuple[str, ...] = (
    "prerequisites",
    "authentication",
    "connection",
    "regions_services",
    "namespaces",
    "metric_streams",
    "private_link",
    "multi_account",
    "validation",
    "handoff",
)

NUMBERED_PLAN_FILES: tuple[tuple[str, str], ...] = (
    ("00-prerequisites.md", "prerequisites"),
    ("01-authentication.md", "authentication"),
    ("02-connection.md", "connection"),
    ("03-regions-services.md", "regions_services"),
    ("04-namespaces.md", "namespaces"),
    ("05-metric-streams.md", "metric_streams"),
    ("06-private-link.md", "private_link"),
    ("07-multi-account.md", "multi_account"),
    ("08-validation.md", "validation"),
    ("09-handoff.md", "handoff"),
)

# Per-namespace per-metric "AWS recommended stats" allow-list (selected
# subset; full catalog renders into references/recommended-stats.yaml).
RECOMMENDED_STATS_SAMPLE: dict[str, dict[str, list[str]]] = {
    "AWS/ApplicationELB": {
        "ActiveConnectionCount": ["sum"],
        "RequestCount": ["sum"],
        "TargetResponseTime": ["mean", "upper"],
        "HTTPCode_Target_5XX_Count": ["sum"],
    },
    "AWS/EC2": {
        "CPUUtilization": ["mean", "upper"],
        "NetworkIn": ["sum"],
        "NetworkOut": ["sum"],
        "DiskReadBytes": ["sum"],
        "DiskWriteBytes": ["sum"],
        "StatusCheckFailed": ["sum"],
    },
    "AWS/ECS": {
        "CPUUtilization": ["mean", "count"],
        "MemoryUtilization": ["mean", "count"],
    },
    "AWS/Lambda": {
        "ConcurrentExecutions": ["upper"],
        "Duration": ["mean", "upper"],
        "Errors": ["sum"],
        "Invocations": ["sum"],
        "Throttles": ["sum"],
    },
    "AWS/RDS": {
        "CPUUtilization": ["mean", "upper"],
        "FreeStorageSpace": ["lower"],
        "DatabaseConnections": ["mean", "upper"],
        "ReadLatency": ["mean", "upper"],
        "WriteLatency": ["mean", "upper"],
    },
    "AWS/S3": {
        "AllRequests": ["sum"],
        "BucketSizeBytes": ["mean"],
        "NumberOfObjects": ["mean"],
    },
    "AWS/SQS": {
        "ApproximateNumberOfMessagesVisible": ["upper"],
        "NumberOfMessagesSent": ["sum"],
        "NumberOfMessagesReceived": ["sum"],
    },
    "AWS/Kinesis": {
        "GetRecords.IteratorAgeMilliseconds": ["upper"],
        "IncomingBytes": ["sum"],
        "IncomingRecords": ["sum"],
    },
    "AWS/DynamoDB": {
        "ConsumedReadCapacityUnits": ["sum"],
        "ConsumedWriteCapacityUnits": ["sum"],
        "ThrottledRequests": ["sum"],
    },
    "AWS/Bedrock": {
        "InputTokenCount": ["sum"],
        "OutputTokenCount": ["sum"],
        "Invocations": ["sum"],
        "InvocationLatency": ["mean", "upper"],
    },
    "AWS/Firehose": {
        "IncomingBytes": ["sum"],
        "IncomingRecords": ["sum"],
        "DeliveryToS3.Records": ["sum"],
    },
}

# Per-namespace tag-sync IAM permissions (subset; full set lives in
# references/iam-permissions.md).
TAG_SYNC_IAM_PERMISSIONS: tuple[str, ...] = (
    "acm:DescribeCertificate", "acm:ListCertificates",
    "airflow:ListEnvironments", "airflow:GetEnvironment",
    "apigateway:GET",
    "autoscaling:DescribeAutoScalingGroups",
    "bedrock:ListTagsForResource", "bedrock:ListFoundationModels",
    "bedrock:GetFoundationModel", "bedrock:ListInferenceProfiles",
    "cloudformation:ListResources", "cloudformation:GetResource",
    "cloudfront:GetDistributionConfig", "cloudfront:ListDistributions",
    "cloudfront:ListTagsForResource",
    "directconnect:DescribeConnections",
    "dynamodb:DescribeTable", "dynamodb:ListTables", "dynamodb:ListTagsOfResource",
    "ec2:DescribeInstances", "ec2:DescribeInstanceStatus",
    "ec2:DescribeNatGateways", "ec2:DescribeRegions",
    "ec2:DescribeReservedInstances", "ec2:DescribeReservedInstancesModifications",
    "ec2:DescribeTags", "ec2:DescribeVolumes",
    "ecs:DescribeClusters", "ecs:DescribeServices", "ecs:DescribeTasks",
    "ecs:ListClusters", "ecs:ListServices", "ecs:ListTagsForResource",
    "ecs:ListTaskDefinitions", "ecs:ListTasks",
    "eks:DescribeCluster", "eks:ListClusters",
    "elasticache:DescribeCacheClusters",
    "elasticloadbalancing:DescribeLoadBalancerAttributes",
    "elasticloadbalancing:DescribeLoadBalancers",
    "elasticloadbalancing:DescribeTags",
    "elasticloadbalancing:DescribeTargetGroups",
    "elasticmapreduce:DescribeCluster", "elasticmapreduce:ListClusters",
    "es:DescribeElasticsearchDomain", "es:ListDomainNames",
    "kafka:DescribeCluster", "kafka:DescribeClusterV2",
    "kafka:ListClusters", "kafka:ListClustersV2",
    "kinesis:DescribeStream", "kinesis:ListShards", "kinesis:ListStreams",
    "kinesis:ListTagsForStream",
    "kinesisanalytics:DescribeApplication",
    "kinesisanalytics:ListApplications",
    "kinesisanalytics:ListTagsForResource",
    "lambda:GetAlias", "lambda:ListFunctions", "lambda:ListTags",
    "network-firewall:ListFirewalls", "network-firewall:DescribeFirewall",
    "organizations:DescribeOrganization",
    "rds:DescribeDBInstances", "rds:DescribeDBClusters",
    "rds:ListTagsForResource",
    "redshift:DescribeClusters", "redshift:DescribeLoggingStatus",
    "s3:GetBucketLocation", "s3:GetBucketLogging", "s3:GetBucketNotification",
    "s3:GetBucketTagging", "s3:ListAllMyBuckets", "s3:ListBucket",
    "s3:PutBucketNotification",
    "sqs:GetQueueAttributes", "sqs:ListQueues", "sqs:ListQueueTags",
    "states:ListActivities", "states:ListStateMachines",
    "tag:GetResources",
    "workspaces:DescribeWorkspaces",
)

# Cassandra/Keyspaces special-case Resource ARNs (cannot share Resource: "*").
CASSANDRA_RESOURCE_ARNS: tuple[str, ...] = (
    "arn:aws:cassandra:*:*:/keyspace/system/table/local",
    "arn:aws:cassandra:*:*:/keyspace/system/table/peers",
    "arn:aws:cassandra:*:*:/keyspace/system_schema/*",
    "arn:aws:cassandra:*:*:/keyspace/system_schema_mcs/table/tags",
    "arn:aws:cassandra:*:*:/keyspace/system_schema_mcs/table/tables",
    "arn:aws:cassandra:*:*:/keyspace/system_schema_mcs/table/columns",
)

# PrivateLink endpoint patterns. The current Splunk PrivateLink doc (last
# updated Sep 2024) uses the legacy signalfx.com domain; we default to it
# and let the operator opt into the new domain via spec.private_link.domain.
PRIVATELINK_PATTERNS_LEGACY: dict[str, str] = {
    "ingest": "private-ingest.{realm}.signalfx.com",
    "api": "private-api.{realm}.signalfx.com",
    "stream": "private-stream.{realm}.signalfx.com",
    "backfill": "private-backfill.{realm}.signalfx.com",
}
PRIVATELINK_PATTERNS_NEW: dict[str, str] = {
    "ingest": "private-ingest.{realm}.observability.splunkcloud.com",
    "api": "private-api.{realm}.observability.splunkcloud.com",
    "stream": "private-stream.{realm}.observability.splunkcloud.com",
    "backfill": "private-backfill.{realm}.observability.splunkcloud.com",
}

# Patterns the secret-leak scanner flags before write.
SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"eyJ[A-Za-z0-9._-]{20,}"),  # JWT-looking
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{12,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key id pattern
    re.compile(r"(?i)aws_secret_access_key\s*[:=]\s*[A-Za-z0-9/+=]{20,}"),
)


# ---------------------------------------------------------------------------
# Spec loading and validation.
# ---------------------------------------------------------------------------


class RenderError(Exception):
    """Raised when the spec cannot be rendered (FAIL)."""


def load_spec(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        loaded = load_yaml_or_json(text, source=str(path))
    except (json.JSONDecodeError, YamlCompatError) as exc:
        raise RenderError(f"failed to parse spec {path}: {exc}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise RenderError("spec root must be a mapping")
    return loaded


def assert_no_secrets_in_text(text: str, label: str) -> None:
    """Raise if ``text`` looks like it contains a secret. Used pre-write."""
    for pat in SECRET_PATTERNS:
        if pat.search(text):
            raise RenderError(
                f"refusing to write {label}: secret-looking content matched {pat.pattern!r}"
            )


def validate_spec(spec: dict[str, Any], realm_override: str | None = None) -> dict[str, Any]:
    """Normalize spec, fill in defaults, and FAIL on hard validation errors."""
    if not isinstance(spec, dict):
        raise RenderError("spec root must be a mapping")

    spec.setdefault("api_version", API_VERSION)
    if not isinstance(spec["api_version"], str):
        raise RenderError("api_version must be a string")
    if spec["api_version"] != API_VERSION:
        raise RenderError(
            f"api_version must be {API_VERSION!r}, got {spec['api_version']!r}"
        )

    realm = realm_override or spec.get("realm", "")
    if not realm:
        raise RenderError(
            f"realm is required ({'/'.join(SUPPORTED_REALMS)}). "
            "us2-gcp is GCP-hosted and not supported by the AWS integration."
        )
    if realm == "us2-gcp":
        raise RenderError(
            "realm us2-gcp is GCP-hosted; the AWSCloudWatch integration is not "
            "available on this realm. Pick an AWS-hosted realm instead "
            f"({'/'.join(SUPPORTED_REALMS)})."
        )
    if realm not in SUPPORTED_REALMS:
        raise RenderError(
            f"realm {realm!r} is not recognized. Allowed: {', '.join(SUPPORTED_REALMS)}"
        )
    spec["realm"] = realm

    if not spec.get("integration_name"):
        raise RenderError("integration_name is required")

    auth = spec.setdefault("authentication", {})
    auth.setdefault("mode", "external_id")
    if auth["mode"] not in AUTH_MODES:
        raise RenderError(
            f"authentication.mode must be one of {AUTH_MODES}, got {auth['mode']!r}"
        )

    if auth["mode"] == "external_id":
        if not auth.get("aws_account_id"):
            raise RenderError(
                "authentication.aws_account_id is required when mode=external_id"
            )
        if not isinstance(auth["aws_account_id"], str) or not auth["aws_account_id"].isdigit():
            raise RenderError(
                "authentication.aws_account_id must be a quoted 12-digit string"
            )
        auth.setdefault("iam_role_name", "SplunkObservabilityRole")
        auth.setdefault("external_id", "")

    conn = spec.setdefault("connection", {})
    conn.setdefault("mode", "polling")
    if conn["mode"] not in CONNECTION_MODES:
        raise RenderError(
            f"connection.mode must be one of {CONNECTION_MODES}, got {conn['mode']!r}"
        )
    poll_rate = int(conn.setdefault("poll_rate_seconds", 300))
    if not 60 <= poll_rate <= 600:
        raise RenderError(
            f"connection.poll_rate_seconds must be between 60 and 600, got {poll_rate}"
        )
    conn["poll_rate_seconds"] = poll_rate
    conn.setdefault("metadata_poll_rate_seconds", 900)
    adaptive = conn.setdefault("adaptive_polling", {})
    adaptive.setdefault("enabled", True)
    inactive = int(adaptive.setdefault("inactive_seconds", 1200))
    if not 60 <= inactive <= 3600:
        raise RenderError(
            f"connection.adaptive_polling.inactive_seconds must be between 60 and 3600, "
            f"got {inactive}"
        )
    adaptive["inactive_seconds"] = inactive

    regions = spec.get("regions") or []
    if not isinstance(regions, list) or not regions:
        raise RenderError(
            "regions cannot be empty. The canonical schema rejects an empty list "
            "and Splunk highly discourages it because new AWS regions auto-onboard "
            "and inflate cost. Enumerate explicitly."
        )
    bad_regions = [r for r in regions if r not in ALL_AWS_REGIONS]
    if bad_regions:
        raise RenderError(f"unknown AWS regions: {', '.join(bad_regions)}")

    govcloud_or_china = [r for r in regions if r in GOVCLOUD_REGIONS or r in CHINA_REGIONS]
    if govcloud_or_china and auth["mode"] != "security_token":
        raise RenderError(
            f"GovCloud / China regions require authentication.mode=security_token, "
            f"got mode={auth['mode']!r} (offending regions: {', '.join(govcloud_or_china)})."
        )
    spec["regions"] = regions

    services = spec.setdefault("services", {})
    services.setdefault("mode", "all_built_in")
    if services["mode"] not in SERVICES_MODES:
        raise RenderError(
            f"services.mode must be one of {SERVICES_MODES}, got {services['mode']!r}"
        )
    services.setdefault("explicit", [])
    services.setdefault("collect_only_recommended_stats", False)
    services.setdefault("metric_stats_to_syncs", [])
    services.setdefault("namespace_sync_rules", [])

    if services["mode"] == "explicit" and not services["explicit"]:
        raise RenderError("services.explicit must be non-empty when mode=explicit")
    if services["mode"] == "namespace_filtered" and not services["namespace_sync_rules"]:
        raise RenderError(
            "services.namespace_sync_rules must be non-empty when mode=namespace_filtered"
        )

    if services["explicit"] and services["namespace_sync_rules"]:
        raise RenderError(
            "services.explicit and services.namespace_sync_rules conflict at the API "
            "level (the canonical schema makes them mutually exclusive). Pick one."
        )

    bad_namespaces = [
        n for n in services["explicit"] if n not in KNOWN_NAMESPACES and not n.startswith(("AWS/", "AmazonMWAA"))
    ]
    if bad_namespaces:
        # Warn rather than fail; operator may have a legitimate custom namespace.
        services.setdefault("_warnings", []).append(
            f"unknown namespaces in services.explicit: {', '.join(bad_namespaces)}"
        )

    custom = spec.setdefault("custom_namespaces", {})
    custom.setdefault("simple_list", [])
    custom.setdefault("sync_rules", [])
    if custom["simple_list"] and custom["sync_rules"]:
        raise RenderError(
            "custom_namespaces.simple_list and custom_namespaces.sync_rules conflict "
            "at the API level (customCloudwatchNamespaces vs customNamespaceSyncRules). "
            "Pick one."
        )
    spec.setdefault("sync_custom_namespaces_only", False)

    guards = spec.setdefault("guards", {})
    guards.setdefault("enable_check_large_volume", True)
    guards.setdefault("ignore_all_status_metrics", False)
    guards.setdefault("sync_load_balancer_target_group_tags", False)
    guards.setdefault("enable_aws_usage", False)

    streams = spec.setdefault("metric_streams", {})
    streams.setdefault("use_metric_streams_sync", conn["mode"] in (
        "streaming_splunk_managed", "streaming_aws_managed"
    ))
    streams.setdefault("managed_externally", conn["mode"] == "streaming_aws_managed")
    streams.setdefault("named_token", "")
    streams.setdefault("cloudformation", conn["mode"] == "streaming_splunk_managed")
    streams.setdefault("cloudformation_template_url", "")
    streams.setdefault("use_stack_sets", False)
    streams.setdefault("terraform", False)
    if streams["managed_externally"] and not streams["use_metric_streams_sync"]:
        raise RenderError(
            "metric_streams.managed_externally=true requires metric_streams.use_metric_streams_sync=true "
            "per the canonical AWSCloudWatch schema."
        )

    pl = spec.setdefault("private_link", {})
    pl.setdefault("enable", False)
    pl.setdefault("endpoint_types", ["ingest", "api", "stream"])
    pl.setdefault("service_name_overrides", {})
    pl.setdefault("domain", "legacy")
    if pl["domain"] not in {"legacy", "new"}:
        raise RenderError(
            f"private_link.domain must be 'legacy' or 'new', got {pl['domain']!r}"
        )

    tf = spec.setdefault("terraform_provider", {})
    tf.setdefault("source", "splunk-terraform/signalfx")
    tf.setdefault("version", TERRAFORM_PROVIDER_VERSION_DEFAULT)

    multi = spec.setdefault("multi_account", {})
    multi.setdefault("enabled", False)
    multi.setdefault("control_account_id", "")
    multi.setdefault("member_accounts", [])
    cfn_ss = multi.setdefault("cfn_stacksets", {})
    cfn_ss.setdefault("template_url", "")
    cfn_ss.setdefault("use_org_service_managed", True)
    cfn_ss.setdefault("fallback_admin_role", "AWSCloudFormationStackSetAdministrationRole")
    cfn_ss.setdefault("fallback_execution_role", "AWSCloudFormationStackSetExecutionRole")

    if multi["enabled"]:
        if not multi["control_account_id"]:
            raise RenderError("multi_account.control_account_id is required when multi_account.enabled=true")
        if not multi["member_accounts"]:
            raise RenderError("multi_account.member_accounts must be non-empty when multi_account.enabled=true")
        for entry in multi["member_accounts"]:
            if not isinstance(entry, dict) or not entry.get("aws_account_id"):
                raise RenderError("each multi_account.member_accounts entry must include aws_account_id")

    handoffs = spec.setdefault("handoffs", {})
    for k, default in (
        ("lambda_apm", False),
        ("logs_via_splunk_ta_aws", False),
        ("dashboards", False),
        ("detectors", False),
        ("otel_collector_for_ec2_eks", False),
    ):
        handoffs.setdefault(k, default)

    if "enableLogsSync" in spec or "enable_logs_sync" in spec:
        raise RenderError(
            "enableLogsSync (enable_logs_sync) is deprecated and rejected. AWS log "
            "ingestion goes through the Splunk Add-on for AWS (Splunkbase 1876, "
            "min v8.1.1) -- use handoffs.logs_via_splunk_ta_aws=true and "
            "splunk-app-install."
        )

    return spec


# ---------------------------------------------------------------------------
# Coverage decision logic.
# ---------------------------------------------------------------------------


def coverage_for(spec: dict[str, Any]) -> dict[str, dict[str, str]]:
    coverage: dict[str, dict[str, str]] = {}

    coverage["prerequisites.realm_region"] = {
        "status": "api_validate",
        "notes": f"realm {spec['realm']} -> STS region {REALM_STS_REGION[spec['realm']]}",
    }
    coverage["prerequisites.cfn_template_probe"] = {
        "status": "api_validate",
        "notes": "HTTP HEAD on the configured CFN template URL.",
    }
    coverage["prerequisites.fedramp_gate"] = {
        "status": "api_validate",
        "notes": "Splunk Observability Cloud is NOT FedRAMP-authorized as of early 2026.",
    }

    coverage["authentication.iam_policy"] = {
        "status": "api_apply",
        "notes": "Operator deploys the IAM trust role and attaches the rendered policy JSON.",
    }
    coverage["authentication.integration_create"] = {
        "status": "api_apply",
        "notes": "POST /v2/integration with type=AWSCloudWatch, returns externalId + sfxAwsAccountArn.",
    }

    conn_mode = spec["connection"]["mode"]
    coverage["connection.mode"] = {
        "status": "api_apply",
        "notes": f"connection.mode={conn_mode}",
    }
    coverage["connection.adaptive_polling"] = {
        "status": "api_apply" if spec["connection"]["adaptive_polling"]["enabled"] else "api_validate",
        "notes": "PUT /v2/integration/{id} with inactiveMetricsPollRate.",
    }

    coverage["regions_services.regions"] = {
        "status": "api_apply",
        "notes": f"{len(spec['regions'])} regions enumerated.",
    }
    services_mode = spec["services"]["mode"]
    coverage["regions_services.services_mode"] = {
        "status": "api_apply",
        "notes": f"services.mode={services_mode}",
    }
    coverage["regions_services.recommended_stats"] = {
        "status": "api_apply" if spec["services"]["collect_only_recommended_stats"] else "api_validate",
        "notes": "PUT /v2/integration/{id} with collectOnlyRecommendedStats.",
    }
    coverage["regions_services.metric_stats_to_syncs"] = {
        "status": "api_apply" if spec["services"]["metric_stats_to_syncs"] else "not_applicable",
        "notes": "Per-namespace per-metric stat allow-list (extended/percentile only when streaming).",
    }

    if spec["custom_namespaces"]["simple_list"] or spec["custom_namespaces"]["sync_rules"]:
        coverage["namespaces.custom"] = {
            "status": "api_apply",
            "notes": "Custom CloudWatch namespaces or sync rules attached to the integration.",
        }
    else:
        coverage["namespaces.custom"] = {"status": "not_applicable", "notes": "No custom namespaces."}
    coverage["namespaces.sync_custom_only"] = {
        "status": "api_apply" if spec["sync_custom_namespaces_only"] else "not_applicable",
        "notes": "syncCustomNamespacesOnly toggle.",
    }

    if spec["metric_streams"]["use_metric_streams_sync"]:
        coverage["metric_streams.use_metric_streams_sync"] = {
            "status": "api_apply",
            "notes": "PUT /v2/integration/{id} with useMetricStreamsSync=true.",
        }
        if spec["metric_streams"]["managed_externally"]:
            coverage["metric_streams.managed_externally"] = {
                "status": "api_apply",
                "notes": "AWS-console-driven streams; one external integration per AWS account.",
            }
            coverage["metric_streams.cloudformation"] = {
                "status": "deeplink",
                "notes": "Operator creates streams in the AWS console (Quick AWS Partner setup).",
            }
        else:
            coverage["metric_streams.managed_externally"] = {"status": "not_applicable", "notes": ""}
            template = "StackSets" if spec["metric_streams"]["use_stack_sets"] else "regional"
            coverage["metric_streams.cloudformation"] = {
                "status": "api_apply" if spec["metric_streams"]["cloudformation"] else "handoff",
                "notes": f"CloudFormation {template} template stub rendered.",
            }
    else:
        for k in ("use_metric_streams_sync", "managed_externally", "cloudformation"):
            coverage[f"metric_streams.{k}"] = {"status": "not_applicable", "notes": "polling mode."}

    if spec["private_link"]["enable"]:
        coverage["private_link"] = {
            "status": "deeplink",
            "notes": (
                f"PrivateLink VPCE setup is operator-driven; URLs use the "
                f"{spec['private_link']['domain']} domain pattern."
            ),
        }
    else:
        coverage["private_link"] = {"status": "not_applicable", "notes": "PrivateLink disabled."}

    if spec["multi_account"]["enabled"]:
        coverage["multi_account"] = {
            "status": "api_apply",
            "notes": (
                f"{len(spec['multi_account']['member_accounts'])} member integrations + "
                f"CFN StackSets (use_org_service_managed="
                f"{spec['multi_account']['cfn_stacksets']['use_org_service_managed']})."
            ),
        }
    else:
        coverage["multi_account"] = {"status": "not_applicable", "notes": "Single-account spec."}

    coverage["validation.live_get"] = {
        "status": "api_validate",
        "notes": "GET /v2/integration/{id} round-trip; drift report against spec.",
    }

    handoffs = spec["handoffs"]
    for k in ("lambda_apm", "logs_via_splunk_ta_aws", "dashboards", "detectors", "otel_collector_for_ec2_eks"):
        coverage[f"handoff.{k}"] = {
            "status": "handoff" if handoffs[k] else "not_applicable",
            "notes": "",
        }

    return coverage


# ---------------------------------------------------------------------------
# IAM policy emission.
# ---------------------------------------------------------------------------


def render_iam_trust_policy(spec: dict[str, Any], sfx_aws_account_arn: str | None = None) -> dict[str, Any]:
    """Trust policy for the customer IAM role (External-ID auth)."""
    auth = spec["authentication"]
    if auth["mode"] != "external_id":
        return {}
    if sfx_aws_account_arn is None:
        account_id = SPLUNK_AWS_ACCOUNT_ID_PER_REALM.get(spec["realm"])
        sfx_aws_account_arn = (
            f"arn:aws:iam::{account_id}:root" if account_id
            else "arn:aws:iam::${SPLUNK_AWS_ACCOUNT_ID_FROM_POST_RESPONSE}:root"
        )
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"AWS": sfx_aws_account_arn},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {
                        "sts:ExternalId": auth.get("external_id") or "${EXTERNAL_ID_FROM_POST_RESPONSE}"
                    }
                },
            }
        ],
    }


def render_iam_foundation_policy() -> dict[str, Any]:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "ec2:DescribeRegions",
                    "iam:ListAccountAliases",
                    "organizations:DescribeOrganization",
                    "tag:GetResources",
                    "cloudformation:ListResources",
                    "cloudformation:GetResource",
                ],
                "Resource": "*",
            }
        ],
    }


def render_iam_polling_policy() -> dict[str, Any]:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "cloudwatch:GetMetricData",
                    "cloudwatch:ListMetrics",
                    "ec2:DescribeRegions",
                    "organizations:DescribeOrganization",
                    "tag:GetResources",
                    "cloudformation:ListResources",
                    "cloudformation:GetResource",
                ],
                "Resource": "*",
            }
        ],
    }


def render_iam_streams_policy() -> dict[str, Any]:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "cloudwatch:DeleteMetricStream",
                    "cloudwatch:GetMetricStream",
                    "cloudwatch:ListMetricStreams",
                    "cloudwatch:ListMetrics",
                    "cloudwatch:PutMetricStream",
                    "cloudwatch:StartMetricStreams",
                    "cloudwatch:StopMetricStreams",
                    "ec2:DescribeRegions",
                    "organizations:DescribeOrganization",
                    "tag:GetResources",
                ],
                "Resource": "*",
            },
            {
                "Effect": "Allow",
                "Action": ["iam:PassRole"],
                "Resource": "arn:aws:iam::*:role/splunk-metric-streams*",
            },
        ],
    }


def render_iam_tag_sync_policy() -> dict[str, Any]:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": list(TAG_SYNC_IAM_PERMISSIONS),
                "Resource": "*",
            },
            {
                "Effect": "Allow",
                "Action": ["cassandra:Select"],
                "Resource": list(CASSANDRA_RESOURCE_ARNS),
            },
        ],
    }


def render_iam_combined_policy(spec: dict[str, Any]) -> dict[str, Any]:
    """Single combined IAM policy that the operator can attach to the trust role."""
    statements: list[dict[str, Any]] = []
    foundation = render_iam_foundation_policy()
    statements.extend(foundation["Statement"])

    if spec["connection"]["mode"] == "polling":
        polling = render_iam_polling_policy()
        for st in polling["Statement"]:
            if st not in statements:
                statements.append(st)
    if spec["metric_streams"]["use_metric_streams_sync"] and not spec["metric_streams"]["managed_externally"]:
        streams = render_iam_streams_policy()
        statements.extend(streams["Statement"])
    tag_sync = render_iam_tag_sync_policy()
    statements.extend(tag_sync["Statement"])
    return {"Version": "2012-10-17", "Statement": statements}


# ---------------------------------------------------------------------------
# REST payload emission.
# ---------------------------------------------------------------------------


def render_rest_payload(spec: dict[str, Any], integration_id: str | None = None) -> dict[str, Any]:
    """Translate the spec into the canonical raw REST POST/PUT payload.

    Durations stay in seconds in the spec but the raw API uses milliseconds for
    pollRate / metadataPollRate / inactiveMetricsPollRate. We convert here.
    """
    auth = spec["authentication"]
    payload: dict[str, Any] = {
        "type": "AWSCloudWatch",
        "name": spec["integration_name"],
        "enabled": False,
        "authMethod": "ExternalId" if auth["mode"] == "external_id" else "SecurityToken",
        "regions": list(spec["regions"]),
        "pollRate": int(spec["connection"]["poll_rate_seconds"]) * 1000,
        "metadataPollRate": int(spec["connection"]["metadata_poll_rate_seconds"]) * 1000,
        "importCloudWatch": True,
        "enableAwsUsage": bool(spec["guards"]["enable_aws_usage"]),
        "enableCheckLargeVolume": bool(spec["guards"]["enable_check_large_volume"]),
        "syncCustomNamespacesOnly": bool(spec["sync_custom_namespaces_only"]),
        "syncLoadBalancerTargetGroupTags": bool(spec["guards"]["sync_load_balancer_target_group_tags"]),
        "ignoreAllStatusMetrics": bool(spec["guards"]["ignore_all_status_metrics"]),
        "useMetricStreamsSync": bool(spec["metric_streams"]["use_metric_streams_sync"]),
        "metricStreamsManagedExternally": bool(spec["metric_streams"]["managed_externally"]),
    }

    if spec["connection"]["adaptive_polling"]["enabled"]:
        payload["inactiveMetricsPollRate"] = int(
            spec["connection"]["adaptive_polling"]["inactive_seconds"]
        ) * 1000

    if spec["services"]["explicit"]:
        payload["services"] = list(spec["services"]["explicit"])
    if spec["services"]["namespace_sync_rules"]:
        payload["namespaceSyncRules"] = [
            {
                "namespace": rule["namespace"],
                "filterAction": rule["filter_action"],
                "filterSource": rule["filter_source"],
                "defaultAction": rule.get("default_action", "Exclude"),
            }
            for rule in spec["services"]["namespace_sync_rules"]
        ]
    if spec["services"]["collect_only_recommended_stats"]:
        payload["collectOnlyRecommendedStats"] = True
    if spec["services"]["metric_stats_to_syncs"]:
        payload["metricStatsToSyncs"] = [
            {
                "namespace": entry["namespace"],
                "metric": entry["metric"],
                "stats": list(entry["stats"]),
            }
            for entry in spec["services"]["metric_stats_to_syncs"]
        ]

    if spec["custom_namespaces"]["simple_list"]:
        # The raw REST API uses `customCloudWatchNamespaces` (capital W) per
        # live discover against the operator's account. The Pulumi/Terraform
        # docs use `customCloudwatchNamespaces` (lowercase w) -- that form is
        # accepted on read but the canonical write form is capital W.
        payload["customCloudWatchNamespaces"] = list(spec["custom_namespaces"]["simple_list"])
    if spec["custom_namespaces"]["sync_rules"]:
        payload["customNamespaceSyncRules"] = [
            {
                "namespace": rule["namespace"],
                "filterAction": rule["filter_action"],
                "filterSource": rule["filter_source"],
                "defaultAction": rule.get("default_action", "Exclude"),
            }
            for rule in spec["custom_namespaces"]["sync_rules"]
        ]

    if spec["metric_streams"]["named_token"]:
        payload["namedToken"] = spec["metric_streams"]["named_token"]

    if auth["mode"] == "external_id":
        payload["roleArn"] = "${ROLE_ARN_FROM_CFN_OR_OPERATOR}"
    else:
        payload["token"] = "${AWS_ACCESS_KEY_ID_FROM_FILE}"
        payload["key"] = "${AWS_SECRET_ACCESS_KEY_FROM_FILE}"

    if integration_id:
        payload["id"] = integration_id

    return payload


# ---------------------------------------------------------------------------
# CloudFormation and Terraform emission.
# ---------------------------------------------------------------------------


def render_cfn_stub(spec: dict[str, Any]) -> str:
    """Render a CloudFormation deploy stub (URL + parameters; not the template body)."""
    streams = spec["metric_streams"]
    if not streams["cloudformation"] and not streams["use_stack_sets"]:
        return "# CloudFormation stub not requested (metric_streams.cloudformation=false).\n"
    template_url = streams["cloudformation_template_url"] or (
        CFN_STACKSETS_URL if streams["use_stack_sets"] else CFN_REGIONAL_URL
    )
    flavor = "StackSets (multi-region)" if streams["use_stack_sets"] else "regional (per-region)"
    lines: list[str] = [
        f"# CloudFormation deploy stub ({flavor}).",
        f"# Template URL: {template_url}",
        "# This stub is operator-driven; copy the appropriate command per region.",
        "",
    ]
    if streams["use_stack_sets"]:
        lines += [
            "# 1. Choose a control account (AWS Organizations management or delegated admin).",
            "# 2. Deploy the multi-region StackSets template across member accounts:",
            "aws cloudformation create-stack-set \\",
            "  --stack-set-name SplunkObservability-MetricStreams \\",
            f"  --template-url {template_url} \\",
            "  --permission-model SERVICE_MANAGED \\",
            "  --auto-deployment Enabled=true,RetainStacksOnAccountRemoval=false \\",
            "  --capabilities CAPABILITY_NAMED_IAM \\",
            f"  --parameters ParameterKey=SplunkRealm,ParameterValue={spec['realm']}",
            "",
        ]
    else:
        lines += [
            "# Per-region deployment loop:",
            "for region in " + " ".join(spec["regions"]) + "; do",
            "  aws cloudformation create-stack \\",
            "    --stack-name SplunkObservability-MetricStreams-${region} \\",
            f"    --template-url {template_url} \\",
            "    --capabilities CAPABILITY_NAMED_IAM \\",
            f"    --parameters ParameterKey=SplunkRealm,ParameterValue={spec['realm']} \\",
            "    --region ${region}",
            "done",
            "",
        ]
    lines.append("# After CFN finishes, capture the trust-role ARN (CFN output) and pass")
    lines.append("# it back to the renderer's PUT /v2/integration/{id} step as roleArn.")
    return "\n".join(lines) + "\n"


def render_terraform_main(spec: dict[str, Any]) -> str:
    auth = spec["authentication"]
    tf = spec["terraform_provider"]
    pieces: list[str] = []

    pieces.append(f"""terraform {{
  required_providers {{
    signalfx = {{
      source  = "{tf['source']}"
      version = "{tf['version']}"
    }}
  }}
}}

provider "signalfx" {{
  # Set SFX_AUTH_TOKEN environment variable from your chmod-600 token file:
  #   export SFX_AUTH_TOKEN="$(cat ${{SPLUNK_O11Y_TOKEN_FILE}})"
  api_url = "https://api.{spec['realm']}.observability.splunkcloud.com"
}}

resource "signalfx_aws_external_integration" "this" {{
  name = "{spec['integration_name']}"
}}
""")

    pieces.append(f"""# AWS-side IAM trust role. Pass the external_id from the
# signalfx_aws_external_integration resource into the AssumeRole condition.
data "aws_iam_policy_document" "trust" {{
  statement {{
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {{
      type        = "AWS"
      identifiers = [signalfx_aws_external_integration.this.signalfx_aws_account]
    }}
    condition {{
      test     = "StringEquals"
      variable = "sts:ExternalId"
      values   = [signalfx_aws_external_integration.this.external_id]
    }}
  }}
}}

resource "aws_iam_role" "splunk_observability" {{
  name               = "{auth.get('iam_role_name', 'SplunkObservabilityRole')}"
  assume_role_policy = data.aws_iam_policy_document.trust.json
}}

resource "aws_iam_role_policy" "splunk_observability_policy" {{
  name   = "SplunkObservabilityPolicy"
  role   = aws_iam_role.splunk_observability.id
  policy = file("${{path.module}}/iam-combined.json")
}}
""")

    services_block = ""
    if spec["services"]["explicit"]:
        services_block = "  services = " + json.dumps(spec["services"]["explicit"]) + "\n"

    namespace_rules = ""
    for rule in spec["services"]["namespace_sync_rules"]:
        namespace_rules += f"""  namespace_sync_rule {{
    namespace      = "{rule['namespace']}"
    filter_action  = "{rule['filter_action']}"
    filter_source  = "{rule['filter_source']}"
    default_action = "{rule.get('default_action', 'Exclude')}"
  }}
"""

    custom_ns_block = ""
    if spec["custom_namespaces"]["simple_list"]:
        custom_ns_block = "  custom_cloudwatch_namespaces = " + json.dumps(
            spec["custom_namespaces"]["simple_list"]
        ) + "\n"
    custom_rules = ""
    for rule in spec["custom_namespaces"]["sync_rules"]:
        custom_rules += f"""  custom_namespace_sync_rule {{
    namespace      = "{rule['namespace']}"
    filter_action  = "{rule['filter_action']}"
    filter_source  = "{rule['filter_source']}"
    default_action = "{rule.get('default_action', 'Exclude')}"
  }}
"""

    metric_stats = ""
    for entry in spec["services"]["metric_stats_to_syncs"]:
        metric_stats += f"""  metric_stats_to_sync {{
    namespace = "{entry['namespace']}"
    metric    = "{entry['metric']}"
    stats     = {json.dumps(entry['stats'])}
  }}
"""

    pieces.append(f"""resource "signalfx_aws_integration" "this" {{
  enabled         = true
  integration_id  = signalfx_aws_external_integration.this.id
  external_id     = signalfx_aws_external_integration.this.external_id
  role_arn        = aws_iam_role.splunk_observability.arn
  regions         = {json.dumps(spec['regions'])}
  poll_rate       = {spec['connection']['poll_rate_seconds']}
  inactive_metrics_poll_rate = {spec['connection']['adaptive_polling']['inactive_seconds']}
  import_cloud_watch = true
  enable_aws_usage           = {str(spec['guards']['enable_aws_usage']).lower()}
  enable_check_large_volume  = {str(spec['guards']['enable_check_large_volume']).lower()}
  use_metric_streams_sync    = {str(spec['metric_streams']['use_metric_streams_sync']).lower()}
  metric_streams_managed_externally = {str(spec['metric_streams']['managed_externally']).lower()}
  collect_only_recommended_stats    = {str(spec['services']['collect_only_recommended_stats']).lower()}
  sync_custom_namespaces_only       = {str(spec['sync_custom_namespaces_only']).lower()}
{services_block}{namespace_rules}{custom_ns_block}{custom_rules}{metric_stats}}}
""")
    return "\n".join(pieces)


# ---------------------------------------------------------------------------
# Plan-tree rendering.
# ---------------------------------------------------------------------------


def write_text(path: Path, text: str, label: str | None = None) -> None:
    assert_no_secrets_in_text(text, label or path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def render_readme(spec: dict[str, Any]) -> str:
    return f"""# Splunk Observability Cloud <-> AWS Integration ({spec['integration_name']})

Generated by [`{SKILL_NAME}`](../skills/{SKILL_NAME}/SKILL.md) at {datetime.now(timezone.utc).isoformat()}.

## TL;DR

- Realm: `{spec['realm']}` (STS region: `{REALM_STS_REGION[spec['realm']]}`)
- Connection: `{spec['connection']['mode']}`
- Auth: `{spec['authentication']['mode']}`
- Regions: {', '.join(spec['regions'])}
- Services: `{spec['services']['mode']}` ({len(spec['services']['explicit'])} explicit)
- Custom namespaces: {len(spec['custom_namespaces']['simple_list'])} simple, {len(spec['custom_namespaces']['sync_rules'])} sync rules
- Multi-account: `{spec['multi_account']['enabled']}`
- PrivateLink: `{spec['private_link']['enable']}` ({spec['private_link']['domain']} domain)

## Next steps

1. Review the numbered plan: `00-prerequisites.md` ... `09-handoff.md`.
2. Apply the IAM trust role + policy from `iam/`.
3. Apply the integration: `bash scripts/apply-integration.sh`.
4. If `connection.mode=streaming_splunk_managed`: `bash scripts/apply-cloudformation.sh`.
5. If `multi_account.enabled`: `bash scripts/apply-multi-account.sh`.
6. Validate: `bash scripts/validate-live.sh`.

See `coverage-report.json` for per-section coverage status. See `apply-plan.json`
for the apply ordering and idempotency keys.
"""


def render_architecture_mmd(spec: dict[str, Any]) -> str:
    return f"""flowchart LR
  subgraph Operator["Operator workstation"]
    spec[template.example]
    setup[setup.sh]
  end
  subgraph SplunkO11y["Splunk Observability Cloud (api.{spec['realm']}.observability.splunkcloud.com)"]
    integration["/v2/integration<br/>type=AWSCloudWatch<br/>name={spec['integration_name']}"]
  end
  subgraph AWSAccount["AWS account"]
    iam[IAM trust role<br/>+ External ID]
    streams[CloudWatch Metric Streams<br/>+ Firehose + S3 backup]
  end
  spec --> setup
  setup -->|POST/PUT/GET| integration
  setup -->|deploy stub| iam
  setup -->|deploy stub| streams
  integration -.discover/doctor.-> setup
"""


def render_section_md(section: str, spec: dict[str, Any], coverage: dict[str, dict[str, str]]) -> str:
    relevant = {k: v for k, v in coverage.items() if k.startswith(section.split(".")[0])}

    sections_text = {
        "prerequisites": _section_prereq,
        "authentication": _section_auth,
        "connection": _section_conn,
        "regions_services": _section_regions_services,
        "namespaces": _section_namespaces,
        "metric_streams": _section_metric_streams,
        "private_link": _section_private_link,
        "multi_account": _section_multi_account,
        "validation": _section_validation,
        "handoff": _section_handoff,
    }
    body = sections_text[section](spec)
    cov_lines = ["", "## Coverage", "", "| Key | Status | Notes |", "|-----|--------|-------|"]
    for k, v in relevant.items():
        cov_lines.append(f"| `{k}` | `{v['status']}` | {v['notes']} |")
    return body + "\n" + "\n".join(cov_lines) + "\n"


def _section_prereq(spec: dict[str, Any]) -> str:
    return f"""# Prerequisites

- Splunk Observability Cloud realm: `{spec['realm']}` (STS region `{REALM_STS_REGION[spec['realm']]}`).
- AWS-hosted realm only. The GCP-hosted `us2-gcp` realm is rejected by the renderer.
- Splunk Observability Cloud is **not yet FedRAMP-authorized** as of early 2026
  (Splunk Cloud Platform is FedRAMP Moderate; Splunk Observability is on the
  roadmap). FedRAMP / IL5 customers cannot use this skill against a FedRAMP
  environment until Splunk publishes authorization. See:
  https://help.splunk.com/en/splunk-observability-cloud/fedramp-support/fedramp-support-for-splunk-observability-cloud
- AWS region inventory at render time:
  - {len(REGULAR_REGIONS)} regular regions
  - {len(OPTIONAL_REGIONS)} optional regions (must be activated AWS-side first)
  - {len(GOVCLOUD_REGIONS)} GovCloud regions (force `authentication.mode=security_token`)
  - {len(CHINA_REGIONS)} China regions (force `authentication.mode=security_token`)
- The renderer has FAILed render if any of the above were violated; this file
  exists only when those checks passed.
- The CloudFormation regional template is hosted at
  `{CFN_REGIONAL_URL}` and the StackSets template at `{CFN_STACKSETS_URL}`.
- Token-auth user API access token (admin scope) required for
  `POST /v2/integration` -- see Safety Rules in `SKILL.md`.
"""


def _section_auth(spec: dict[str, Any]) -> str:
    auth = spec["authentication"]
    if auth["mode"] == "external_id":
        return f"""# Authentication: External-ID flow

- AWS account ID: `{auth['aws_account_id']}`
- IAM role name: `{auth.get('iam_role_name', 'SplunkObservabilityRole')}`
- External ID: returned by `POST /v2/integration` and embedded in the trust
  policy at apply time.
- Trust policy: `iam/iam-trust.json`.
- Combined attached policy: `iam/iam-combined.json` (foundation + polling/streams +
  tag sync + Cassandra-Keyspaces special case).
- Apply order:
  1. `POST /v2/integration` (create with `enabled=false`); record `externalId` + `sfxAwsAccountArn`.
  2. Operator deploys IAM role + policy AWS-side using the rendered JSON.
  3. `PUT /v2/integration/{{id}}` with `roleArn` set + `enabled=true`.
"""
    return """# Authentication: SecurityToken flow (GovCloud / China)

- Auth mode: `security_token` (forced by GovCloud / China region selection).
- AWS access key ID: passed via `--aws-access-key-id-file` (chmod 600).
- AWS secret access key: passed via `--aws-secret-access-key-file` (chmod 600).
- Combined attached policy: `iam/iam-combined.json` (operator attaches to the
  IAM user that owns the access key).
- AWS does NOT provide FIPS-compliant tag-retrieval endpoints in GovCloud --
  do not include sensitive data in tags; Splunk Observability prefixes tags
  with `aws_tag_`.
"""


def _section_conn(spec: dict[str, Any]) -> str:
    conn = spec["connection"]
    return f"""# Connection

- Mode: `{conn['mode']}`
- pollRate: `{conn['poll_rate_seconds']}` seconds
  ({conn['poll_rate_seconds'] * 1000} ms in the raw REST payload)
- metadataPollRate: `{conn['metadata_poll_rate_seconds']}` seconds
- Adaptive polling: `{'enabled' if conn['adaptive_polling']['enabled'] else 'disabled'}`
  (inactiveMetricsPollRate = `{conn['adaptive_polling']['inactive_seconds']}` s)

References:
- https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/connect-via-polling
- https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/adaptive-polling
"""


def _section_regions_services(spec: dict[str, Any]) -> str:
    services = spec["services"]
    return f"""# Regions and services

- {len(spec['regions'])} regions: `{', '.join(spec['regions'])}`
- Services mode: `{services['mode']}`
- Explicit services: {len(services['explicit'])}
{chr(10).join(f'  - `{n}`' for n in services['explicit'])}
- collectOnlyRecommendedStats: `{services['collect_only_recommended_stats']}`
- metricStatsToSyncs: {len(services['metric_stats_to_syncs'])} entries
- namespaceSyncRules: {len(services['namespace_sync_rules'])} entries

CONFLICT NOTE: `services` and `namespaceSyncRules` are mutually exclusive at
the API level. The renderer rejected the spec if both were set.
"""


def _section_namespaces(spec: dict[str, Any]) -> str:
    custom = spec["custom_namespaces"]
    return f"""# Custom namespaces

- Simple list (`customCloudwatchNamespaces`): {len(custom['simple_list'])}
{chr(10).join(f'  - `{n}`' for n in custom['simple_list']) or '  (none)'}
- Sync rules (`customNamespaceSyncRules`): {len(custom['sync_rules'])}
- syncCustomNamespacesOnly: `{spec['sync_custom_namespaces_only']}`

CONFLICT NOTE: `customCloudwatchNamespaces` and `customNamespaceSyncRules`
are mutually exclusive at the API level. The renderer rejected the spec if
both were set.

CWAgent: present in the supported namespaces table, but only produces useful
data when AWS's CloudWatch Agent is actually installed and configured to
publish under that namespace AWS-side. For richer EC2 host metrics, see the
OTel collector handoff in `09-handoff.md`.
"""


def _section_metric_streams(spec: dict[str, Any]) -> str:
    streams = spec["metric_streams"]
    template = "StackSets" if streams["use_stack_sets"] else "regional"
    template_url = streams["cloudformation_template_url"] or (
        CFN_STACKSETS_URL if streams["use_stack_sets"] else CFN_REGIONAL_URL
    )
    return f"""# Metric Streams

- useMetricStreamsSync: `{streams['use_metric_streams_sync']}`
- metricStreamsManagedExternally: `{streams['managed_externally']}`
- namedToken: `{streams['named_token'] or '(default org token)'}`
- CloudFormation: `{streams['cloudformation']}` ({template})
- Template URL: `{template_url}`

CONSTRAINT: `metricStreamsManagedExternally=true` requires
`useMetricStreamsSync=true` per the canonical schema. The renderer enforced
this.

OTel payload: AWS-managed Metric Streams support OTel 0.7 and 1.0 only.

State machine (server-assigned, read-back via GET):
`ENABLED` -> `CANCELLING` -> `CANCELLATION_FAILED` (failure path) ->
`DISABLED` (success).
"""


def _section_private_link(spec: dict[str, Any]) -> str:
    pl = spec["private_link"]
    if not pl["enable"]:
        return "# AWS PrivateLink\n\nPrivateLink not enabled for this integration.\n"
    patterns = PRIVATELINK_PATTERNS_LEGACY if pl["domain"] == "legacy" else PRIVATELINK_PATTERNS_NEW
    rendered = "\n".join(
        f"- `{etype}`: `{patterns[etype].format(realm=spec['realm'])}`"
        for etype in pl["endpoint_types"]
    )
    return f"""# AWS PrivateLink

- Domain: `{pl['domain']}` (`{('signalfx.com' if pl['domain'] == 'legacy' else 'observability.splunkcloud.com')}`)
- Endpoint types:
{rendered}

PrivateLink only works within ONE AWS region. For cross-region workloads
(e.g. workload in `ap-south-1`, realm STS region `us-east-1`), VPC-peer the
two regions and activate PrivateLink in the destination region. See:
https://help.splunk.com/en/splunk-observability-cloud/manage-data/private-connectivity/private-connectivity-using-aws-privatelink

VPCE service-name overrides: see `references/privatelink.md` for the
per-realm table; pass `private_link.service_name_overrides` if Splunk has
republished the per-realm VPCE service names.
"""


def _section_multi_account(spec: dict[str, Any]) -> str:
    multi = spec["multi_account"]
    if not multi["enabled"]:
        return "# Multi-account\n\nSingle-account spec; multi_account.enabled=false.\n"
    return f"""# Multi-account / AWS Organizations

- Control account: `{multi['control_account_id']}`
- Member accounts: {len(multi['member_accounts'])}
{chr(10).join(f'  - `{a["aws_account_id"]}` ({a.get("label", "")})' for a in multi['member_accounts'])}
- StackSets template URL: `{multi['cfn_stacksets']['template_url'] or CFN_STACKSETS_URL}`
- Service-managed permissions: `{multi['cfn_stacksets']['use_org_service_managed']}`

When `use_org_service_managed=true`, AWS auto-creates
`AWSServiceRoleForCloudFormationStackSetsOrgAdmin` (control account) and
`AWSServiceRoleForCloudFormationStackSetsOrgMember` (member accounts).

When `use_org_service_managed=false`, the renderer emits the manual
`AWSCloudFormationStackSetAdministrationRole` (control) +
`AWSCloudFormationStackSetExecutionRole` (member) IAM JSON in
`iam/stacksets-admin.json` and `iam/stacksets-execution.json`.

NOTE: Splunk Observability Cloud has NO native multi-account aggregation;
this renders ONE Splunk Observability integration per member AWS account.
"""


def _section_validation(spec: dict[str, Any]) -> str:
    return """# Validation

Live validation strategy:

1. `--discover`: `GET /v2/integration?type=AWSCloudWatch`, write `current-state.json`.
2. Compare live vs spec field-by-field, emit `drift-report.md` with three buckets:
   - `safe-to-converge`: spec is more complete than live; `--apply` will set fields.
   - `operator-confirm-required`: live differs from spec on a field with side
     effects (e.g. flipping `useMetricStreamsSync`). `--apply` refuses without
     `--accept-drift <field>`.
   - `adopt-from-live`: live has fields the spec leaves unset. Use
     `--quickstart-from-live` to write `template.observed.yaml`.
3. `--doctor`: troubleshooting catalog -> `doctor-report.md`.

PUT body always strips read-back fields: `metricStreamsSyncState`,
`largeVolume`, `created`, `lastUpdated`, `creator`, `lastUpdatedBy`,
`lastUpdatedByName`, `createdByName`, `id`.
"""


def _section_handoff(spec: dict[str, Any]) -> str:
    h = spec["handoffs"]
    rows: list[str] = ["# Hand-offs"]
    if h["logs_via_splunk_ta_aws"]:
        rows.append(f"""
## AWS logs -> Splunk Add-on for AWS (Splunkbase 1876)

- Minimum version: `{SPLUNK_TA_AWS_MIN_VERSION}` (April 2026)
- v7.0+ absorbed Splunk Add-on for Amazon Security Lake; the renderer's
  preflight checks for `Splunk_TA_amazon_security_lake` and emits an
  uninstall step before upgrade.
- Apply: `bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id 1876`
- Then surface those logs in O11y via Log Observer Connect:
  `bash skills/splunk-observability-cloud-integration-setup/scripts/setup.sh --apply log_observer_connect`
""")
    if h["lambda_apm"]:
        rows.append(f"""
## Lambda APM

- Skill: `splunk-observability-aws-lambda-apm-setup`
- Splunk OpenTelemetry Lambda layer publisher: `{LAMBDA_LAYER_PUBLISHER_AWS_ACCOUNT}`
- Run: `bash skills/splunk-observability-aws-lambda-apm-setup/scripts/setup.sh --quickstart --accept-beta`
- Covers Node.js/Python/Java on x86_64 and arm64, exec-wrapper wiring, Secrets Manager/SSM token delivery, vendor/ADOT conflict detection, and Terraform/CloudFormation/AWS CLI variants.
- See: https://help.splunk.com/en/splunk-observability-cloud/manage-data/instrument-serverless-functions/instrument-serverless-functions/instrument-aws-lambda-functions
""")
    if h["dashboards"]:
        rows.append("""
## AWS dashboards

- `bash skills/splunk-observability-dashboard-builder/scripts/setup.sh --render-aws-dashboards`
- Pre-built AWS dashboards exist for every `AWS/*` namespace in the supported
  integrations table; use this hand-off only when you need custom rendering.
""")
    if h["detectors"]:
        rows.append("""
## AWS AutoDetect detectors

- `bash skills/splunk-observability-native-ops/scripts/setup.sh --apply autodetect-aws`
- Default-enabled detectors include: RDS free-disk, ALB 5xx, EC2 disk
  pressure, Route 53 health-checker latency, Route 53 unhealthy endpoint.
""")
    if h["otel_collector_for_ec2_eks"]:
        rows.append("""
## OTel collector for EC2 / EKS host telemetry

- `bash skills/splunk-observability-otel-collector-setup/scripts/setup.sh --render`
- Use this when CWAgent host metrics are insufficient or unavailable.
""")
    if not any(h.values()):
        rows.append("\nNo hand-offs requested in this spec.")
    return "\n".join(rows) + "\n"


# ---------------------------------------------------------------------------
# Apply scripts.
# ---------------------------------------------------------------------------


def render_apply_integration_sh(spec: dict[str, Any]) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

# Apply the AWSCloudWatch integration via POST/PUT /v2/integration.
# Reads the admin user API access token from $SPLUNK_O11Y_TOKEN_FILE (chmod 600).

SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
RENDER_DIR="$(cd "${{SCRIPT_DIR}}/.." && pwd)"
SKILL_DIR="$(cd "${{RENDER_DIR}}/../skills/{SKILL_NAME}" 2>/dev/null && pwd || \\
    cd "${{RENDER_DIR}}/../../skills/{SKILL_NAME}" 2>/dev/null && pwd || \\
    echo "")"

if [[ -z "${{SKILL_DIR}}" ]]; then
    echo "ERROR: cannot locate the {SKILL_NAME} skill scripts directory." >&2
    exit 2
fi

PYTHON_BIN="python3"
if [[ -x "${{RENDER_DIR}}/../.venv/bin/python" ]]; then
    PYTHON_BIN="${{RENDER_DIR}}/../.venv/bin/python"
fi

: "${{SPLUNK_O11Y_REALM:?must be set (e.g. {spec['realm']})}}"
: "${{SPLUNK_O11Y_TOKEN_FILE:?must point at a chmod-600 admin user API access token}}"

"${{PYTHON_BIN}}" "${{SKILL_DIR}}/scripts/aws_integration_api.py" \\
    --realm "${{SPLUNK_O11Y_REALM}}" \\
    --token-file "${{SPLUNK_O11Y_TOKEN_FILE}}" \\
    --state-dir "${{RENDER_DIR}}/state" \\
    --payload-file "${{RENDER_DIR}}/payloads/integration-create.json" \\
    upsert
"""


def render_apply_cloudformation_sh(spec: dict[str, Any]) -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

# Apply the CloudFormation Metric Streams stub. Operator-driven; this script
# just prints the commands from aws/cloudformation-stub.sh for review.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RENDER_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cat "${RENDER_DIR}/aws/cloudformation-stub.sh"
echo ""
echo "Review the commands above, then run them in a shell with AWS credentials."
"""


def render_apply_multi_account_sh(spec: dict[str, Any]) -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

# Apply the multi-account AWS Organizations CFN StackSets pattern.
# This is a render-only stub; operator deploys via aws-cli or the AWS console.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RENDER_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -f "${RENDER_DIR}/aws/cloudformation-stacksets-stub.sh" ]]; then
    cat "${RENDER_DIR}/aws/cloudformation-stacksets-stub.sh"
else
    echo "Multi-account not enabled in this spec." >&2
    exit 0
fi
"""


def render_handoff_logs_sh(spec: dict[str, Any]) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

# Hand-off: AWS log ingestion via the Splunk Add-on for AWS (Splunkbase 1876).
# AWS log ingestion does NOT go through Splunk Observability Cloud directly --
# enableLogsSync is deprecated. Logs land in Splunk Platform, then surface in
# O11y via Log Observer Connect.

PROJECT_ROOT="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/../../.." && pwd)"

echo "==> Step 1: Preflight uninstall Splunk_TA_amazon_security_lake (absorbed by"
echo "    Splunk_TA_AWS v7.0+; running both causes data duplication)."
bash "${{PROJECT_ROOT}}/skills/splunk-app-install/scripts/install_app.sh" --uninstall Splunk_TA_amazon_security_lake || true

echo "==> Step 2: Install Splunk Add-on for AWS (Splunkbase 1876, min v{SPLUNK_TA_AWS_MIN_VERSION})."
bash "${{PROJECT_ROOT}}/skills/splunk-app-install/scripts/install_app.sh" --source splunkbase --app-id 1876

echo "==> Step 3: Configure CloudTrail / VPC Flow Logs / S3 access logs in Splunk_TA_AWS"
echo "    (operator-driven; see Splunkbase docs for the per-source-type input config)."

echo "==> Step 4: Surface AWS logs in Splunk Observability via Log Observer Connect:"
echo "    bash ${{PROJECT_ROOT}}/skills/splunk-observability-cloud-integration-setup/scripts/setup.sh \\\\"
echo "      --apply log_observer_connect"
"""


def render_handoff_dashboards_sh(spec: dict[str, Any]) -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

# Hand-off: AWS dashboards via splunk-observability-dashboard-builder.

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

echo "==> Pre-built AWS dashboards exist for every AWS/* namespace in the supported"
echo "    integrations table -- they auto-populate when the integration is healthy."
echo "==> For custom dashboards on top of AWS data, render via:"
echo "    bash ${PROJECT_ROOT}/skills/splunk-observability-dashboard-builder/scripts/setup.sh --render"
echo "==> Reference for the AWS namespace catalog:"
echo "    https://help.splunk.com/en/splunk-observability-cloud/manage-data/available-data-sources/supported-integrations-in-splunk-observability-cloud/cloud-services-aws"
"""


def render_handoff_detectors_sh(spec: dict[str, Any]) -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

# Hand-off: AWS AutoDetect detectors via splunk-observability-native-ops.

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

echo "==> AWS AutoDetect detectors that ship enabled-by-default include:"
echo "      - AWS / RDS free disk space about to exhaust"
echo "      - AWS ALB sudden change in HTTP 5xx server errors"
echo "      - AWS EC2 disk utilization expected to reach the limit"
echo "      - AWS Route 53 health checkers' connection time over 9 seconds"
echo "      - AWS Route 53 unhealthy status of health check endpoint"
echo "==> For custom detectors on top of AWS data, render via:"
echo "    bash ${PROJECT_ROOT}/skills/splunk-observability-native-ops/scripts/setup.sh --render"
echo "==> Reference for the full AutoDetect detector list:"
echo "    https://help.splunk.com/en/splunk-observability-cloud/create-alerts-detectors-and-service-level-objectives/create-alerts-and-detectors/use-and-customize-autodetect-alerts-and-detectors/list-of-available-autodetect-detectors"
"""


def render_handoff_otel_sh(spec: dict[str, Any]) -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

# Hand-off: Splunk Distribution of OpenTelemetry Collector for EC2 / EKS host
# telemetry. CWAgent is built-in but produces fewer host metrics than the OTel
# collector running natively.

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

echo "==> Render the Splunk OTel collector deployment for EC2 / EKS:"
echo "    bash ${PROJECT_ROOT}/skills/splunk-observability-otel-collector-setup/scripts/setup.sh --render"
echo "==> Compared to CWAgent, the OTel collector ships richer host telemetry"
echo "    (cpu, memory, disk, network, processes) through OTLP and bypasses"
echo "    CloudWatch metric publishing costs."
"""


def render_handoff_lambda_sh(spec: dict[str, Any]) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

# Hand-off: AWS Lambda APM via the Splunk OpenTelemetry Lambda layer.
# Use the splunk-observability-aws-lambda-apm-setup skill.

echo "==> AWS Lambda APM is handled by splunk-observability-aws-lambda-apm-setup."
echo "    Splunk OTel Lambda layer publisher AWS account: {LAMBDA_LAYER_PUBLISHER_AWS_ACCOUNT}"
echo ""
echo "==> Quickstart:"
echo "    bash skills/splunk-observability-aws-lambda-apm-setup/scripts/setup.sh --quickstart --accept-beta"
echo ""
echo "==> Splunk doc:"
echo "    https://help.splunk.com/en/splunk-observability-cloud/manage-data/instrument-serverless-functions/instrument-serverless-functions/instrument-aws-lambda-functions"
"""


def render_validate_live_sh(spec: dict[str, Any]) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

# Live validation: GET /v2/integration?type=AWSCloudWatch and dump the
# matching integrations to current-state.json (with secrets redacted).

SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
RENDER_DIR="$(cd "${{SCRIPT_DIR}}/.." && pwd)"
SKILL_DIR="$(cd "${{RENDER_DIR}}/../skills/{SKILL_NAME}" 2>/dev/null && pwd || \\
    cd "${{RENDER_DIR}}/../../skills/{SKILL_NAME}" 2>/dev/null && pwd || \\
    echo "")"

PYTHON_BIN="python3"
if [[ -x "${{RENDER_DIR}}/../.venv/bin/python" ]]; then
    PYTHON_BIN="${{RENDER_DIR}}/../.venv/bin/python"
fi

: "${{SPLUNK_O11Y_REALM:?must be set}}"
: "${{SPLUNK_O11Y_TOKEN_FILE:?must point at a chmod-600 admin user API access token}}"

"${{PYTHON_BIN}}" "${{SKILL_DIR}}/scripts/aws_integration_api.py" \\
    --realm "${{SPLUNK_O11Y_REALM}}" \\
    --token-file "${{SPLUNK_O11Y_TOKEN_FILE}}" \\
    --state-dir "${{RENDER_DIR}}/state" \\
    discover --output "${{RENDER_DIR}}/current-state.json"
"""


# ---------------------------------------------------------------------------
# Top-level render.
# ---------------------------------------------------------------------------


def render(
    spec: dict[str, Any],
    output_dir: Path,
    *,
    explain: bool = False,
    list_namespaces: bool = False,
    list_recommended_stats: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    # Clear stale subdirs so re-renders don't carry leftover state.
    for sub in ("payloads", "scripts", "state", "aws", "iam", "support-tickets"):
        target = output_dir / sub
        if target.exists():
            shutil.rmtree(target)

    coverage = coverage_for(spec)

    write_text(output_dir / "README.md", render_readme(spec))
    write_text(output_dir / "architecture.mmd", render_architecture_mmd(spec))

    for filename, section in NUMBERED_PLAN_FILES:
        write_text(output_dir / filename, render_section_md(section, spec, coverage))

    write_text(
        output_dir / "coverage-report.json",
        json.dumps(
            {
                "api_version": API_VERSION,
                "realm": spec["realm"],
                "integration_name": spec["integration_name"],
                "coverage": coverage,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ) + "\n",
    )

    apply_plan = {
        "api_version": API_VERSION,
        "ordered_steps": [
            {
                "step": "iam.trust_policy",
                "idempotency_key": f"iam-trust:{spec['authentication'].get('aws_account_id', 'security-token')}",
                "coverage": coverage["authentication.iam_policy"]["status"],
            },
            {
                "step": "integration.upsert",
                "idempotency_key": f"integration-upsert:{spec['integration_name']}",
                "coverage": coverage["authentication.integration_create"]["status"],
            },
            {
                "step": "metric_streams.cfn",
                "idempotency_key": f"cfn:{spec['integration_name']}",
                "coverage": coverage.get("metric_streams.cloudformation", {}).get("status", "not_applicable"),
            },
            {
                "step": "validation.discover",
                "idempotency_key": f"discover:{spec['integration_name']}",
                "coverage": coverage["validation.live_get"]["status"],
            },
        ],
    }
    write_text(output_dir / "apply-plan.json", json.dumps(apply_plan, indent=2) + "\n")

    # Payloads.
    payloads_dir = output_dir / "payloads"
    payloads_dir.mkdir(parents=True, exist_ok=True)
    payload = render_rest_payload(spec)
    write_text(payloads_dir / "integration-create.json", json.dumps(payload, indent=2) + "\n")
    write_text(
        payloads_dir / "api-payload-shapes.json",
        json.dumps(
            {
                "POST /v2/integration": payload,
                "PUT /v2/integration/{id}": {**payload, "enabled": True, "id": "${INTEGRATION_ID}"},
                "GET /v2/integration?type=AWSCloudWatch": {"_method_only": True},
                "DELETE /v2/integration/{id}": {"_method_only": True},
            },
            indent=2,
        ) + "\n",
    )

    # IAM.
    iam_dir = output_dir / "iam"
    iam_dir.mkdir(parents=True, exist_ok=True)
    if spec["authentication"]["mode"] == "external_id":
        write_text(iam_dir / "iam-trust.json", json.dumps(render_iam_trust_policy(spec), indent=2) + "\n")
    write_text(iam_dir / "iam-foundation.json", json.dumps(render_iam_foundation_policy(), indent=2) + "\n")
    write_text(iam_dir / "iam-polling.json", json.dumps(render_iam_polling_policy(), indent=2) + "\n")
    write_text(iam_dir / "iam-streams.json", json.dumps(render_iam_streams_policy(), indent=2) + "\n")
    write_text(iam_dir / "iam-tag-sync.json", json.dumps(render_iam_tag_sync_policy(), indent=2) + "\n")
    write_text(iam_dir / "iam-combined.json", json.dumps(render_iam_combined_policy(spec), indent=2) + "\n")
    if spec["multi_account"]["enabled"] and not spec["multi_account"]["cfn_stacksets"]["use_org_service_managed"]:
        write_text(
            iam_dir / "stacksets-admin.json",
            json.dumps({
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Action": ["sts:AssumeRole"],
                    "Resource": ["arn:*:iam::*:role/AWSCloudFormationStackSetExecutionRole"],
                }],
            }, indent=2) + "\n",
        )

    # AWS-side templates and Terraform.
    aws_dir = output_dir / "aws"
    aws_dir.mkdir(parents=True, exist_ok=True)
    write_text(aws_dir / "cloudformation-stub.sh", render_cfn_stub(spec))
    if spec["multi_account"]["enabled"]:
        ms_spec = dict(spec)
        ms_spec["metric_streams"] = dict(spec["metric_streams"])
        ms_spec["metric_streams"]["use_stack_sets"] = True
        write_text(aws_dir / "cloudformation-stacksets-stub.sh", render_cfn_stub(ms_spec))
    write_text(aws_dir / "main.tf", render_terraform_main(spec))
    write_text(
        aws_dir / "iam-combined.json",
        json.dumps(render_iam_combined_policy(spec), indent=2) + "\n",
    )

    # Apply scripts.
    scripts_dir = output_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    write_text(scripts_dir / "apply-integration.sh", render_apply_integration_sh(spec))
    os.chmod(scripts_dir / "apply-integration.sh", 0o755)
    write_text(scripts_dir / "apply-cloudformation.sh", render_apply_cloudformation_sh(spec))
    os.chmod(scripts_dir / "apply-cloudformation.sh", 0o755)
    write_text(scripts_dir / "apply-multi-account.sh", render_apply_multi_account_sh(spec))
    os.chmod(scripts_dir / "apply-multi-account.sh", 0o755)
    write_text(scripts_dir / "validate-live.sh", render_validate_live_sh(spec))
    os.chmod(scripts_dir / "validate-live.sh", 0o755)

    # Hand-off driver scripts (one per enabled handoff).
    if spec["handoffs"]["logs_via_splunk_ta_aws"]:
        write_text(scripts_dir / "handoff-logs-splunk-ta-aws.sh", render_handoff_logs_sh(spec))
        os.chmod(scripts_dir / "handoff-logs-splunk-ta-aws.sh", 0o755)
    if spec["handoffs"]["dashboards"]:
        write_text(scripts_dir / "handoff-dashboards.sh", render_handoff_dashboards_sh(spec))
        os.chmod(scripts_dir / "handoff-dashboards.sh", 0o755)
    if spec["handoffs"]["detectors"]:
        write_text(scripts_dir / "handoff-detectors.sh", render_handoff_detectors_sh(spec))
        os.chmod(scripts_dir / "handoff-detectors.sh", 0o755)
    if spec["handoffs"]["otel_collector_for_ec2_eks"]:
        write_text(scripts_dir / "handoff-otel-collector.sh", render_handoff_otel_sh(spec))
        os.chmod(scripts_dir / "handoff-otel-collector.sh", 0o755)
    if spec["handoffs"]["lambda_apm"]:
        write_text(scripts_dir / "handoff-lambda-apm.sh", render_handoff_lambda_sh(spec))
        os.chmod(scripts_dir / "handoff-lambda-apm.sh", 0o755)

    # State placeholders (renderer never writes a real apply record; the
    # API client populates these on apply).
    state_dir = output_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "apply-state.json"
    write_text(state_path, json.dumps({"steps": []}, indent=2) + "\n")
    os.chmod(state_path, 0o600)
    write_text(
        state_dir / "idempotency-keys.json",
        json.dumps([s["idempotency_key"] for s in apply_plan["ordered_steps"]], indent=2) + "\n",
    )

    # Support tickets (rendered conditionally).
    tickets_dir = output_dir / "support-tickets"
    tickets_dir.mkdir(parents=True, exist_ok=True)
    if spec["multi_account"]["enabled"] and len(spec["multi_account"]["member_accounts"]) > 5:
        write_text(
            tickets_dir / "many-member-accounts.md",
            f"""# Support ticket: many member accounts

This spec configures `{len(spec['multi_account']['member_accounts'])}` member
accounts. Splunk Observability Cloud has no documented hard limit, but the
~100-integration soft cap may apply per org. Open a Splunk Observability
Cloud support case to confirm capacity before applying.
""",
        )
    if spec["regions"] != [] and len(spec["regions"]) > 5 and not spec["guards"]["enable_check_large_volume"]:
        write_text(
            tickets_dir / "large-volume-guard-disabled.md",
            """# Support ticket: 100k-metric guard disabled with broad coverage

You have selected many regions AND disabled `enableCheckLargeVolume`. The
100k-metric auto-deactivate guard is OFF. Confirm with Splunk Observability
Cloud support that you have capacity before applying.
""",
        )

    result: dict[str, Any] = {
        "output_dir": str(output_dir),
        "coverage_summary": {
            "total": len(coverage),
            "by_status": {
                status: sum(1 for v in coverage.values() if v["status"] == status)
                for status in ("api_apply", "api_validate", "deeplink", "handoff", "not_applicable")
            },
        },
        "files": sorted(p.relative_to(output_dir).as_posix() for p in output_dir.rglob("*") if p.is_file()),
    }
    if explain:
        result["explain"] = [
            f"{step['step']} ({step['coverage']}; key={step['idempotency_key']})"
            for step in apply_plan["ordered_steps"]
        ]
    if list_namespaces:
        result["namespaces"] = list(KNOWN_NAMESPACES)
    if list_recommended_stats:
        result["recommended_stats"] = RECOMMENDED_STATS_SAMPLE
    return result


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--realm", default="")
    parser.add_argument("--privatelink-domain", choices=("legacy", "new"), default="")
    parser.add_argument("--cfn-template-url", default="")
    parser.add_argument("--explain", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--list-namespaces", action="store_true")
    parser.add_argument("--list-recommended-stats", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    spec_path = Path(args.spec)
    if not spec_path.is_file():
        print(f"FAIL: spec file not found: {spec_path}", flush=True)
        return 2
    try:
        spec = load_spec(spec_path)
        if args.privatelink_domain:
            spec.setdefault("private_link", {})
            if not isinstance(spec["private_link"], dict):
                raise RenderError("private_link must be a mapping")
            spec["private_link"]["domain"] = args.privatelink_domain
        if args.cfn_template_url:
            spec.setdefault("metric_streams", {})
            if not isinstance(spec["metric_streams"], dict):
                raise RenderError("metric_streams must be a mapping")
            spec["metric_streams"]["cloudformation_template_url"] = args.cfn_template_url
        spec = validate_spec(spec, realm_override=args.realm or None)
    except RenderError as exc:
        print(f"FAIL: {exc}", flush=True)
        return 2

    output_dir = Path(args.output_dir).resolve()
    try:
        result = render(
            spec,
            output_dir,
            explain=args.explain,
            list_namespaces=args.list_namespaces,
            list_recommended_stats=args.list_recommended_stats,
        )
    except RenderError as exc:
        print(f"FAIL: {exc}", flush=True)
        return 2

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        summary = result["coverage_summary"]
        by_status = ", ".join(f"{k}={v}" for k, v in summary["by_status"].items())
        print(f"render: OK -> {result['output_dir']} ({summary['total']} coverage entries; {by_status})")
        if args.explain:
            print()
            print("Apply plan (explain):")
            for line in result.get("explain", []):
                print(f"  - {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
