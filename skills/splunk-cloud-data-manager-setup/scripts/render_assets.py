#!/usr/bin/env python3
"""Render Splunk Cloud Data Manager setup artifacts."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shlex
import stat
import sys
from pathlib import Path
from typing import Any

try:  # pragma: no cover - CI may have PyYAML; local repo checks may not.
    import yaml
except ModuleNotFoundError:  # pragma: no cover
    yaml = None


SKILL_NAME = "splunk-cloud-data-manager-setup"
DEFAULT_OUTPUT_DIR = "splunk-cloud-data-manager-rendered"
ALLOWED_COVERAGE_STATUSES = {
    "ui_handoff",
    "artifact_validate",
    "artifact_apply",
    "splunk_validate",
    "cloud_validate",
    "handoff",
    "not_applicable",
}
HEC_ACK_REQUIRED_SOURCES = [
    "CloudTrail",
    "GuardDuty",
    "SecurityHub",
    "IAM Access Analyzer",
    "CloudWatch Logs",
]
HEC_SPECIAL_TOKENS = {
    "aws_s3": "scdm-scs-hec-token",
    "aws_s3_promote": "scdm-scs-promote-hec-token",
    "azure_event_hub": "scdm-scs-hec-token",
    "crowdstrike_fdr": "scdm-scs-hec-token",
}
HEC_TOKEN_NAMES = {
    "aws_cloudtrail": "data-manager-cloudtrail_<input_id>",
    "aws_guardduty": "data-manager-guardduty_<input_id>",
    "aws_security_hub": "data-manager-security_<input_id>",
    "aws_iam_access_analyzer": "data-manager-iam-aa_<input_id>",
    "aws_iam_credential_reports_and_metadata": "data-manager-iam-cr_<input_id>",
    "aws_cloudwatch_logs": "data-manager-cwl_<input_id>",
    "aws_lambda": "data-manager-lambda_<input_id>",
    "aws_s3": "scdm-scs-hec-token",
    "aws_s3_promote": "scdm-scs-promote-hec-token",
    "azure_entra_id": "data-manager-azure-ad_<input_id>",
    "azure_activity_logs": "data-manager-azure-activity_<input_id>",
    "azure_event_hub": "scdm-scs-hec-token",
    "gcp": "data-manager-gcp-cloud-logging_<input_id>",
    "crowdstrike": "scdm-scs-hec-token",
}
AWS_ORG_OU_SUPPORTED_SOURCE_FAMILIES = {
    "cloudtrail",
    "security_hub",
    "guardduty",
    "iam_access_analyzer",
    "iam_credential_report",
    "metadata",
    "cloudwatch_logs_api_gateway",
    "cloudwatch_logs_cloudhsm",
    "cloudwatch_logs_documentdb",
    "cloudwatch_logs_eks",
    "cloudwatch_logs_lambda",
    "cloudwatch_logs_rds",
}
AWS_INGESTION_REGIONS = {
    "us-east-1",
    "us-east-2",
    "us-west-1",
    "us-west-2",
    "ca-central-1",
    "sa-east-1",
    "eu-central-1",
    "eu-west-1",
    "eu-west-2",
    "eu-south-1",
    "eu-west-3",
    "eu-north-1",
    "me-south-1",
    "af-south-1",
    "ap-northeast-1",
    "ap-northeast-2",
    "ap-south-1",
    "ap-southeast-1",
    "ap-southeast-2",
    "ap-east-1",
}
AZURE_INGESTION_REGIONS = {
    "southafricanorth",
    "eastasia",
    "australiaeast",
    "australiasoutheast",
    "brazilsouth",
    "canadacentral",
    "canadaeast",
    "northeurope",
    "westeurope",
    "francecentral",
    "germanywestcentral",
    "centralindia",
    "westindia",
    "japaneast",
    "japanwest",
    "koreacentral",
    "norwayeast",
    "switzerlandnorth",
    "uaenorth",
    "uksouth",
    "centralus",
    "eastus",
    "eastus2",
    "northcentralus",
    "southcentralus",
    "westcentralus",
    "westus",
    "westus2",
}
GCP_DATAFLOW_REGIONS = {
    "europe-west6",
    "europe-west3",
    "europe-west2",
    "europe-west1",
    "europe-southwest1",
    "europe-north1",
    "europe-central2",
    "australia-southeast2",
    "australia-southeast1",
    "asia-southeast2",
    "asia-southeast1",
    "asia-south2",
    "asia-south1",
    "asia-northeast3",
    "asia-northeast2",
    "asia-northeast1",
    "asia-east2",
    "asia-east1",
    "us-south1",
    "us-west4",
    "us-west3",
    "us-west2",
    "us-west1",
    "us-east5",
    "us-east4",
    "us-east1",
    "us-central1",
    "southamerica-west1",
    "southamerica-east1",
    "northamerica-northeast2",
    "northamerica-northeast1",
}
CROWDSTRIKE_FDR_REGIONS = {"US-1", "US-2", "EU-1"}
CROWDSTRIKE_REGION_TO_AWS_REGION = {
    "US-1": "us-west-1",
    "US-2": "us-west-2",
    "EU-1": "eu-central-1",
}
UNSUPPORTED_CLAIM_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"POST\s+/.*data.?manager.*input",
        r"PUT\s+/.*data.?manager.*input",
        r"terraform\s+resource\s+.*data.?manager",
        r"splunk.?cloud.?data.?manager.?input.?resource",
        r"global\s+HEC\s+ACK",
    )
]
SECRET_FIELD_RE = re.compile(
    r"(password|secret|api[_-]?key|access[_-]?key|private[_-]?key|bearer|session[_-]?token)",
    re.IGNORECASE,
)

SOURCE_CATALOG = {
    "aws": [
        "aws:s3:accesslogs",
        "aws:cloudtrail",
        "aws:cloudwatch:guardduty",
        "aws:cloudwatchlogs",
        "aws:accessanalyzer:finding",
        "aws:iam:credentialreport",
        "aws:metadata",
        "aws:securityhub:finding",
        "aws:cloudfront:accesslogs",
        "aws:elb:accesslogs",
    ],
    "azure": [
        "azure:monitor:aad",
        "azure:monitor:activity",
        "azure:monitor:resource",
        "mscs:azure:eventhub",
    ],
    "gcp": [
        "google:gcp:pubsub:access_transparency",
        "google:gcp:pubsub:audit:admin_activity",
        "google:gcp:pubsub:audit:data_access",
        "google:gcp:pubsub:audit:policy_denied",
        "google:gcp:pubsub:audit:system_event",
    ],
    "crowdstrike": [
        "crowdstrike:events:sensor",
        "crowdstrike:events:external",
        "crowdstrike:events:ztha",
        "crowdstrike:inventory:aidmaster",
        "crowdstrike:inventory:managedassets",
        "crowdstrike:inventory:notmanaged",
        "crowdstrike:inventory:appinfo",
        "crowdstrike:inventory:userinfo",
    ],
}

DATA_SOURCE_FAMILIES = {
    "aws": [
        "Amazon API Gateway",
        "AWS CloudHSM",
        "Amazon Web Services (AWS) CloudTrail",
        "Amazon DocumentDB",
        "Amazon Elastic Kubernetes Service (Amazon EKS)",
        "Amazon GuardDuty",
        "AWS Lambda",
        "AWS Metadata - AWS Identity and Access Management (IAM) Users",
        "AWS Metadata - Elastic Compute Cloud (Amazon EC2) Instances",
        "AWS Metadata - EC2 Security Groups",
        "AWS Metadata - Network ACLs",
        "AWS IAM Access Analyzer",
        "AWS IAM Credential Report",
        "Amazon Relational Database Service (Amazon RDS)",
        "AWS Security Hub",
        "AWS Virtual Private Cloud (VPC) Flow Logs",
        "AWS CloudTrail (S3)",
        "AWS S3 access logs (S3)",
        "AWS Elastic Load Balancer (ELB) access logs (S3)",
        "AWS CloudFront (CF) access logs (S3)",
        "Amazon CloudWatch Logs - Custom Logs",
        "Amazon S3 custom source types",
        "AWS S3 Promote historical data",
    ],
    "azure": [
        "Microsoft Entra ID",
        "Microsoft Azure Activity Logs",
        "Microsoft Azure Event Hubs",
        "Azure Monitor resource logs through Event Hubs",
        "Azure Event Hub custom source types",
    ],
    "gcp": [
        "GCP Audit Logs - Admin Activity",
        "GCP Audit Logs - Data Access",
        "GCP Audit Logs - Policy Denied",
        "GCP Audit Logs - System Event",
        "GCP Access Transparency Logs",
    ],
    "crowdstrike": [
        "Sensor events",
        "External security events",
        "Zero Trust Host Assessment events",
        "Aidmaster inventory",
        "Managed assets inventory",
        "Not managed assets inventory",
        "Application inventory",
        "User inventory",
    ],
}


class RenderError(RuntimeError):
    """Raised for render-blocking validation errors."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--spec",
        default=str(Path(__file__).resolve().parents[1] / "template.example"),
        help="YAML or JSON non-secret Data Manager spec.",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Rendered artifact directory.",
    )
    parser.add_argument(
        "--mode",
        choices=("render", "doctor", "status", "check-rendered"),
        default="render",
    )
    return parser.parse_args()


def strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    for index, char in enumerate(line):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            return line[:index]
    return line


def yaml_scalar(value: str) -> Any:
    value = value.strip()
    if value in {"", '""', "''"}:
        return ""
    if value == "[]":
        return []
    if value == "{}":
        return {}
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none", "~"}:
        return None
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def next_yaml_container(lines: list[str], start_index: int, indent: int) -> Any:
    for raw in lines[start_index + 1 :]:
        line = strip_comment(raw).rstrip()
        if not line.strip():
            continue
        next_indent = len(line) - len(line.lstrip(" "))
        if next_indent <= indent:
            return {}
        return [] if line.strip().startswith("- ") else {}
    return {}


def parse_minimal_yaml(text: str) -> dict[str, Any]:
    """Parse the limited YAML subset used by this skill's template."""

    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    lines = text.splitlines()
    for index, raw in enumerate(lines):
        line = strip_comment(raw).rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        content = line.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise RenderError(f"Invalid indentation near line {index + 1}: {raw}")
        parent = stack[-1][1]
        if content.startswith("- "):
            if not isinstance(parent, list):
                raise RenderError(f"List item without list parent near line {index + 1}")
            parent.append(yaml_scalar(content[2:]))
            continue
        if ":" not in content:
            raise RenderError(f"Unsupported YAML near line {index + 1}: {raw}")
        key, raw_value = content.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if not isinstance(parent, dict):
            raise RenderError(f"Mapping entry inside scalar list near line {index + 1}")
        if value:
            parent[key] = yaml_scalar(value)
        else:
            container = next_yaml_container(lines, index, indent)
            parent[key] = container
            stack.append((indent, container))
    return root


def load_spec(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        loaded = json.loads(text)
    elif yaml is not None:
        loaded = yaml.safe_load(text) or {}
    else:
        loaded = parse_minimal_yaml(text)
    if not isinstance(loaded, dict):
        raise RenderError("Spec root must be a mapping.")
    return loaded


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def enabled(spec: dict[str, Any], provider: str) -> bool:
    return bool_value(as_dict(spec.get(provider)).get("enabled"))


def iac_apply_enabled(iac: dict[str, Any], key: str) -> bool:
    return bool_value(iac.get("apply_enabled")) and bool_value(iac.get(key))


def validate_no_raw_secrets(value: Any, path: tuple[str, ...] = ()) -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = path + (str(key),)
            lowered = str(key).lower()
            is_file_ref = lowered.endswith("_file") or lowered.endswith("_path")
            is_allowed_name = lowered in {
                "expected_tokens",
                "validate_tokens",
                "ack_required_sources",
            }
            if (
                SECRET_FIELD_RE.search(lowered)
                and not is_file_ref
                and not is_allowed_name
                and child not in ("", None, [])
            ):
                errors.append(".".join(child_path))
            errors.extend(validate_no_raw_secrets(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(validate_no_raw_secrets(child, path + (str(index),)))
    return errors


def collect_findings(spec: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    splunk_cloud = as_dict(spec.get("splunk_cloud"))
    data_manager = as_dict(spec.get("data_manager"))
    hec = as_dict(spec.get("hec"))
    aws = as_dict(spec.get("aws"))
    azure = as_dict(spec.get("azure"))
    gcp = as_dict(spec.get("gcp"))
    crowdstrike = as_dict(spec.get("crowdstrike"))
    iac = as_dict(spec.get("iac"))
    migration = as_dict(spec.get("migration"))

    if not bool_value(splunk_cloud.get("primary_search_head", False)):
        findings.append(
            {
                "severity": "ERROR",
                "area": "splunk_cloud",
                "message": "Data Manager is available only on the primary search head.",
            }
        )
    roles = {str(role) for role in as_list(splunk_cloud.get("roles"))}
    if roles.isdisjoint({"admin", "sc_admin"}) and not bool_value(
        splunk_cloud.get("capabilities_confirmed")
    ):
        findings.append(
            {
                "severity": "WARN",
                "area": "splunk_cloud",
                "message": "No admin/sc_admin role or documented capability-set confirmation was provided.",
            }
        )
    if not bool_value(hec.get("enabled", False)):
        findings.append(
            {
                "severity": "ERROR",
                "area": "hec",
                "message": "HEC must be enabled before Data Manager inputs can ingest.",
            }
        )
    input_limit = data_manager.get("input_limit", 5000)
    planned_input_count = data_manager.get("planned_input_count", 0)
    if isinstance(input_limit, int) and input_limit != 5000:
        findings.append(
            {
                "severity": "WARN",
                "area": "data_manager",
                "message": "Data Manager 1.16 documents a 5000 input limit; verify any override.",
            }
        )
    if (
        isinstance(input_limit, int)
        and isinstance(planned_input_count, int)
        and planned_input_count > input_limit
    ):
        findings.append(
            {
                "severity": "WARN",
                "area": "data_manager",
                "message": "Planned Data Manager input count exceeds the configured input limit.",
            }
        )
    if enabled(spec, "aws"):
        aws_regions = {str(value) for value in as_list(aws.get("regions")) if str(value)}
        unsupported_regions = sorted(aws_regions - AWS_INGESTION_REGIONS)
        if unsupported_regions:
            findings.append(
                {
                    "severity": "ERROR",
                    "area": "aws",
                    "message": "AWS ingestion region is not listed in Data Manager 1.16 supported regions: "
                    + ", ".join(unsupported_regions),
                }
            )
        aws_sources = {str(value) for value in as_list(aws.get("source_families"))}
        org = as_dict(aws.get("organizations"))
        if bool_value(org.get("enabled")):
            unsupported = sorted(
                source
                for source in aws_sources
                if source not in AWS_ORG_OU_SUPPORTED_SOURCE_FAMILIES
            )
            if unsupported:
                findings.append(
                    {
                        "severity": "ERROR",
                        "area": "aws",
                        "message": "AWS Organizations/OUs are not documented for: "
                        + ", ".join(unsupported),
                    }
                )
            if not bool_value(org.get("checked_for_overlap")):
                findings.append(
                    {
                        "severity": "WARN",
                        "area": "aws",
                        "message": "Run an account/input overlap check before Organizations/OUs onboarding.",
                    }
                )
        s3_promote = as_dict(aws.get("s3_promote"))
        if bool_value(s3_promote.get("enabled")) and not (
            bool_value(s3_promote.get("ingest_actions_reviewed"))
            and bool_value(s3_promote.get("ingest_processor_reviewed"))
        ):
            findings.append(
                {
                    "severity": "WARN",
                    "area": "aws",
                    "message": "Review ingest actions and Ingest Processor routing before S3 Promote.",
                }
            )
    if enabled(spec, "azure"):
        azure_region = str(azure.get("event_hub_region") or "")
        if azure_region and azure_region.lower() not in AZURE_INGESTION_REGIONS:
            findings.append(
                {
                    "severity": "ERROR",
                    "area": "azure",
                    "message": "Azure Event Hub region is not listed in Data Manager 1.16 supported regions: "
                    + azure_region,
                }
            )
        mscs = as_dict(azure.get("mscs_migration"))
        wants_migration = bool_value(mscs.get("enabled")) or bool_value(
            migration.get("azure_event_hubs_from_mscs")
        )
        if wants_migration and not bool_value(mscs.get("duplicate_migration_checked")):
            findings.append(
                {
                    "severity": "ERROR",
                    "area": "azure",
                    "message": "Duplicate Azure Event Hub migration check is required.",
                }
            )
        if wants_migration and not (
            bool_value(mscs.get("inputs_inactive")) and bool_value(mscs.get("health_ready"))
        ):
            findings.append(
                {
                    "severity": "WARN",
                    "area": "azure",
                    "message": "MSCS Event Hub inputs should be inactive and Ready before migration.",
                }
            )
    if enabled(spec, "gcp"):
        dataflow_region = str(gcp.get("dataflow_region") or "")
        if dataflow_region and dataflow_region not in GCP_DATAFLOW_REGIONS:
            findings.append(
                {
                    "severity": "ERROR",
                    "area": "gcp",
                    "message": "GCP Dataflow region is not listed in Data Manager 1.16 supported regions: "
                    + dataflow_region,
                }
            )
        if not bool_value(gcp.get("overlap_checked")):
            findings.append(
                {
                    "severity": "WARN",
                    "area": "gcp",
                    "message": "Check GCP project/folder/org overlap before Data Access or Access Transparency onboarding.",
                }
            )
    if enabled(spec, "crowdstrike"):
        crowdstrike_region = str(crowdstrike.get("region") or "").upper()
        if crowdstrike_region and crowdstrike_region not in CROWDSTRIKE_FDR_REGIONS:
            findings.append(
                {
                    "severity": "ERROR",
                    "area": "crowdstrike",
                    "message": "CrowdStrike FDR region must be one of US-1, US-2, or EU-1.",
                }
            )
        sqs_queue_url = str(crowdstrike.get("sqs_queue_url") or "")
        sqs_region_match = re.search(r"\.([a-z]{2}-[a-z]+-\d)\.amazonaws\.com", sqs_queue_url)
        mapped_region = CROWDSTRIKE_REGION_TO_AWS_REGION.get(crowdstrike_region)
        if sqs_region_match and mapped_region and sqs_region_match.group(1) != mapped_region:
            findings.append(
                {
                    "severity": "WARN",
                    "area": "crowdstrike",
                    "message": "CrowdStrike FDR region "
                    + crowdstrike_region
                    + " maps to AWS region "
                    + mapped_region
                    + ", but the SQS URL uses "
                    + sqs_region_match.group(1)
                    + ".",
                }
            )
        if not bool_value(crowdstrike.get("single_account_confirmed")):
            findings.append(
                {
                    "severity": "ERROR",
                    "area": "crowdstrike",
                    "message": "CrowdStrike Data Manager onboarding is single-account only.",
                }
            )
        event_types = {str(value).lower() for value in as_list(crowdstrike.get("event_types"))}
        if "sensor" not in event_types:
            findings.append(
                {
                    "severity": "ERROR",
                    "area": "crowdstrike",
                    "message": "CrowdStrike sensor events are mandatory.",
                }
            )
        if not crowdstrike.get("aws_secret_access_key_file"):
            findings.append(
                {
                    "severity": "ERROR",
                    "area": "crowdstrike",
                    "message": "CrowdStrike FDR secret access key must be supplied by file path.",
                }
            )
        if not crowdstrike.get("aws_access_key_id_file"):
            findings.append(
                {
                    "severity": "ERROR",
                    "area": "crowdstrike",
                    "message": "CrowdStrike FDR access key ID must be supplied by file path.",
                }
            )
    if not bool_value(iac.get("splunk_scp_provider_adjacent_only", True)):
        findings.append(
            {
                "severity": "ERROR",
                "area": "iac",
                "message": "splunk/scp is adjacent only; it does not provide Data Manager input CRUD.",
            }
        )
    if bool_value(iac.get("gcp_terraform_apply_enabled")) and bool_value(
        iac.get("gcp_terraform_destroy_enabled")
    ):
        findings.append(
            {
                "severity": "ERROR",
                "area": "iac",
                "message": "GCP Terraform apply and destroy cannot both be enabled in one run.",
            }
        )
    provider_apply_keys = (
        "aws_cloudformation_apply_enabled",
        "azure_arm_apply_enabled",
        "gcp_terraform_apply_enabled",
        "gcp_terraform_destroy_enabled",
    )
    if not bool_value(iac.get("apply_enabled")) and any(
        bool_value(iac.get(key)) for key in provider_apply_keys
    ):
        findings.append(
            {
                "severity": "WARN",
                "area": "iac",
                "message": "Provider apply flags are ignored until iac.apply_enabled is true.",
            }
        )
    return findings


def coverage_entry(
    feature: str,
    status: str,
    provider: str = "core",
    detail: str = "",
) -> dict[str, str]:
    if status not in ALLOWED_COVERAGE_STATUSES:
        raise RenderError(f"Unsupported coverage status {status!r} for {feature}.")
    return {
        "provider": provider,
        "feature": feature,
        "coverage_status": status,
        "detail": detail,
    }


def build_coverage(spec: dict[str, Any]) -> list[dict[str, str]]:
    iac = as_dict(spec.get("iac"))
    rows = [
        coverage_entry(
            "Data Manager input creation",
            "ui_handoff",
            detail="Splunk Cloud UI handoff; no unsupported private API is claimed.",
        ),
        coverage_entry("Splunk Cloud readiness", "splunk_validate"),
        coverage_entry("HEC enabled/token/ACK readiness", "splunk_validate"),
        coverage_entry("Index existence and role access", "splunk_validate"),
        coverage_entry("Source catalog and HEC ACK catalog", "artifact_validate"),
        coverage_entry("Splunk Cloud ACS allowlist prerequisite handoff", "handoff"),
        coverage_entry("Splunk HEC service prerequisite handoff", "handoff"),
        coverage_entry("Splunk Add-on prerequisite handoff", "handoff"),
    ]
    if enabled(spec, "aws"):
        rows.extend(
            [
                coverage_entry("AWS source catalog", "artifact_validate", "aws"),
                coverage_entry("AWS CloudFormation template validation", "artifact_validate", "aws"),
                coverage_entry(
                    "AWS CloudFormation stack apply",
                    "artifact_apply"
                    if iac_apply_enabled(iac, "aws_cloudformation_apply_enabled")
                    else "artifact_validate",
                    "aws",
                ),
                coverage_entry("AWS StackSet execution handoff", "handoff", "aws"),
                coverage_entry("AWS Organizations/OUs overlap check", "cloud_validate", "aws"),
                coverage_entry("AWS S3 Promote guardrails", "ui_handoff", "aws"),
                coverage_entry("Amazon Security Lake Data Manager classification", "handoff", "aws"),
            ]
        )
    else:
        rows.append(coverage_entry("AWS onboarding", "not_applicable", "aws"))
    if enabled(spec, "azure"):
        rows.extend(
            [
                coverage_entry("Azure ARM template what-if", "artifact_validate", "azure"),
                coverage_entry(
                    "Azure ARM template apply",
                    "artifact_apply"
                    if iac_apply_enabled(iac, "azure_arm_apply_enabled")
                    else "artifact_validate",
                    "azure",
                ),
                coverage_entry("Azure Event Hubs MSCS migration", "ui_handoff", "azure"),
            ]
        )
    else:
        rows.append(coverage_entry("Azure onboarding", "not_applicable", "azure"))
    if enabled(spec, "gcp"):
        rows.extend(
            [
                coverage_entry("GCP source catalog", "artifact_validate", "gcp"),
                coverage_entry("GCP Terraform template validation", "artifact_validate", "gcp"),
                coverage_entry(
                    "GCP Terraform apply/destroy",
                    "artifact_apply"
                    if (
                        iac_apply_enabled(iac, "gcp_terraform_apply_enabled")
                        or iac_apply_enabled(iac, "gcp_terraform_destroy_enabled")
                    )
                    else "artifact_validate",
                    "gcp",
                ),
                coverage_entry("GCP scope overlap check", "cloud_validate", "gcp"),
            ]
        )
    else:
        rows.append(coverage_entry("GCP onboarding", "not_applicable", "gcp"))
    if enabled(spec, "crowdstrike"):
        rows.extend(
            [
                coverage_entry("CrowdStrike source catalog", "artifact_validate", "crowdstrike"),
                coverage_entry("CrowdStrike FDR secret-file guardrails", "artifact_validate", "crowdstrike"),
                coverage_entry("CrowdStrike Data Manager input creation", "ui_handoff", "crowdstrike"),
            ]
        )
    else:
        rows.append(coverage_entry("CrowdStrike onboarding", "not_applicable", "crowdstrike"))
    return rows


def shell_quote(value: Any) -> str:
    text = str(value or "")
    return shlex.quote(text)


def build_apply_plan(spec: dict[str, Any]) -> dict[str, Any]:
    aws = as_dict(spec.get("aws"))
    azure = as_dict(spec.get("azure"))
    gcp = as_dict(spec.get("gcp"))
    iac = as_dict(spec.get("iac"))
    operations: list[dict[str, Any]] = [
        {
            "id": "splunk-readiness",
            "coverage_status": "splunk_validate",
            "mutating": False,
            "script": "scripts/validate-splunk-readiness.sh",
        },
        {
            "id": "data-manager-ui-create-inputs",
            "coverage_status": "ui_handoff",
            "mutating": False,
            "script": "",
            "note": "Create or edit Data Manager inputs in the Splunk Cloud UI.",
        },
    ]
    if enabled(spec, "aws"):
        operations.append(
            {
                "id": "aws-cloudformation-validate",
                "coverage_status": "artifact_validate",
                "mutating": False,
                "script": "scripts/aws-cloudformation.sh --validate",
                "artifact_path": aws.get("cloudformation_template_path")
                or aws.get("stackset_template_path"),
            }
        )
        operations.append(
            {
                "id": "aws-cloudformation-apply",
                "coverage_status": "artifact_apply",
                "mutating": True,
                "enabled": iac_apply_enabled(iac, "aws_cloudformation_apply_enabled"),
                "script": "scripts/aws-cloudformation.sh --apply",
                "artifact_path": aws.get("cloudformation_template_path"),
                "note": "StackSet execution is rendered as a handoff because deployment targets and permission mode require operator review.",
            }
        )
    if enabled(spec, "azure"):
        operations.append(
            {
                "id": "azure-arm-what-if",
                "coverage_status": "artifact_validate",
                "mutating": False,
                "script": "scripts/azure-arm.sh --what-if",
                "artifact_path": azure.get("arm_template_path"),
            }
        )
        operations.append(
            {
                "id": "azure-arm-apply",
                "coverage_status": "artifact_apply",
                "mutating": True,
                "enabled": iac_apply_enabled(iac, "azure_arm_apply_enabled"),
                "script": "scripts/azure-arm.sh --apply",
                "artifact_path": azure.get("arm_template_path"),
            }
        )
    if enabled(spec, "gcp"):
        operations.append(
            {
                "id": "gcp-terraform-validate",
                "coverage_status": "artifact_validate",
                "mutating": False,
                "script": "scripts/gcp-terraform.sh --validate",
                "artifact_path": gcp.get("terraform_template_dir"),
            }
        )
        operations.append(
            {
                "id": "gcp-terraform-apply",
                "coverage_status": "artifact_apply",
                "mutating": True,
                "enabled": iac_apply_enabled(iac, "gcp_terraform_apply_enabled"),
                "script": "scripts/gcp-terraform.sh --apply",
                "artifact_path": gcp.get("terraform_template_dir"),
            }
        )
        operations.append(
            {
                "id": "gcp-terraform-destroy",
                "coverage_status": "artifact_apply",
                "mutating": True,
                "enabled": iac_apply_enabled(iac, "gcp_terraform_destroy_enabled"),
                "script": "scripts/gcp-terraform.sh --destroy",
                "artifact_path": gcp.get("terraform_template_dir"),
            }
        )
    return {
        "api_version": "splunk-cloud-data-manager-setup/v1",
        "requires_accept_apply": True,
        "rendered_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "unsupported_claims_blocked": [
            "No private Data Manager API.",
            "No Terraform-based Data Manager input CRUD.",
            "No universal HEC ACK assumption.",
        ],
        "operations": operations,
    }


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    output = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        output.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(output)


def write_text(path: Path, text: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    if executable:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def render_readme(spec: dict[str, Any], coverage: list[dict[str, str]]) -> str:
    provider_names = [
        provider
        for provider in ("aws", "azure", "gcp", "crowdstrike")
        if enabled(spec, provider)
    ]
    coverage_rows = [
        [row["provider"], row["feature"], row["coverage_status"]]
        for row in coverage
    ]
    return f"""# Splunk Cloud Data Manager Render

Skill: `{SKILL_NAME}`

Enabled providers: {", ".join(provider_names) if provider_names else "none"}

This render validates Splunk Cloud Data Manager readiness and provider
artifacts. Data Manager input creation is a UI handoff unless Splunk publishes
a supported API. The generated scripts handle only user-supplied or Data
Manager-downloaded CloudFormation, ARM, and Terraform artifacts.

## Safe Next Commands

```bash
bash scripts/validate-splunk-readiness.sh
bash scripts/apply-data-manager-artifacts.sh --dry-run
```

Run the skill-level validator from the repo root:

```bash
bash skills/splunk-cloud-data-manager-setup/scripts/validate.sh
```

## Coverage

{markdown_table(["Provider", "Feature", "Status"], coverage_rows)}
"""


def render_doctor(findings: list[dict[str, str]]) -> str:
    if not findings:
        findings_md = "- No render-blocking findings."
    else:
        findings_md = "\n".join(
            f"- **{item['severity']}** `{item['area']}` - {item['message']}"
            for item in findings
        )
    return f"""# Data Manager Doctor Report

## Findings

{findings_md}

## Common Fix Handoffs

- Missing HEC/index prerequisites: use `splunk-hec-service-setup`.
- Search API or Data Manager UI allowlist issues: use `splunk-cloud-acs-allowlist-setup`.
- Add-on prerequisites: use `splunk-app-install`.
- Unknown admin posture: use `splunk-admin-doctor`.
"""


def render_health_searches(spec: dict[str, Any]) -> str:
    indexes = [str(index) for index in as_list(as_dict(spec.get("indexes")).get("required"))]
    if not indexes:
        indexes = ["main"]
    provider_sourcetypes: list[str] = []
    for provider in ("aws", "azure", "gcp", "crowdstrike"):
        if enabled(spec, provider):
            provider_sourcetypes.extend(SOURCE_CATALOG[provider][:8])
    index_clause = " OR ".join(f"index={index}" for index in indexes)
    sourcetype_clause = (
        " OR ".join(f'sourcetype="{sourcetype}"' for sourcetype in provider_sourcetypes)
        if provider_sourcetypes
        else "sourcetype=*"
    )
    return f"""# Data Manager health searches

| makeresults
| eval note="Run these searches after Data Manager inputs report healthy."

({index_clause}) ({sourcetype_clause})
| stats count min(_time) as first_event max(_time) as last_event by index sourcetype host
| convert ctime(first_event) ctime(last_event)

index=_internal (component=DataManager OR component=scdm OR log_level=ERROR)
| stats count by component log_level message
"""


def render_source_catalog_json() -> dict[str, Any]:
    return {
        "manual_version": "1.16",
        "hec_ack_required_sources": HEC_ACK_REQUIRED_SOURCES,
        "hec_special_tokens": HEC_SPECIAL_TOKENS,
        "hec_token_names": HEC_TOKEN_NAMES,
        "source_catalog": SOURCE_CATALOG,
        "data_source_families": DATA_SOURCE_FAMILIES,
        "aws_org_ou_supported_source_families": sorted(AWS_ORG_OU_SUPPORTED_SOURCE_FAMILIES),
        "supported_ingestion_regions": {
            "aws": sorted(AWS_INGESTION_REGIONS),
            "azure": sorted(AZURE_INGESTION_REGIONS),
            "gcp_dataflow": sorted(GCP_DATAFLOW_REGIONS),
            "crowdstrike_fdr": sorted(CROWDSTRIKE_FDR_REGIONS),
        },
        "crowdstrike_fdr_region_to_aws_region": CROWDSTRIKE_REGION_TO_AWS_REGION,
        "out_of_scope_handoffs": {
            "amazon_security_lake": "Federated Analytics / Amazon Security Lake provider, not Data Manager input CRUD.",
            "splunk_ta_google_cloud_platform_source_types": "Adjacent add-on sourcetypes, not Data Manager 1.16 source catalog unless listed above.",
        },
    }


def render_provider_runbooks(output_dir: Path, spec: dict[str, Any]) -> None:
    write_text(
        output_dir / "provider-runbooks" / "hec.md",
        """# HEC Runbook

Validate HEC is enabled and Data Manager-created tokens are enabled. ACK is
source-specific, not global.

ACK required sources: CloudTrail, GuardDuty, SecurityHub, IAM Access Analyzer,
and CloudWatch Logs.

Special tokens:

- `scdm-scs-hec-token` for AWS S3, Azure Event Hub, and CrowdStrike FDR.
- `scdm-scs-promote-hec-token` for AWS S3 Promote.
""",
    )
    for provider, sourcetypes in SOURCE_CATALOG.items():
        if not enabled(spec, provider):
            continue
        write_text(
            output_dir / "provider-runbooks" / f"{provider}.md",
            f"""# {provider.upper()} Data Manager Runbook

Coverage status is rendered in `../coverage-report.json`.

## Source Types

{chr(10).join(f"- `{sourcetype}`" for sourcetype in sourcetypes)}

## Data Sources

{chr(10).join(f"- {source}" for source in DATA_SOURCE_FAMILIES.get(provider, []))}

## Apply Model

Use only Data Manager-generated artifacts for provider-side infrastructure.
Input creation or editing remains a Data Manager UI handoff unless Splunk
publishes a supported API.
""",
        )
    write_json(output_dir / "provider-runbooks" / "source-catalog.json", render_source_catalog_json())


def render_scripts(output_dir: Path, spec: dict[str, Any]) -> None:
    aws = as_dict(spec.get("aws"))
    azure = as_dict(spec.get("azure"))
    gcp = as_dict(spec.get("gcp"))
    iac = as_dict(spec.get("iac"))
    aws_cloudformation_template = aws.get("cloudformation_template_path")
    aws_stackset_template = aws.get("stackset_template_path")
    aws_template = aws_cloudformation_template or aws_stackset_template
    aws_stack_name = aws.get("cloudformation_stack_name") or ""
    azure_template = azure.get("arm_template_path")
    gcp_dir = gcp.get("terraform_template_dir")
    azure_subscription = azure.get("event_hub_subscription_id") or (
        as_list(azure.get("subscription_ids"))[0] if as_list(azure.get("subscription_ids")) else ""
    )
    azure_region = azure.get("event_hub_region") or ""
    write_text(
        output_dir / "scripts" / "validate-splunk-readiness.sh",
        """#!/usr/bin/env bash
set -euo pipefail

echo "Validating Splunk Cloud Data Manager readiness from rendered plan."
echo "- Confirm Data Manager opens on the primary search head."
echo "- Confirm admin/sc_admin or documented Data Manager capabilities."
echo "- Confirm HEC is enabled and required indexes are visible to the role."
echo "- Confirm Data Manager-created tokens are enabled and ACK is source-specific."
echo "- Confirm input count remains below 5000."
""",
        executable=True,
    )
    write_text(
        output_dir / "scripts" / "aws-cloudformation.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail

MODE="${{1:---validate}}"
TEMPLATE_PATH={shell_quote(aws_template)}
CLOUDFORMATION_TEMPLATE_PATH={shell_quote(aws_cloudformation_template)}
STACK_NAME={shell_quote(aws_stack_name)}
REGION={shell_quote(aws.get("iam_roles_region") or (as_list(aws.get("regions"))[0] if as_list(aws.get("regions")) else ""))}
STACKSET_TEMPLATE_PATH={shell_quote(aws_stackset_template)}
APPLY_ENABLED={shell_quote(str(iac_apply_enabled(iac, "aws_cloudformation_apply_enabled")).lower())}

if [[ -z "${{TEMPLATE_PATH}}" ]]; then
  if [[ "${{MODE}}" == "--apply" && "${{APPLY_ENABLED}}" == "true" ]]; then
    echo "AWS apply is enabled, but no Data Manager-generated CloudFormation stack template path is configured." >&2
    exit 2
  fi
  if [[ -n "${{STACKSET_TEMPLATE_PATH}}" ]]; then
    echo "StackSet template configured at ${{STACKSET_TEMPLATE_PATH}}. Validate/apply it through the StackSet handoff after reviewing deployment targets and permission mode."
  else
    echo "No AWS CloudFormation stack template path configured."
  fi
  exit 0
fi

case "${{MODE}}" in
  --validate)
    aws cloudformation validate-template --template-body "file://${{TEMPLATE_PATH}}" --region "${{REGION}}"
    ;;
  --apply)
    if [[ "${{ACCEPT_DATA_MANAGER_APPLY:-}}" != "1" ]]; then
      echo "Set ACCEPT_DATA_MANAGER_APPLY=1 after reviewing Data Manager-generated CloudFormation."
      exit 2
    fi
    if [[ -z "${{CLOUDFORMATION_TEMPLATE_PATH}}" ]]; then
      echo "AWS StackSet apply is a rendered handoff. Provide aws.cloudformation_template_path for single-stack apply." >&2
      exit 2
    fi
    if [[ -z "${{STACK_NAME}}" ]]; then
      echo "AWS CloudFormation apply requires aws.cloudformation_stack_name in the spec." >&2
      exit 2
    fi
    aws cloudformation deploy \
      --template-file "${{TEMPLATE_PATH}}" \
      --stack-name "${{STACK_NAME}}" \
      --region "${{REGION}}" \
      --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND
    ;;
  *)
    echo "Usage: $0 --validate|--apply" >&2
    exit 2
    ;;
esac
""",
        executable=True,
    )
    write_text(
        output_dir / "scripts" / "azure-arm.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail

MODE="${{1:---what-if}}"
TEMPLATE_PATH={shell_quote(azure_template)}
SUBSCRIPTION_ID={shell_quote(azure_subscription)}
LOCATION={shell_quote(azure_region)}
APPLY_ENABLED={shell_quote(str(iac_apply_enabled(iac, "azure_arm_apply_enabled")).lower())}

if [[ -z "${{TEMPLATE_PATH}}" ]]; then
  if [[ "${{MODE}}" == "--apply" && "${{APPLY_ENABLED}}" == "true" ]]; then
    echo "Azure ARM apply is enabled, but no Data Manager-generated ARM template path is configured." >&2
    exit 2
  fi
  echo "No Azure ARM template path configured."
  exit 0
fi

case "${{MODE}}" in
  --what-if)
    az deployment sub what-if --subscription "${{SUBSCRIPTION_ID}}" --location "${{LOCATION}}" --template-file "${{TEMPLATE_PATH}}"
    ;;
  --apply)
    if [[ "${{ACCEPT_DATA_MANAGER_APPLY:-}}" != "1" ]]; then
      echo "Set ACCEPT_DATA_MANAGER_APPLY=1 after reviewing ARM what-if output."
      exit 2
    fi
    az deployment sub create --subscription "${{SUBSCRIPTION_ID}}" --location "${{LOCATION}}" --template-file "${{TEMPLATE_PATH}}"
    ;;
  *)
    echo "Usage: $0 --what-if|--apply" >&2
    exit 2
    ;;
esac
""",
        executable=True,
    )
    write_text(
        output_dir / "scripts" / "gcp-terraform.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail

MODE="${{1:---validate}}"
TEMPLATE_DIR={shell_quote(gcp_dir)}
APPLY_ENABLED={shell_quote(str(iac_apply_enabled(iac, "gcp_terraform_apply_enabled")).lower())}
DESTROY_ENABLED={shell_quote(str(iac_apply_enabled(iac, "gcp_terraform_destroy_enabled")).lower())}

if [[ -z "${{TEMPLATE_DIR}}" ]]; then
  if [[ "${{MODE}}" == "--apply" && "${{APPLY_ENABLED}}" == "true" ]]; then
    echo "GCP Terraform apply is enabled, but no Data Manager-generated Terraform template directory is configured." >&2
    exit 2
  fi
  if [[ "${{MODE}}" == "--destroy" && "${{DESTROY_ENABLED}}" == "true" ]]; then
    echo "GCP Terraform destroy is enabled, but no Data Manager-generated Terraform template directory is configured." >&2
    exit 2
  fi
  echo "No GCP Terraform template directory configured."
  exit 0
fi

cd "${{TEMPLATE_DIR}}"
terraform init

case "${{MODE}}" in
  --validate)
    terraform validate
    ;;
  --apply)
    if [[ "${{ACCEPT_DATA_MANAGER_APPLY:-}}" != "1" ]]; then
      echo "Set ACCEPT_DATA_MANAGER_APPLY=1 after reviewing Data Manager-generated Terraform."
      exit 2
    fi
    terraform apply
    ;;
  --destroy)
    if [[ "${{ACCEPT_DATA_MANAGER_APPLY:-}}" != "1" ]]; then
      echo "Set ACCEPT_DATA_MANAGER_APPLY=1 after reviewing Data Manager delete guidance."
      exit 2
    fi
    terraform destroy
    ;;
  *)
    echo "Usage: $0 --validate|--apply|--destroy" >&2
    exit 2
    ;;
esac
""",
        executable=True,
    )
    write_text(
        output_dir / "scripts" / "apply-data-manager-artifacts.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail

DRY_RUN=false
if [[ "${{1:-}}" == "--dry-run" ]]; then
  DRY_RUN=true
fi

if [[ "${{DRY_RUN}}" == "true" ]]; then
  echo "Dry run only. Review apply-plan.json before running setup.sh --phase apply --accept-apply."
  exit 0
fi

if [[ "${{ACCEPT_DATA_MANAGER_APPLY:-}}" != "1" ]]; then
  echo "Refusing to apply without ACCEPT_DATA_MANAGER_APPLY=1."
  exit 2
fi

echo "Running enabled Data Manager artifact apply wrappers."
if [[ {shell_quote(str(iac_apply_enabled(iac, "aws_cloudformation_apply_enabled")).lower())} == "true" ]]; then
  ./scripts/aws-cloudformation.sh --apply
else
  echo "Skipping AWS CloudFormation apply; iac.apply_enabled and iac.aws_cloudformation_apply_enabled are not both true."
fi
if [[ {shell_quote(str(iac_apply_enabled(iac, "azure_arm_apply_enabled")).lower())} == "true" ]]; then
  ./scripts/azure-arm.sh --apply
else
  echo "Skipping Azure ARM apply; iac.apply_enabled and iac.azure_arm_apply_enabled are not both true."
fi
if [[ {shell_quote(str(iac_apply_enabled(iac, "gcp_terraform_apply_enabled")).lower())} == "true" ]]; then
  ./scripts/gcp-terraform.sh --apply
else
  echo "Skipping GCP Terraform apply; iac.apply_enabled and iac.gcp_terraform_apply_enabled are not both true."
fi
if [[ {shell_quote(str(iac_apply_enabled(iac, "gcp_terraform_destroy_enabled")).lower())} == "true" ]]; then
  ./scripts/gcp-terraform.sh --destroy
else
  echo "Skipping GCP Terraform destroy; iac.apply_enabled and iac.gcp_terraform_destroy_enabled are not both true."
fi
""",
        executable=True,
    )


def scan_generated_text(output_dir: Path) -> list[str]:
    errors: list[str] = []
    for path in output_dir.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in UNSUPPORTED_CLAIM_PATTERNS:
            if pattern.search(text):
                errors.append(f"{path}: unsupported claim matched {pattern.pattern}")
    return errors


def render(spec_path: Path, output_dir: Path, mode: str) -> None:
    spec = load_spec(spec_path)
    secret_errors = validate_no_raw_secrets(spec)
    if secret_errors:
        raise RenderError(
            "Raw secret-like values are not allowed. Use *_file or *_path fields: "
            + ", ".join(secret_errors)
        )
    findings = collect_findings(spec)
    coverage = build_coverage(spec)
    apply_plan = build_apply_plan(spec)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "spec.normalized.json", spec)
    write_json(output_dir / "coverage-report.json", coverage)
    write_json(output_dir / "apply-plan.json", apply_plan)
    write_json(output_dir / "source-catalog.json", render_source_catalog_json())
    write_text(output_dir / "README.md", render_readme(spec, coverage))
    write_text(output_dir / "doctor-report.md", render_doctor(findings))
    write_text(output_dir / "health-searches.spl", render_health_searches(spec))
    render_provider_runbooks(output_dir, spec)
    render_scripts(output_dir, spec)
    generated_errors = scan_generated_text(output_dir)
    if generated_errors:
        raise RenderError("\n".join(generated_errors))

    print(f"Rendered {SKILL_NAME} artifacts to {output_dir}")
    if mode == "doctor" and findings:
        for item in findings:
            print(f"{item['severity']} {item['area']}: {item['message']}")


def check_rendered(output_dir: Path) -> None:
    required = [
        "README.md",
        "coverage-report.json",
        "apply-plan.json",
        "doctor-report.md",
        "health-searches.spl",
        "source-catalog.json",
        "provider-runbooks/source-catalog.json",
        "scripts/validate-splunk-readiness.sh",
        "scripts/apply-data-manager-artifacts.sh",
    ]
    missing = [rel for rel in required if not (output_dir / rel).is_file()]
    if missing:
        raise RenderError("Missing rendered artifacts: " + ", ".join(missing))
    coverage = json.loads((output_dir / "coverage-report.json").read_text(encoding="utf-8"))
    statuses = {row.get("coverage_status") for row in coverage}
    unknown = statuses - ALLOWED_COVERAGE_STATUSES
    if unknown:
        raise RenderError("Unknown coverage statuses: " + ", ".join(sorted(unknown)))
    source_catalog = json.loads((output_dir / "source-catalog.json").read_text(encoding="utf-8"))
    if source_catalog.get("hec_ack_required_sources") != HEC_ACK_REQUIRED_SOURCES:
        raise RenderError("HEC ACK required source mapping drifted.")
    plan = json.loads((output_dir / "apply-plan.json").read_text(encoding="utf-8"))
    missing_artifacts = [
        op["id"]
        for op in plan.get("operations", [])
        if op.get("mutating") and op.get("enabled") and not op.get("artifact_path")
    ]
    if missing_artifacts:
        raise RenderError(
            "Enabled apply operations are missing Data Manager-generated artifacts: "
            + ", ".join(missing_artifacts)
        )
    generated_errors = scan_generated_text(output_dir)
    if generated_errors:
        raise RenderError("\n".join(generated_errors))
    print(f"Rendered artifacts in {output_dir} passed validation.")


def main() -> int:
    args = parse_args()
    spec_path = Path(args.spec)
    output_dir = Path(args.output_dir)
    try:
        if args.mode == "check-rendered":
            check_rendered(output_dir)
        elif args.mode == "status":
            check_rendered(output_dir)
            plan = json.loads((output_dir / "apply-plan.json").read_text(encoding="utf-8"))
            print(json.dumps(plan["operations"], indent=2))
        else:
            render(spec_path, output_dir, args.mode)
    except RenderError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
