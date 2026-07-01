#!/usr/bin/env python3
"""Render Splunk Observability Cloud <-> GCP Integration assets.

Reads a YAML or JSON spec (default: ``template.example``) and emits a
render-first plan tree under ``--output-dir``:

- ``rest/``         — POST/PUT /v2/integration payloads (type=GCP)
- ``terraform/``    — signalfx_gcp_integration resource for service-account auth
- ``gcloud-cli/``   — service-account creation + role binding scripts
- ``handoffs/``     — cross-skill driver scripts (opt-in per handoffs.*)
- ``state/``        — placeholder; populated by gcp_integration_api.py on apply
- ``coverage-report.json``
- ``apply-plan.json``

The renderer never accepts or writes any secret value. ``projectKey``, the
official Splunk-generated ``gcp_wif_config.json``, and the Splunk O11y token
are referenced as file paths only.
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
# Constants.
# ---------------------------------------------------------------------------

SKILL_NAME = "splunk-observability-gcp-integration"
API_VERSION = f"{SKILL_NAME}/v1"

SUPPORTED_REALMS: tuple[str, ...] = (
    "us0", "us1", "us2", "us3",
    "eu0", "eu1", "eu2",
    "au0", "jp0", "sg0",
)

AUTH_MODES: tuple[str, ...] = ("service_account_key", "workload_identity_federation")

TERRAFORM_PROVIDER_VERSION_DEFAULT = "~> 9.0"

SERVICES_MODES: tuple[str, ...] = ("all_built_in", "explicit")

SERVICES_ENUM_PATH = Path(__file__).parent.parent / "references" / "services-enum.json"

SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"eyJ[A-Za-z0-9._-]{20,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{12,}"),
    re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:[A-Za-z0-9._~-]{16,}"),
)


# ---------------------------------------------------------------------------
# Spec loading and validation.
# ---------------------------------------------------------------------------


class RenderError(Exception):
    """Raised when the spec cannot be rendered (FAIL)."""


def load_services_enum() -> list[str]:
    try:
        data = json.loads(SERVICES_ENUM_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RenderError(f"cannot load GCP services enum {SERVICES_ENUM_PATH}: {exc}") from exc
    services = data.get("services") if isinstance(data, dict) else None
    if not isinstance(services, list) or not services or not all(isinstance(item, str) and item for item in services):
        raise RenderError(f"GCP services enum {SERVICES_ENUM_PATH} must contain a non-empty string list")
    return list(services)


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
    for pat in SECRET_PATTERNS:
        if pat.search(text):
            raise RenderError(
                f"refusing to write {label}: secret-looking content matched {pat.pattern!r}"
            )


def validate_spec(
    spec: dict[str, Any],
    realm_override: str | None = None,
    key_file_overrides: list[str] | None = None,
    wif_config_file_override: str | None = None,
) -> dict[str, Any]:
    """Normalize spec, fill defaults, FAIL on hard errors."""
    if not isinstance(spec, dict):
        raise RenderError("spec root must be a mapping")

    spec.setdefault("api_version", API_VERSION)
    if spec["api_version"] != API_VERSION:
        raise RenderError(f"api_version must be {API_VERSION!r}, got {spec['api_version']!r}")

    realm = realm_override or spec.get("realm", "")
    if not realm:
        raise RenderError(f"realm is required ({'/'.join(SUPPORTED_REALMS)})")
    if realm not in SUPPORTED_REALMS:
        raise RenderError(f"realm {realm!r} is not recognized. Allowed: {', '.join(SUPPORTED_REALMS)}")
    spec["realm"] = realm

    if not spec.get("integration_name"):
        raise RenderError("integration_name is required")

    auth = spec.setdefault("authentication", {})
    auth_mode = auth.setdefault("mode", "service_account_key")
    if auth_mode not in AUTH_MODES:
        raise RenderError(
            f"authentication.mode must be one of {AUTH_MODES}, got {auth_mode!r}"
        )

    # Conflict matrix: SA key mode vs WIF configuration.
    psk = auth.get("project_service_keys") or []
    wif = auth.get("workload_identity_federation") or {}
    if not isinstance(wif, dict):
        raise RenderError("authentication.workload_identity_federation must be a mapping")
    wif_has_data = any(value not in (None, "", [], {}) for value in wif.values())

    if auth_mode == "service_account_key":
        if wif_config_file_override:
            raise RenderError("--wif-config-file cannot be used with service_account_key")
        if wif_has_data:
            raise RenderError(
                "authentication.mode=service_account_key but workload_identity_federation "
                "block is populated. Remove the WIF block or change mode."
            )
        # Apply repeated key-file overrides one-to-one in project spec order.
        if key_file_overrides:
            if len(key_file_overrides) != len(psk):
                raise RenderError(
                    f"received {len(key_file_overrides)} --key-file value(s) for "
                    f"{len(psk)} project_service_keys entries; supply exactly one per project"
                )
            for entry, key_file in zip(psk, key_file_overrides):
                if isinstance(entry, dict):
                    entry["key_file"] = key_file
        if not psk:
            raise RenderError(
                "authentication.project_service_keys is required when mode=service_account_key. "
                "Add at least one {project_id, key_file} entry."
            )
        for entry in psk:
            if not isinstance(entry, dict) or not entry.get("project_id"):
                raise RenderError("each project_service_keys entry must have a project_id")
    elif auth_mode == "workload_identity_federation":
        if key_file_overrides:
            raise RenderError("--key-file cannot be used with workload_identity_federation")
        if psk:
            raise RenderError(
                "authentication.mode=workload_identity_federation but project_service_keys "
                "is populated. Remove the project_service_keys block or change mode."
            )
        legacy_fields = sorted(
            key for key in ("pool_id", "provider_id", "splunk_principal") if key in wif
        )
        if legacy_fields:
            raise RenderError(
                "unsupported legacy WIF fields are present: "
                + ", ".join(legacy_fields)
                + ". Do not construct pool/provider/principal values; use config_file "
                  "pointing to Splunk's official generated gcp_wif_config.json."
            )
        if wif_config_file_override:
            wif["config_file"] = wif_config_file_override
        config_file = str(wif.get("config_file") or "").strip()
        if not config_file:
            raise RenderError(
                "authentication.workload_identity_federation.config_file is required in WIF mode; "
                "use the official Splunk-generated gcp_wif_config.json file"
            )
        if Path(config_file).name != "gcp_wif_config.json":
            raise RenderError(
                "WIF config_file must reference the official generated file named gcp_wif_config.json"
            )
        wif["config_file"] = config_file

    conn = spec.setdefault("connection", {})
    poll_rate = int(conn.setdefault("poll_rate_seconds", 300))
    if not 60 <= poll_rate <= 600:
        raise RenderError(f"connection.poll_rate_seconds must be 60..600, got {poll_rate}")
    conn["poll_rate_seconds"] = poll_rate
    conn.setdefault("use_metric_source_project_for_quota", False)
    conn.setdefault("import_gcp_metrics", True)

    if conn["use_metric_source_project_for_quota"]:
        spec.setdefault("_warnings", []).append(
            "use_metric_source_project_for_quota=true requires "
            "roles/serviceusage.serviceUsageConsumer on the metric source project SA."
        )

    projects = spec.setdefault("projects", {})
    projects.setdefault("sync_mode", "ALL")
    if projects["sync_mode"] not in ("ALL", "SELECTED"):
        raise RenderError(
            f"projects.sync_mode must be ALL or SELECTED, got {projects['sync_mode']!r}"
        )
    projects.setdefault("selected_project_ids", [])
    selected_project_ids = projects["selected_project_ids"]
    if not isinstance(selected_project_ids, list) or not all(
        isinstance(project_id, str) and project_id.strip()
        for project_id in selected_project_ids
    ):
        raise RenderError("projects.selected_project_ids must be a list of non-empty strings")
    projects["selected_project_ids"] = list(dict.fromkeys(selected_project_ids))
    if projects["sync_mode"] == "ALL" and projects["selected_project_ids"]:
        raise RenderError(
            "projects.selected_project_ids must be empty when projects.sync_mode=ALL"
        )
    if projects["sync_mode"] == "SELECTED" and not projects["selected_project_ids"]:
        raise RenderError(
            "projects.selected_project_ids must be non-empty when projects.sync_mode=SELECTED"
        )

    services = spec.setdefault("services", {})
    services.setdefault("mode", "all_built_in")
    if services["mode"] not in SERVICES_MODES:
        raise RenderError(f"services.mode must be one of {SERVICES_MODES}")
    services.setdefault("explicit", [])

    # Conflict: explicit non-empty + mode=all_built_in.
    if services["mode"] == "all_built_in" and services["explicit"]:
        raise RenderError(
            "services.explicit is non-empty but services.mode=all_built_in. "
            "Either set mode=explicit or clear services.explicit."
        )

    known_services = load_services_enum()
    if services["mode"] == "explicit":
        if known_services and services["explicit"]:
            unknown = [s for s in services["explicit"] if s not in known_services]
            if unknown:
                services.setdefault("_warnings", []).append(
                    f"unknown services (not in 32-entry enum, will be passed as-is): {', '.join(unknown)}"
                )

    spec.setdefault("custom_metric_type_domains", [])
    spec.setdefault("exclude_gce_instances_with_labels", [])
    spec.setdefault("named_token", "")

    tf = spec.setdefault("terraform_provider", {})
    tf.setdefault("source", "splunk-terraform/signalfx")
    tf.setdefault("version", TERRAFORM_PROVIDER_VERSION_DEFAULT)

    spec.setdefault("gcloud_cli_render", True)

    multi = spec.setdefault("multi_project", {})
    multi.setdefault("enabled", False)

    handoffs = spec.setdefault("handoffs", {})
    for k, default in (
        ("splunk_ta_google_cloud", False),
        ("gke_otel_collector", False),
        ("dashboards", False),
        ("detectors", False),
    ):
        handoffs.setdefault(k, default)

    return spec


# ---------------------------------------------------------------------------
# Coverage.
# ---------------------------------------------------------------------------


def coverage_for(spec: dict[str, Any]) -> dict[str, dict[str, str]]:
    coverage: dict[str, dict[str, str]] = {}

    coverage["prerequisites.realm"] = {
        "status": "api_validate",
        "notes": f"realm {spec['realm']}",
    }

    auth = spec["authentication"]
    auth_mode = auth["mode"]
    coverage["authentication.mode"] = {
        "status": "api_apply",
        "notes": f"authMethod={auth_mode.upper().replace('_', '_')}",
    }

    if auth_mode == "service_account_key":
        psk = auth.get("project_service_keys") or []
        coverage["authentication.project_service_keys"] = {
            "status": "api_apply",
            "notes": f"{len(psk)} project(s); projectKey write-only, redacted on GET",
        }
        coverage["authentication.wif"] = {"status": "not_applicable", "notes": "SA key mode"}
    else:
        coverage["authentication.wif"] = {
            "status": "api_apply",
            "notes": (
                "official gcp_wif_config.json supplied by file; sent as compact JSON in "
                "workloadIdentityFederationConfig"
            ),
        }
        coverage["authentication.project_service_keys"] = {
            "status": "not_applicable",
            "notes": "WIF mode; no SA key",
        }

    conn = spec["connection"]
    coverage["connection.poll_rate"] = {
        "status": "api_apply",
        "notes": f"pollRate={conn['poll_rate_seconds']}s ({conn['poll_rate_seconds'] * 1000}ms wire)",
    }
    coverage["connection.use_metric_source_project_for_quota"] = {
        "status": "api_apply" if conn["use_metric_source_project_for_quota"] else "not_applicable",
        "notes": f"useMetricSourceProjectForQuota={conn['use_metric_source_project_for_quota']}",
    }
    coverage["connection.import_gcp_metrics"] = {
        "status": "api_apply",
        "notes": f"importGCPMetrics={conn['import_gcp_metrics']}",
    }

    projects = spec["projects"]
    coverage["projects.sync_mode"] = {
        "status": "api_apply",
        "notes": f"sync_mode={projects['sync_mode']}, {len(projects['selected_project_ids'])} selected IDs",
    }

    services = spec["services"]
    coverage["services.mode"] = {
        "status": "api_apply",
        "notes": f"mode={services['mode']}, {len(services['explicit'])} explicit",
    }

    if spec["custom_metric_type_domains"]:
        coverage["custom_metric_type_domains"] = {
            "status": "api_apply",
            "notes": f"{len(spec['custom_metric_type_domains'])} custom domain(s)",
        }
    else:
        coverage["custom_metric_type_domains"] = {"status": "not_applicable", "notes": ""}

    if spec["exclude_gce_instances_with_labels"]:
        coverage["exclude_gce_instances_with_labels"] = {
            "status": "api_apply",
            "notes": f"{len(spec['exclude_gce_instances_with_labels'])} label exclusion(s)",
        }
    else:
        coverage["exclude_gce_instances_with_labels"] = {"status": "not_applicable", "notes": ""}

    if spec["named_token"]:
        coverage["named_token"] = {
            "status": "api_apply",
            "notes": f"namedToken={spec['named_token']} (WARNING: ForceNew — changes recreate the integration)",
        }
    else:
        coverage["named_token"] = {"status": "not_applicable", "notes": "using default org token"}

    if auth_mode == "service_account_key":
        coverage["terraform.resource"] = {
            "status": "handoff",
            "notes": f"signalfx_gcp_integration in terraform/main.tf (provider {spec['terraform_provider']['version']})",
        }
    else:
        coverage["terraform.resource"] = {
            "status": "not_applicable",
            "notes": (
                "No Terraform WIF resource is claimed; use the REST apply path with the "
                "official generated gcp_wif_config.json"
            ),
        }

    if spec["gcloud_cli_render"] and auth_mode == "service_account_key":
        coverage["gcloud_cli"] = {
            "status": "handoff",
            "notes": "gcloud-cli/create-sa.sh + bind-roles.sh rendered",
        }
    elif auth_mode == "workload_identity_federation":
        coverage["gcloud_cli"] = {
            "status": "not_applicable",
            "notes": "WIF pool/provider construction is intentionally not generated",
        }
    else:
        coverage["gcloud_cli"] = {"status": "not_applicable", "notes": "gcloud_cli_render=false"}

    if spec["multi_project"]["enabled"]:
        coverage["multi_project"] = {
            "status": "api_apply",
            "notes": "multi-project mode enabled",
        }
    else:
        coverage["multi_project"] = {"status": "not_applicable", "notes": "single-project spec"}

    coverage["validation.live_get"] = {
        "status": "api_validate",
        "notes": "GET /v2/integration/{id} round-trip; drift check for non-redacted fields",
    }
    coverage["validation.credential_hash"] = {
        "status": "api_validate",
        "notes": "SHA-256 of key_file(s) or WIF config vs state/credential-hashes.json",
    }

    handoffs = spec["handoffs"]
    for k in ("splunk_ta_google_cloud", "gke_otel_collector", "dashboards", "detectors"):
        coverage[f"handoff.{k}"] = {
            "status": "handoff" if handoffs[k] else "not_applicable",
            "notes": "",
        }

    return coverage


# ---------------------------------------------------------------------------
# REST payload.
# ---------------------------------------------------------------------------


def render_rest_payload(spec: dict[str, Any], integration_id: str | None = None) -> dict[str, Any]:
    """Produce the canonical POST /v2/integration body (type=GCP).

    pollRate: wire is milliseconds; spec is seconds.
    projectKey and workloadIdentityFederationConfig are rendered as placeholders;
    the API client reads their chmod-600 files immediately before apply.
    """
    auth = spec["authentication"]
    auth_mode = auth["mode"]
    conn = spec["connection"]
    services = spec["services"]

    payload: dict[str, Any] = {
        "type": "GCP",
        "name": spec["integration_name"],
        "enabled": True,
        "pollRate": conn["poll_rate_seconds"] * 1000,
        "useMetricSourceProjectForQuota": bool(conn["use_metric_source_project_for_quota"]),
        "importGCPMetrics": bool(conn["import_gcp_metrics"]),
        "projects": {
            "syncMode": spec["projects"]["sync_mode"],
        },
    }
    if spec["projects"]["sync_mode"] == "SELECTED":
        payload["projects"]["projectIds"] = list(spec["projects"]["selected_project_ids"])

    if auth_mode == "service_account_key":
        payload["authMethod"] = "SERVICE_ACCOUNT_KEY"
        psk = auth.get("project_service_keys") or []
        payload["projectServiceKeys"] = [
            {
                "projectId": entry["project_id"],
                "projectKey": "${PROJECT_KEY_FROM_FILE}",
            }
            for entry in psk
            if isinstance(entry, dict) and entry.get("project_id")
        ]
    elif auth_mode == "workload_identity_federation":
        payload["authMethod"] = "WORKLOAD_IDENTITY_FEDERATION"
        payload["workloadIdentityFederationConfig"] = (
            "${WORKLOAD_IDENTITY_FEDERATION_CONFIG_FROM_FILE}"
        )

    if services["mode"] == "explicit" and services["explicit"]:
        payload["services"] = list(services["explicit"])

    if spec["custom_metric_type_domains"]:
        payload["customMetricTypeDomains"] = list(spec["custom_metric_type_domains"])

    if spec["exclude_gce_instances_with_labels"]:
        payload["excludeGceInstancesWithLabels"] = list(spec["exclude_gce_instances_with_labels"])

    if spec["named_token"]:
        payload["namedToken"] = spec["named_token"]

    if integration_id:
        payload["id"] = integration_id

    return payload


# ---------------------------------------------------------------------------
# Terraform.
# ---------------------------------------------------------------------------


def render_terraform_main(spec: dict[str, Any]) -> str:
    services = spec["services"]
    tf = spec["terraform_provider"]
    conn = spec["connection"]
    auth = spec["authentication"]
    auth_mode = auth["mode"]

    if auth_mode == "workload_identity_federation":
        return """# Workload Identity Federation is intentionally not rendered as a
# signalfx_gcp_integration Terraform resource here. The supported contract uses
# authMethod=WORKLOAD_IDENTITY_FEDERATION and a compact JSON string loaded from
# Splunk's official generated gcp_wif_config.json. This skill does not claim
# provider arguments for that opaque file.
#
# Apply WIF through scripts/setup.sh --apply --wif-config-file
# /secure/path/gcp_wif_config.json after reviewing rest/create.json.
"""

    services_block = ""
    if services["mode"] == "explicit" and services["explicit"]:
        services_block = "  services = " + json.dumps(services["explicit"], indent=4).replace("\n", "\n  ") + "\n"

    named_token_line = f'  named_token = "{spec["named_token"]}"\n' if spec["named_token"] else ""

    poll_rate_comment = "  # poll_rate is in SECONDS for signalfx_gcp_integration (60-600)"

    psk = auth.get("project_service_keys") or []
    project_keys_block = ""
    for entry in psk:
        if isinstance(entry, dict) and entry.get("project_id"):
            project_keys_block += f"""
  project_service_keys {{
    project_id  = "{entry['project_id']}"
    project_key = var.project_key  # sensitive; deliver via TF_VAR_project_key or vault
  }}"""
    auth_block = project_keys_block + "\n"

    return f"""terraform {{
  required_providers {{
    signalfx = {{
      source  = "{tf['source']}"
      version = "{tf['version']}"
    }}
  }}
}}

provider "signalfx" {{
  # Export SFX_AUTH_TOKEN from your chmod-600 token file:
  #   export SFX_AUTH_TOKEN="$(cat ${{SPLUNK_O11Y_TOKEN_FILE}})"
  api_url = "https://api.{spec['realm']}.observability.splunkcloud.com"
}}

resource "signalfx_gcp_integration" "this" {{
  name    = "{spec['integration_name']}"
  enabled = true

{poll_rate_comment}
  poll_rate = {conn['poll_rate_seconds']}

  import_gcp_metrics                    = {str(conn['import_gcp_metrics']).lower()}
  use_metric_source_project_for_quota   = {str(conn['use_metric_source_project_for_quota']).lower()}

{auth_block}
{services_block}{named_token_line}}}
"""


def render_terraform_variables(spec: dict[str, Any]) -> str:
    auth_mode = spec["authentication"]["mode"]
    if auth_mode == "service_account_key":
        return """variable "project_key" {
  description = "GCP Service Account JSON key content"
  type        = string
  sensitive   = true
}
"""
    else:
        return """# No Terraform variables are rendered for Workload Identity Federation.
# Use the REST apply path with the official generated gcp_wif_config.json.
"""


# ---------------------------------------------------------------------------
# GCloud CLI scripts.
# ---------------------------------------------------------------------------


def render_gcloud_cli_create_sa(spec: dict[str, Any]) -> str:
    return """#!/usr/bin/env bash
# Create GCP Service Account for Splunk Observability GCP integration.
# Outputs the SA key to /tmp/splunk-gcp-sa-key.json (chmod 600).
# NEVER paste the key value into this script — the output file is the secret file.
set -euo pipefail

: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID to your GCP project ID}"

SA_NAME="splunk-observability-o11y"
SA_EMAIL="${SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

echo "==> Creating Service Account: ${SA_EMAIL}"
gcloud iam service-accounts create "${SA_NAME}" \\
  --display-name "Splunk Observability O11y" \\
  --project "${GCP_PROJECT_ID}"

echo "==> Downloading SA key to /tmp/splunk-gcp-sa-key.json"
gcloud iam service-accounts keys create /tmp/splunk-gcp-sa-key.json \\
  --iam-account "${SA_EMAIL}" \\
  --project "${GCP_PROJECT_ID}"
chmod 600 /tmp/splunk-gcp-sa-key.json

echo "==> SA key written to /tmp/splunk-gcp-sa-key.json (chmod 600)"
echo "==> Service Account email: ${SA_EMAIL}"
echo ""
echo "==> Next: bash bind-roles.sh"
"""


def render_gcloud_cli_bind_roles(spec: dict[str, Any]) -> str:
    auth = spec["authentication"]
    psk = auth.get("project_service_keys") or []
    project_ids = [e["project_id"] for e in psk if isinstance(e, dict) and e.get("project_id")]

    project_lines = "\n".join(
        f"  _bind_roles \"{pid}\""
        for pid in (project_ids if project_ids else ["${GCP_PROJECT_ID}"])
    )

    quota_warn = ""
    if spec["connection"].get("use_metric_source_project_for_quota"):
        quota_warn = """
  # useMetricSourceProjectForQuota=true: also grant serviceusage.serviceUsageConsumer
  gcloud projects add-iam-policy-binding "$1" \\
    --member="serviceAccount:${{SA_EMAIL}}" \\
    --role="roles/serviceusage.serviceUsageConsumer"
"""

    return f"""#!/usr/bin/env bash
# Bind required IAM roles to the Splunk Observability SA on each project.
# Run after create-sa.sh.
set -euo pipefail

: "${{GCP_PROJECT_ID:?Set GCP_PROJECT_ID to your GCP project ID}}"

SA_EMAIL="splunk-observability-o11y@${{GCP_PROJECT_ID}}.iam.gserviceaccount.com"

_bind_roles() {{
  local project_id="$1"
  echo "==> Binding roles on project: ${{project_id}}"

  gcloud projects add-iam-policy-binding "${{project_id}}" \\
    --member="serviceAccount:${{SA_EMAIL}}" \\
    --role="roles/monitoring.viewer"

  gcloud projects add-iam-policy-binding "${{project_id}}" \\
    --member="serviceAccount:${{SA_EMAIL}}" \\
    --role="roles/compute.viewer"
{quota_warn}}}

# Bind roles on each project listed in the spec.
{project_lines}

echo "==> Role bindings complete."
echo "==> Required roles per project:"
echo "    roles/monitoring.viewer  — read Cloud Monitoring metrics"
echo "    roles/compute.viewer     — GCE resource discovery"
"""


# ---------------------------------------------------------------------------
# Handoff scripts.
# ---------------------------------------------------------------------------


def render_handoff_ta_3088(spec: dict[str, Any]) -> str:
    return """#!/usr/bin/env bash
# Hand-off: GCP log ingestion via Splunk_TA_google_cloud (Splunkbase 3088).
# GCP Cloud Monitoring metrics go through Splunk Observability; GCP logs land in Splunk Platform.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

echo "==> Install Splunk_TA_google_cloud (Splunkbase 3088) for GCP log ingestion:"
echo "    bash ${PROJECT_ROOT}/skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id 3088"
echo ""
echo "==> After install, configure GCP inputs in the TA for:"
echo "    Cloud Pub/Sub subscriptions, GCS log bucket inputs, Cloud Audit Logs"
"""


def render_handoff_gke_otel(spec: dict[str, Any]) -> str:
    return """#!/usr/bin/env bash
# Hand-off: GKE host telemetry via splunk-observability-otel-collector-setup.
# Splunk Observability GCP integration collects Cloud Monitoring metrics.
# The OTel collector adds richer Kubernetes/host telemetry from GKE nodes.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

echo "==> Render Splunk OTel collector for GKE:"
echo "    bash ${PROJECT_ROOT}/skills/splunk-observability-otel-collector-setup/scripts/setup.sh --render"
echo ""
echo "==> The OTel collector complements (does not replace) the GCP Cloud Monitoring integration."
echo "    GKE cluster metrics via Cloud Monitoring (container service)"
echo "    GKE node host telemetry: cpu/memory/disk/network via the OTel collector."
"""


def render_handoff_dashboards(spec: dict[str, Any]) -> str:
    return """#!/usr/bin/env bash
# Hand-off: GCP dashboards via splunk-observability-dashboard-builder.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

echo "==> Render custom GCP dashboards on top of O11y GCP metrics:"
echo "    bash ${PROJECT_ROOT}/skills/splunk-observability-dashboard-builder/scripts/setup.sh --render"
echo ""
echo "==> Built-in GCP dashboards auto-populate when the integration is healthy."
echo "    No custom rendering is required unless you need bespoke charts."
"""


def render_handoff_detectors(spec: dict[str, Any]) -> str:
    return """#!/usr/bin/env bash
# Hand-off: GCP detectors via splunk-observability-native-ops.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

echo "==> Render GCP detectors via splunk-observability-native-ops:"
echo "    bash ${PROJECT_ROOT}/skills/splunk-observability-native-ops/scripts/setup.sh --render"
"""


# ---------------------------------------------------------------------------
# Plan sections.
# ---------------------------------------------------------------------------


def render_readme(spec: dict[str, Any]) -> str:
    auth = spec["authentication"]
    auth_mode = auth["mode"]
    psk = auth.get("project_service_keys") or []
    project_count = len(psk) if auth_mode == "service_account_key" else "managed by projects.syncMode"
    if auth_mode == "service_account_key":
        credential_step = "Create the GCP SA and key: `bash gcloud-cli/create-sa.sh`"
        role_step = "Bind roles: `bash gcloud-cli/bind-roles.sh`"
        apply_credential = "--key-file /secure/path/gcp-sa-key.json"
        terraform_review = "Review `rest/create.json` and the optional `terraform/main.tf` handoff."
    else:
        credential_step = (
            "Obtain Splunk's official generated `gcp_wif_config.json`; do not construct or edit it"
        )
        role_step = "Store it as a mode-600 regular file"
        apply_credential = "--wif-config-file /secure/path/gcp_wif_config.json"
        terraform_review = (
            "Review `rest/create.json`; Terraform WIF arguments are intentionally not claimed."
        )

    return f"""# Splunk Observability Cloud <-> GCP Integration ({spec['integration_name']})

Generated by [`{SKILL_NAME}`] at {datetime.now(timezone.utc).isoformat()}.

## TL;DR

- Realm: `{spec['realm']}`
- Integration name: `{spec['integration_name']}`
- Auth mode: `{auth_mode}`
- Projects: {project_count}
- Services mode: `{spec['services']['mode']}` ({len(spec['services']['explicit'])} explicit)
- Poll rate: `{spec['connection']['poll_rate_seconds']}` s
- Named token: `{spec['named_token'] or '(default)'}`

## Next steps

1. {credential_step}.
2. {role_step}.
3. {terraform_review}
4. Apply: `bash {SKILL_NAME}/scripts/setup.sh --apply --realm {spec['realm']} --token-file /secure/path/splunk_token {apply_credential}`
5. Validate: `bash {SKILL_NAME}/scripts/setup.sh --validate --live`

See `coverage-report.json` for per-section coverage status.
"""


# ---------------------------------------------------------------------------
# Write helpers.
# ---------------------------------------------------------------------------


def write_text(path: Path, text: str, label: str | None = None) -> None:
    assert_no_secrets_in_text(text, label or path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Top-level render.
# ---------------------------------------------------------------------------


def render(
    spec: dict[str, Any],
    output_dir: Path,
    *,
    explain: bool = False,
    list_services: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    for sub in ("rest", "terraform", "gcloud-cli", "handoffs"):
        target = output_dir / sub
        if target.exists():
            shutil.rmtree(target)

    coverage = coverage_for(spec)

    write_text(output_dir / "README.md", render_readme(spec))

    # REST payloads.
    rest_dir = output_dir / "rest"
    rest_dir.mkdir(parents=True, exist_ok=True)
    payload = render_rest_payload(spec)
    write_text(rest_dir / "create.json", json.dumps(payload, indent=2) + "\n")
    write_text(
        rest_dir / "project-key-file-manifest.json",
        json.dumps(
            [
                {"projectId": entry.get("project_id", ""), "keyFile": entry.get("key_file", "")}
                for entry in spec["authentication"].get("project_service_keys", [])
                if isinstance(entry, dict)
            ],
            indent=2,
        ) + "\n",
    )
    wif_config_file = ""
    if spec["authentication"]["mode"] == "workload_identity_federation":
        wif_config_file = str(
            spec["authentication"]["workload_identity_federation"].get("config_file", "")
        )
    write_text(
        rest_dir / "wif-config-file-manifest.json",
        json.dumps(
            {
                "authMethod": (
                    "WORKLOAD_IDENTITY_FEDERATION"
                    if wif_config_file
                    else "SERVICE_ACCOUNT_KEY"
                ),
                "configFile": wif_config_file,
            },
            indent=2,
        ) + "\n",
    )
    update_payload = {**payload, "enabled": True, "id": "${INTEGRATION_ID}"}
    write_text(rest_dir / "update.json", json.dumps(update_payload, indent=2) + "\n")

    # Terraform.
    tf_dir = output_dir / "terraform"
    tf_dir.mkdir(parents=True, exist_ok=True)
    write_text(tf_dir / "main.tf", render_terraform_main(spec))
    write_text(tf_dir / "variables.tf", render_terraform_variables(spec))

    # GCloud CLI.
    if (
        spec["gcloud_cli_render"]
        and spec["authentication"]["mode"] == "service_account_key"
    ):
        cli_dir = output_dir / "gcloud-cli"
        cli_dir.mkdir(parents=True, exist_ok=True)
        create_sa = render_gcloud_cli_create_sa(spec)
        write_text(cli_dir / "create-sa.sh", create_sa)
        os.chmod(cli_dir / "create-sa.sh", 0o755)
        bind_sh = render_gcloud_cli_bind_roles(spec)
        write_text(cli_dir / "bind-roles.sh", bind_sh)
        os.chmod(cli_dir / "bind-roles.sh", 0o755)

    # Handoffs.
    handoffs_dir = output_dir / "handoffs"
    handoffs_dir.mkdir(parents=True, exist_ok=True)
    h = spec["handoffs"]
    if h["splunk_ta_google_cloud"]:
        sh = render_handoff_ta_3088(spec)
        write_text(handoffs_dir / "handoff-splunk-ta-google-cloud-3088.sh", sh)
        os.chmod(handoffs_dir / "handoff-splunk-ta-google-cloud-3088.sh", 0o755)
    if h["gke_otel_collector"]:
        sh = render_handoff_gke_otel(spec)
        write_text(handoffs_dir / "handoff-gke-otel-collector.sh", sh)
        os.chmod(handoffs_dir / "handoff-gke-otel-collector.sh", 0o755)
    if h["dashboards"]:
        sh = render_handoff_dashboards(spec)
        write_text(handoffs_dir / "handoff-dashboards.sh", sh)
        os.chmod(handoffs_dir / "handoff-dashboards.sh", 0o755)
    if h["detectors"]:
        sh = render_handoff_detectors(spec)
        write_text(handoffs_dir / "handoff-detectors.sh", sh)
        os.chmod(handoffs_dir / "handoff-detectors.sh", 0o755)

    # State placeholder.
    state_dir = output_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "apply-state.json"
    if not state_path.exists():
        write_text(state_path, json.dumps({"steps": []}, indent=2) + "\n")
    os.chmod(state_path, 0o600)
    cred_hash_path = state_dir / "credential-hashes.json"
    if not cred_hash_path.exists():
        write_text(
            cred_hash_path,
            json.dumps(
                {"project_key_sha256": {}, "wif_config_sha256": {}},
                indent=2,
            ) + "\n",
        )
    os.chmod(cred_hash_path, 0o600)

    # Coverage report.
    write_text(
        output_dir / "coverage-report.json",
        json.dumps(
            {
                "api_version": API_VERSION,
                "realm": spec["realm"],
                "integration_name": spec["integration_name"],
                "auth_method": spec["authentication"]["mode"].upper(),
                "projects_sync_mode": spec["projects"]["sync_mode"],
                "wif_config_delivery": (
                    "file-backed compact JSON string"
                    if spec["authentication"]["mode"] == "workload_identity_federation"
                    else None
                ),
                "coverage": coverage,
                "warnings": spec.get("_warnings", []),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ) + "\n",
    )

    # Apply plan.
    auth_mode = spec["authentication"]["mode"]
    apply_plan = {
        "api_version": API_VERSION,
        "ordered_steps": [
            {
                "step": (
                    "gcloud_cli.create_sa"
                    if auth_mode == "service_account_key"
                    else "prerequisites.obtain_official_wif_config"
                ),
                "description": (
                    "Create GCP SA + download key + bind Monitoring Viewer + Compute Viewer roles"
                    if auth_mode == "service_account_key"
                    else (
                        "Obtain Splunk's official generated gcp_wif_config.json and store it "
                        "as a mode-600 file; no pool/provider/principal values are fabricated"
                    )
                ),
                "operator_driven": True,
            },
            {
                "step": "integration.upsert",
                "idempotency_key": f"gcp-upsert:{spec['integration_name']}",
                "coverage": coverage["authentication.mode"]["status"],
            },
            {
                "step": "validation.discover",
                "idempotency_key": f"gcp-discover:{spec['integration_name']}",
                "coverage": coverage["validation.live_get"]["status"],
            },
        ],
    }
    write_text(output_dir / "apply-plan.json", json.dumps(apply_plan, indent=2) + "\n")

    result: dict[str, Any] = {
        "output_dir": str(output_dir),
        "coverage_summary": {
            "total": len(coverage),
            "by_status": {
                status: sum(1 for v in coverage.values() if v["status"] == status)
                for status in ("api_apply", "api_validate", "deeplink", "handoff", "not_applicable")
            },
        },
        "warnings": spec.get("_warnings", []),
        "files": sorted(p.relative_to(output_dir).as_posix() for p in output_dir.rglob("*") if p.is_file()),
    }
    if explain:
        result["explain"] = [
            f"{step['step']} ({step.get('coverage', 'operator_driven')}; key={step.get('idempotency_key', 'n/a')})"
            for step in apply_plan["ordered_steps"]
        ]
    if list_services:
        result["services"] = load_services_enum()
    return result


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--realm", default="")
    parser.add_argument("--key-file", action="append", default=[])
    parser.add_argument("--wif-config-file", default="")
    parser.add_argument("--explain", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--list-services", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    spec_path = Path(args.spec)
    if not spec_path.is_file():
        print(f"FAIL: spec file not found: {spec_path}", flush=True)
        return 2

    if args.list_services:
        services = load_services_enum()
        if args.json:
            print(json.dumps({"services": services}, indent=2))
        else:
            for s in services:
                print(s)
        return 0

    try:
        spec = load_spec(spec_path)
        spec = validate_spec(
            spec,
            realm_override=args.realm or None,
            key_file_overrides=args.key_file or None,
            wif_config_file_override=args.wif_config_file or None,
        )
    except RenderError as exc:
        print(f"FAIL: {exc}", flush=True)
        return 2

    output_dir = Path(args.output_dir).resolve()
    try:
        result = render(spec, output_dir, explain=args.explain)
    except RenderError as exc:
        print(f"FAIL: {exc}", flush=True)
        return 2

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        summary = result["coverage_summary"]
        by_status = ", ".join(f"{k}={v}" for k, v in summary["by_status"].items())
        print(f"render: OK -> {result['output_dir']} ({summary['total']} coverage entries; {by_status})")
        for w in result.get("warnings", []):
            print(f"WARN: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
