#!/usr/bin/env python3
"""Render Splunk Observability Cloud <-> Azure Integration assets.

Reads a YAML or JSON spec (default: ``template.example``) and emits a
render-first plan tree under ``--output-dir``:

- ``rest/``         — POST/PUT /v2/integration payloads (type=Azure)
- ``terraform/``    — signalfx_azure_integration resource + variables
- ``azure-cli/``    — SP creation + role-assignment scripts
- ``bicep/``        — role-assignment.bicep (opt-in)
- ``handoffs/``     — cross-skill driver scripts (opt-in per handoffs.*)
- ``state/``        — placeholder; populated by azure_integration_api.py on apply
- ``coverage-report.json``
- ``apply-plan.json``

The renderer never accepts or writes any secret value.  appId, secretKey, and
the Splunk O11y token are referenced as file-paths only.
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

SKILL_NAME = "splunk-observability-azure-integration"
API_VERSION = f"{SKILL_NAME}/v1"

SUPPORTED_REALMS: tuple[str, ...] = (
    "us0", "us1", "us2", "us3",
    "eu0", "eu1", "eu2",
    "au0", "jp0", "sg0",
)

GOVCLOUD_REALMS: frozenset[str] = frozenset()  # Splunk GovCloud realms are org-specific; no public enum

AZURE_ENVIRONMENTS: tuple[str, ...] = ("AZURE", "AZURE_US_GOVERNMENT")

TERRAFORM_PROVIDER_VERSION_DEFAULT = "~> 9.0"

CONNECTION_MODES: tuple[str, ...] = ("polling", "terraform_only")

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
        return list(data.get("services", []))
    except Exception:
        return []


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
    app_id_file_override: str | None = None,
    secret_file_override: str | None = None,
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
    auth.setdefault("tenant_id", "")
    if not auth["tenant_id"] or auth["tenant_id"] == "00000000-0000-0000-0000-000000000000":
        raise RenderError(
            "authentication.tenant_id is required and must be your real Azure AD tenant ID"
        )
    if app_id_file_override:
        auth["app_id_file"] = app_id_file_override
    if secret_file_override:
        auth["secret_file"] = secret_file_override

    env = spec.setdefault("azure_environment", "AZURE")
    if env not in AZURE_ENVIRONMENTS:
        raise RenderError(
            f"azure_environment must be one of {AZURE_ENVIRONMENTS}, got {env!r}"
        )
    if env == "AZURE_US_GOVERNMENT":
        spec.setdefault("_warnings", []).append(
            "azure_environment=AZURE_US_GOVERNMENT requires a GovCloud Splunk O11y realm. "
            "Contact Splunk for GovCloud org provisioning."
        )

    subs = spec.get("subscriptions") or []
    if not isinstance(subs, list) or not subs:
        raise RenderError("subscriptions must be a non-empty list of Azure subscription IDs")
    placeholder_subs = [s for s in subs if s == "00000000-0000-0000-0000-000000000000"]
    if placeholder_subs:
        raise RenderError(
            "subscriptions contains placeholder UUIDs. Replace with real Azure subscription IDs."
        )
    spec["subscriptions"] = [str(s) for s in subs]

    conn = spec.setdefault("connection", {})
    conn.setdefault("mode", "polling")
    if conn["mode"] not in CONNECTION_MODES:
        raise RenderError(f"connection.mode must be one of {CONNECTION_MODES}")
    poll_rate = int(conn.setdefault("poll_rate_seconds", 300))
    if not 60 <= poll_rate <= 600:
        raise RenderError(f"connection.poll_rate_seconds must be 60..600, got {poll_rate}")
    conn["poll_rate_seconds"] = poll_rate
    conn.setdefault("use_batch_api", True)
    conn.setdefault("import_azure_monitor", True)
    conn.setdefault("sync_guest_os_namespaces", False)

    services = spec.setdefault("services", {})
    services.setdefault("mode", "explicit")
    if services["mode"] not in SERVICES_MODES:
        raise RenderError(f"services.mode must be one of {SERVICES_MODES}")
    services.setdefault("explicit", [])
    services.setdefault("additional_services", [])
    services.setdefault("custom_namespaces_per_service", [])

    known_services = load_services_enum()
    if services["mode"] == "explicit":
        if not services["explicit"] and not services["additional_services"]:
            raise RenderError(
                "services.explicit and services.additional_services are both empty. "
                "Specify at least one Azure service to monitor."
            )
        if known_services:
            unknown = [s for s in services["explicit"] if s not in known_services]
            if unknown:
                services.setdefault("_warnings", []).append(
                    f"unknown services (not in built-in enum, will be passed as-is): {', '.join(unknown)}"
                )

    spec.setdefault("resource_filter_rules", [])
    spec.setdefault("named_token", "")

    tf = spec.setdefault("terraform_provider", {})
    tf.setdefault("source", "splunk-terraform/signalfx")
    tf.setdefault("version", TERRAFORM_PROVIDER_VERSION_DEFAULT)

    spec.setdefault("azure_cli_render", True)
    spec.setdefault("bicep_render", False)

    multi = spec.setdefault("multi_subscription", {})
    multi.setdefault("enabled", False)
    multi.setdefault("management_group_id", "")

    handoffs = spec.setdefault("handoffs", {})
    for k, default in (
        ("splunk_ta_microsoft_cloud_services", False),
        ("microsoft_azure_app", False),
        ("aks_otel_collector", False),
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
    coverage["authentication.tenant"] = {
        "status": "api_apply",
        "notes": f"tenantId {spec['authentication']['tenant_id']}",
    }
    coverage["authentication.sp_credentials"] = {
        "status": "api_apply",
        "notes": "appId + secretKey via file-based delivery; redacted on GET",
    }

    env = spec["azure_environment"]
    coverage["azure_environment"] = {
        "status": "api_apply",
        "notes": f"azureEnvironment={env}",
    }

    coverage["subscriptions"] = {
        "status": "api_apply",
        "notes": f"{len(spec['subscriptions'])} subscription(s)",
    }

    conn = spec["connection"]
    coverage["connection.poll_rate"] = {
        "status": "api_apply",
        "notes": f"pollRate={conn['poll_rate_seconds']}s ({conn['poll_rate_seconds'] * 1000}ms wire)",
    }
    coverage["connection.use_batch_api"] = {
        "status": "api_apply",
        "notes": f"useBatchApi={conn['use_batch_api']}",
    }
    coverage["connection.import_azure_monitor"] = {
        "status": "api_apply",
        "notes": f"importAzureMonitor={conn['import_azure_monitor']}",
    }
    coverage["connection.sync_guest_os_namespaces"] = {
        "status": "api_apply" if conn["sync_guest_os_namespaces"] else "not_applicable",
        "notes": f"syncGuestOsNamespaces={conn['sync_guest_os_namespaces']}",
    }

    services = spec["services"]
    coverage["services.mode"] = {
        "status": "api_apply",
        "notes": f"mode={services['mode']}, {len(services['explicit'])} explicit + {len(services['additional_services'])} additional",
    }
    if services["custom_namespaces_per_service"]:
        coverage["services.custom_namespaces"] = {
            "status": "api_apply",
            "notes": f"{len(services['custom_namespaces_per_service'])} customNamespacesPerService entries",
        }
    else:
        coverage["services.custom_namespaces"] = {"status": "not_applicable", "notes": ""}

    if spec["resource_filter_rules"]:
        coverage["resource_filter_rules"] = {
            "status": "api_apply",
            "notes": f"{len(spec['resource_filter_rules'])} tag-filter rule(s)",
        }
    else:
        coverage["resource_filter_rules"] = {"status": "not_applicable", "notes": "no filter rules"}

    if spec["named_token"]:
        coverage["named_token"] = {
            "status": "api_apply",
            "notes": f"namedToken={spec['named_token']} (WARNING: ForceNew — changes recreate the integration)",
        }
    else:
        coverage["named_token"] = {"status": "not_applicable", "notes": "using default org token"}

    coverage["terraform.resource"] = {
        "status": "api_apply" if conn["mode"] != "polling" else "handoff",
        "notes": f"signalfx_azure_integration in terraform/main.tf (provider {spec['terraform_provider']['version']})",
    }

    if spec["azure_cli_render"]:
        coverage["azure_cli"] = {
            "status": "api_apply",
            "notes": "azure-cli/create-sp.sh + grant-monitoring-reader.sh rendered",
        }
    else:
        coverage["azure_cli"] = {"status": "not_applicable", "notes": "azure_cli_render=false"}

    if spec["bicep_render"]:
        coverage["bicep"] = {
            "status": "api_apply",
            "notes": "bicep/role-assignment.bicep rendered",
        }
    else:
        coverage["bicep"] = {"status": "not_applicable", "notes": "bicep_render=false"}

    if spec["multi_subscription"]["enabled"]:
        mgmt = spec["multi_subscription"]["management_group_id"]
        coverage["multi_subscription"] = {
            "status": "api_apply",
            "notes": f"management_group_id={mgmt or '(per-subscription)'} role assignment",
        }
    else:
        coverage["multi_subscription"] = {"status": "not_applicable", "notes": "single-subscription spec"}

    coverage["validation.live_get"] = {
        "status": "api_validate",
        "notes": "GET /v2/integration/{id} round-trip; drift check for non-redacted fields",
    }
    coverage["validation.credential_hash"] = {
        "status": "api_validate",
        "notes": "SHA-256 of app_id_file+secret_file vs state/credential-hashes.json",
    }

    handoffs = spec["handoffs"]
    for k in ("splunk_ta_microsoft_cloud_services", "microsoft_azure_app", "aks_otel_collector", "dashboards", "detectors"):
        coverage[f"handoff.{k}"] = {
            "status": "handoff" if handoffs[k] else "not_applicable",
            "notes": "",
        }

    return coverage


# ---------------------------------------------------------------------------
# REST payload.
# ---------------------------------------------------------------------------


def render_rest_payload(spec: dict[str, Any], integration_id: str | None = None) -> dict[str, Any]:
    """Produce the canonical POST /v2/integration body (type=Azure).

    pollRate: wire is milliseconds; spec is seconds.
    appId / secretKey: rendered as file-path placeholders only, never the values.
    """
    services = spec["services"]
    conn = spec["connection"]

    payload: dict[str, Any] = {
        "type": "Azure",
        "name": spec["integration_name"],
        "enabled": False,
        "tenantId": spec["authentication"]["tenant_id"],
        "appId": "${APP_ID_FROM_FILE}",
        "secretKey": "${SECRET_KEY_FROM_FILE}",
        "azureEnvironment": spec["azure_environment"],
        "subscriptions": list(spec["subscriptions"]),
        "pollRate": conn["poll_rate_seconds"] * 1000,
        "useBatchApi": bool(conn["use_batch_api"]),
        "importAzureMonitor": bool(conn["import_azure_monitor"]),
        "syncGuestOsNamespaces": bool(conn["sync_guest_os_namespaces"]),
    }

    if services["mode"] == "all_built_in":
        pass  # omit services field — server uses all built-ins
    else:
        explicit = list(services["explicit"])
        if explicit:
            payload["services"] = explicit

    if services["additional_services"]:
        payload["additionalServices"] = list(services["additional_services"])

    if services["custom_namespaces_per_service"]:
        cns: dict[str, list[str]] = {}
        for entry in services["custom_namespaces_per_service"]:
            if isinstance(entry, dict):
                svc = entry.get("service", "")
                ns = list(entry.get("namespaces", []))
                if svc and ns:
                    cns[svc] = ns
        if cns:
            payload["customNamespacesPerService"] = cns

    if spec["resource_filter_rules"]:
        payload["resourceFilterRules"] = [
            {"filter": {"source": rule["filter_source"]}}
            for rule in spec["resource_filter_rules"]
        ]

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

    services_block = ""
    if services["mode"] == "explicit" and services["explicit"]:
        services_block = "  services = " + json.dumps(services["explicit"], indent=4).replace("\n", "\n  ") + "\n"

    additional_block = ""
    if services["additional_services"]:
        additional_block = "  additional_services = " + json.dumps(services["additional_services"]) + "\n"

    named_token_line = f'  named_token = "{spec["named_token"]}"\n' if spec["named_token"] else ""

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

resource "signalfx_azure_integration" "this" {{
  name        = "{spec['integration_name']}"
  enabled     = true

  tenant_id   = var.tenant_id
  app_id      = var.app_id      # sensitive; deliver via TF_VAR_app_id or vault
  secret_key  = var.secret_key  # sensitive; deliver via TF_VAR_secret_key or vault

  environment   = "{spec['azure_environment'].lower().replace('azure_us_government', 'azure_us_government')}"
  subscriptions = {json.dumps(spec['subscriptions'])}

  poll_rate = {conn['poll_rate_seconds']}

  import_azure_monitor      = {str(conn['import_azure_monitor']).lower()}
  use_batch_api             = {str(conn['use_batch_api']).lower()}
  sync_guest_os_namespaces  = {str(conn['sync_guest_os_namespaces']).lower()}

{services_block}{additional_block}{named_token_line}}}
"""


def render_terraform_variables(spec: dict[str, Any]) -> str:
    return f"""variable "tenant_id" {{
  description = "Azure AD Directory (tenant) ID"
  type        = string
}}

variable "app_id" {{
  description = "Azure AD application (client) ID"
  type        = string
  sensitive   = true
}}

variable "secret_key" {{
  description = "Azure AD client secret"
  type        = string
  sensitive   = true
}}
"""


# ---------------------------------------------------------------------------
# Azure CLI scripts.
# ---------------------------------------------------------------------------


def render_azure_cli_create_sp(spec: dict[str, Any]) -> str:
    sub_list = " ".join(
        f"--scopes \"/subscriptions/${{AZ_SUB_ID}}\"" for _ in spec["subscriptions"][:1]
    )
    multi = spec["multi_subscription"]
    scope_comment = ""
    if multi["enabled"] and multi["management_group_id"]:
        scope_comment = (
            f"# For management-group-scoped assignment, use:\n"
            f"#   --scopes \"/providers/Microsoft.Management/managementGroups/{multi['management_group_id']}\""
        )

    return f"""#!/usr/bin/env bash
# Create Azure AD Service Principal for Splunk Observability Azure integration.
# Outputs the SP JSON to /tmp/splunk-azure-sp.json (chmod 600).
# NEVER paste the secret value into this script — the output file is the secret file.
set -euo pipefail

: "${{AZ_SUB_ID:?Set AZ_SUB_ID to your Azure subscription ID}}"

{scope_comment}

az ad sp create-for-rbac \\
  --name splunk-observability-o11y \\
  --role "Monitoring Reader" \\
  --scopes "/subscriptions/${{AZ_SUB_ID}}" \\
  --years 2 --output json > /tmp/splunk-azure-sp.json && chmod 600 /tmp/splunk-azure-sp.json

echo "==> SP created. Contents:"
jq 'del(.password)' /tmp/splunk-azure-sp.json

echo ""
echo "==> appId   : $(jq -r .appId   /tmp/splunk-azure-sp.json)"
echo "==> tenantId: $(jq -r .tenant  /tmp/splunk-azure-sp.json)"
echo ""
echo "==> Write appId to a chmod-600 file:"
echo "    jq -r .appId   /tmp/splunk-azure-sp.json > /tmp/azure-app-id.txt && chmod 600 /tmp/azure-app-id.txt"
echo "    jq -r .password /tmp/splunk-azure-sp.json > /tmp/azure-secret.txt && chmod 600 /tmp/azure-secret.txt"
echo ""
echo "==> Next: bash grant-monitoring-reader.sh"
"""


def render_azure_cli_grant_roles(spec: dict[str, Any]) -> str:
    multi = spec["multi_subscription"]
    scope_block = ""
    if multi["enabled"] and multi["management_group_id"]:
        scope_block = f"""# Management-group-scoped Reader assignment (covers all member subscriptions):
SP_OBJ=$(az ad sp show --id "${{APP_ID}}" --query id -o tsv)
az role assignment create \\
  --assignee-object-id "${{SP_OBJ}}" \\
  --assignee-principal-type ServicePrincipal \\
  --role Reader \\
  --scope "/providers/Microsoft.Management/managementGroups/{multi['management_group_id']}"
"""
    else:
        sub_lines = "\n".join(
            f"  _grant_reader \"${{AZ_SUB_ID_{i+1}:?Set AZ_SUB_ID_{i+1}}}\""
            for i in range(len(spec["subscriptions"]))
        )
        scope_block = f"""_grant_reader() {{
  local sub_id="$1"
  local sp_obj
  sp_obj=$(az ad sp show --id "${{APP_ID}}" --query id -o tsv)
  az role assignment create \\
    --assignee-object-id "${{sp_obj}}" \\
    --assignee-principal-type ServicePrincipal \\
    --role Reader \\
    --scope "/subscriptions/${{sub_id}}"
}}

# Repeat for each subscription in your spec.
# Set environment variables AZ_SUB_ID_1 ... AZ_SUB_ID_{len(spec["subscriptions"])}
{sub_lines}
"""

    return f"""#!/usr/bin/env bash
# Grant Monitoring Reader + Reader roles to the Splunk O11y SP.
# Run after create-sp.sh.
set -euo pipefail

APP_ID_FILE="${{1:-/tmp/azure-app-id.txt}}"
if [[ ! -f "${{APP_ID_FILE}}" ]]; then
  echo "Usage: $0 <app-id-file>" >&2; exit 2
fi
APP_ID="$(cat "${{APP_ID_FILE}}")"
if [[ -z "${{APP_ID}}" ]]; then
  echo "FAIL: app-id-file is empty." >&2; exit 2
fi

{scope_block}

echo "==> Role assignments complete."
echo "==> Required roles per subscription:"
echo "    Monitoring Reader: 43d0d8ad-25c7-4714-9337-8ba259a9fe05"
echo "    Reader:            acdd72a7-3385-48ef-bd42-f606fba81ae7"
"""


# ---------------------------------------------------------------------------
# Bicep.
# ---------------------------------------------------------------------------


def render_bicep_role_assignment(spec: dict[str, Any]) -> str:
    multi = spec["multi_subscription"]
    if multi["enabled"] and multi["management_group_id"]:
        scope_line = "targetScope = 'managementGroup'"
        scope_comment = f"// Management group: {multi['management_group_id']}"
    else:
        scope_line = "targetScope = 'subscription'"
        scope_comment = "// Deploy with: az deployment sub create --template-file role-assignment.bicep --parameters spObjectId=<SP_OBJ_ID>"

    return f"""// Bicep role-assignment for Splunk Observability Azure integration.
// Assigns Monitoring Reader to the Service Principal on this scope.
{scope_comment}
{scope_line}

param spObjectId string

var monitoringReaderId = '43d0d8ad-25c7-4714-9337-8ba259a9fe05'
var readerId          = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'

resource raMonitoring 'Microsoft.Authorization/roleAssignments@2022-04-01' = {{
  name: guid(subscription().id, spObjectId, monitoringReaderId)
  properties: {{
    principalId:      spObjectId
    principalType:    'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions', monitoringReaderId)
  }}
}}

resource raReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {{
  name: guid(subscription().id, spObjectId, readerId)
  properties: {{
    principalId:      spObjectId
    principalType:    'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions', readerId)
  }}
}}
"""


# ---------------------------------------------------------------------------
# Handoff scripts.
# ---------------------------------------------------------------------------


def render_handoff_ta_3110(spec: dict[str, Any]) -> str:
    return """#!/usr/bin/env bash
# Hand-off: Azure log ingestion via Splunk_TA_microsoft_cloud_services (Splunkbase 3110).
# Azure Monitor metrics go through Splunk Observability; Azure logs land in Splunk Platform.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

echo "==> Install Splunk_TA_microsoft_cloud_services (Splunkbase 3110) for Azure log ingestion:"
echo "    bash ${PROJECT_ROOT}/skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id 3110"
echo ""
echo "==> After install, configure Azure AD inputs in the TA for:"
echo "    Activity Logs, Audit Logs, Azure AD Signin Logs, Azure Monitor Logs"
"""


def render_handoff_azure_app_4882(spec: dict[str, Any]) -> str:
    return """#!/usr/bin/env bash
# Hand-off: Microsoft Azure App for Splunk (Splunkbase 4882) — Azure dashboards on Splunk Platform.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

echo "==> Install Microsoft Azure App for Splunk (Splunkbase 4882) for Azure dashboards:"
echo "    bash ${PROJECT_ROOT}/skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id 4882"
"""


def render_handoff_aks_otel(spec: dict[str, Any]) -> str:
    return f"""#!/usr/bin/env bash
# Hand-off: AKS host telemetry via splunk-observability-otel-collector-setup.
# Splunk Observability Azure integration collects Azure Monitor metrics.
# The OTel collector adds richer Kubernetes/host telemetry from AKS nodes.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/../../.." && pwd)"

echo "==> Render Splunk OTel collector for AKS:"
echo "    bash ${{PROJECT_ROOT}}/skills/splunk-observability-otel-collector-setup/scripts/setup.sh --render"
echo ""
echo "==> The OTel collector complements (does not replace) the Azure Monitor integration."
echo "    AKS cluster: microsoft.containerservice/managedclusters metrics via Azure Monitor"
echo "    AKS node host telemetry: cpu/memory/disk/network via the OTel collector."
"""


def render_handoff_dashboards(spec: dict[str, Any]) -> str:
    return """#!/usr/bin/env bash
# Hand-off: Azure dashboards via splunk-observability-dashboard-builder.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

echo "==> Render custom Azure dashboards on top of O11y Azure metrics:"
echo "    bash ${PROJECT_ROOT}/skills/splunk-observability-dashboard-builder/scripts/setup.sh --render"
echo ""
echo "==> Built-in Azure dashboards auto-populate when the integration is healthy."
echo "    No custom rendering is required unless you need bespoke charts."
"""


def render_handoff_detectors(spec: dict[str, Any]) -> str:
    return """#!/usr/bin/env bash
# Hand-off: Azure detectors via splunk-observability-native-ops.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

echo "==> Render Azure detectors via splunk-observability-native-ops:"
echo "    bash ${PROJECT_ROOT}/skills/splunk-observability-native-ops/scripts/setup.sh --render"
"""


# ---------------------------------------------------------------------------
# Plan sections.
# ---------------------------------------------------------------------------


def render_readme(spec: dict[str, Any]) -> str:
    return f"""# Splunk Observability Cloud <-> Azure Integration ({spec['integration_name']})

Generated by [`{SKILL_NAME}`] at {datetime.now(timezone.utc).isoformat()}.

## TL;DR

- Realm: `{spec['realm']}`
- Integration name: `{spec['integration_name']}`
- Tenant ID: `{spec['authentication']['tenant_id']}`
- Azure environment: `{spec['azure_environment']}`
- Subscriptions: {len(spec['subscriptions'])}
- Services mode: `{spec['services']['mode']}` ({len(spec['services']['explicit'])} explicit + {len(spec['services']['additional_services'])} additional)
- Poll rate: `{spec['connection']['poll_rate_seconds']}` s
- Named token: `{spec['named_token'] or '(default)'}`

## Next steps

1. Create the Azure Service Principal: `bash azure-cli/create-sp.sh`
2. Assign roles: `bash azure-cli/grant-monitoring-reader.sh /tmp/azure-app-id.txt`
3. Review `rest/create.json` and `terraform/main.tf`.
4. Apply: `bash {SKILL_NAME}/scripts/setup.sh --apply --realm {spec['realm']} --token-file /tmp/splunk_token --app-id-file /tmp/azure-app-id.txt --secret-file /tmp/azure-secret.txt`
5. Validate: `bash {SKILL_NAME}/scripts/setup.sh --validate --live`

See `coverage-report.json` for per-section coverage status.
"""


# ---------------------------------------------------------------------------
# write helpers.
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

    for sub in ("rest", "terraform", "azure-cli", "bicep", "handoffs", "state"):
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
    update_payload = {**payload, "enabled": True, "id": "${INTEGRATION_ID}"}
    write_text(rest_dir / "update.json", json.dumps(update_payload, indent=2) + "\n")

    # Terraform.
    tf_dir = output_dir / "terraform"
    tf_dir.mkdir(parents=True, exist_ok=True)
    write_text(tf_dir / "main.tf", render_terraform_main(spec))
    write_text(tf_dir / "variables.tf", render_terraform_variables(spec))

    # Azure CLI.
    if spec["azure_cli_render"]:
        cli_dir = output_dir / "azure-cli"
        cli_dir.mkdir(parents=True, exist_ok=True)
        create_sp = render_azure_cli_create_sp(spec)
        write_text(cli_dir / "create-sp.sh", create_sp)
        os.chmod(cli_dir / "create-sp.sh", 0o755)
        grant_sh = render_azure_cli_grant_roles(spec)
        write_text(cli_dir / "grant-monitoring-reader.sh", grant_sh)
        os.chmod(cli_dir / "grant-monitoring-reader.sh", 0o755)

    # Bicep.
    if spec["bicep_render"]:
        bicep_dir = output_dir / "bicep"
        bicep_dir.mkdir(parents=True, exist_ok=True)
        write_text(bicep_dir / "role-assignment.bicep", render_bicep_role_assignment(spec))

    # Handoffs.
    handoffs_dir = output_dir / "handoffs"
    handoffs_dir.mkdir(parents=True, exist_ok=True)
    h = spec["handoffs"]
    if h["splunk_ta_microsoft_cloud_services"]:
        sh = render_handoff_ta_3110(spec)
        write_text(handoffs_dir / "handoff-splunk-ta-3110.sh", sh)
        os.chmod(handoffs_dir / "handoff-splunk-ta-3110.sh", 0o755)
    if h["microsoft_azure_app"]:
        sh = render_handoff_azure_app_4882(spec)
        write_text(handoffs_dir / "handoff-microsoft-azure-app-4882.sh", sh)
        os.chmod(handoffs_dir / "handoff-microsoft-azure-app-4882.sh", 0o755)
    if h["aks_otel_collector"]:
        sh = render_handoff_aks_otel(spec)
        write_text(handoffs_dir / "handoff-aks-otel-collector.sh", sh)
        os.chmod(handoffs_dir / "handoff-aks-otel-collector.sh", 0o755)
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
    write_text(state_path, json.dumps({"steps": []}, indent=2) + "\n")
    os.chmod(state_path, 0o600)
    cred_hash_path = state_dir / "credential-hashes.json"
    write_text(cred_hash_path, json.dumps({"app_id_sha256": "", "secret_sha256": ""}, indent=2) + "\n")
    os.chmod(cred_hash_path, 0o600)

    # Coverage report.
    write_text(
        output_dir / "coverage-report.json",
        json.dumps(
            {
                "api_version": API_VERSION,
                "realm": spec["realm"],
                "integration_name": spec["integration_name"],
                "coverage": coverage,
                "warnings": spec.get("_warnings", []),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ) + "\n",
    )

    # Apply plan.
    apply_plan = {
        "api_version": API_VERSION,
        "ordered_steps": [
            {
                "step": "azure_cli.create_sp",
                "description": "Create Azure AD SP + assign Monitoring Reader + Reader roles",
                "operator_driven": True,
            },
            {
                "step": "integration.upsert",
                "idempotency_key": f"azure-upsert:{spec['integration_name']}",
                "coverage": coverage["authentication.sp_credentials"]["status"],
            },
            {
                "step": "validation.discover",
                "idempotency_key": f"azure-discover:{spec['integration_name']}",
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
    parser.add_argument("--app-id-file", default="")
    parser.add_argument("--secret-file", default="")
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
            app_id_file_override=args.app_id_file or None,
            secret_file_override=args.secret_file or None,
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
