"""Manifest and conversion helpers for Splunk MCP custom tools."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yaml_compat import load_yaml_or_json


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / "skills"

SOURCE_FILENAME = "mcp_tools.source.yaml"
GENERATED_FILENAME = "mcp_tools.json"

MANIFEST_ROOT_KEYS = {
    "name",
    "description",
    "version",
    "author",
    "external_app_id",
    "tools",
    "coverage",
}
MANIFEST_TOOL_KEYS = {
    "id",
    "name",
    "title",
    "description",
    "category",
    "tags",
    "time_range",
    "row_limiter",
    "spl",
    "arguments",
    "examples",
    "annotations",
}
MANIFEST_COVERAGE_KEYS = {
    "id",
    "status",
    "tool",
    "builtin_tool",
    "reason",
    "notes",
}

LEGACY_ROOT_KEYS = {"name", "description", "version", "author", "tools"}
LEGACY_TOOL_KEYS = {
    "_key",
    "name",
    "title",
    "description",
    "category",
    "tags",
    "time_range",
    "row_limiter",
    "spl",
    "arguments",
    "examples",
}

SUPPORTED_EXTERNAL_APP_IDS = {
    "es",
    "ari",
    "saa",
    "soar",
    "oncall",
    "sc4s",
    "sc4snmp",
    "o11y_platform",
}

VALID_COVERAGE_STATUSES = {
    "mcp_tool",
    "covered_by_builtin_mcp",
    "live_lab_only",
    "excluded_with_reason",
}

RISKY_SPL_COMMANDS = {
    "collect",
    "delete",
    "map",
    "mcollect",
    "outputcsv",
    "outputlookup",
    "runshellscript",
    "script",
    "sendemail",
}

SENSITIVE_OUTPUT_FIELDS = {
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "bearer_token",
    "clear_password",
    "password",
    "passwd",
    "private_key",
    "secret",
    "session_key",
    "token",
}

ALLOWED_INITIAL_COMMANDS = {
    "mcatalog",
    "makeresults",
    "rest",
    "search",
    "tstats",
}

ALLOWED_PIPELINE_COMMANDS = {
    "addinfo",
    "append",
    "appendcols",
    "appendpipe",
    "bin",
    "bucket",
    "chart",
    "convert",
    "dedup",
    "eval",
    "eventstats",
    "fields",
    "fieldsummary",
    "filldown",
    "fillnull",
    "format",
    "head",
    "mcatalog",
    "noop",
    "rare",
    "rename",
    "rest",
    "rex",
    "search",
    "sort",
    "spath",
    "stats",
    "streamstats",
    "table",
    "timechart",
    "top",
    "tstats",
    "where",
}

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_COMMAND_RE = re.compile(r"(?i)(^|\|)\s*([a-z][a-z0-9_]*)")
_PROJECTION_FIELDS_RE = re.compile(r"(?i)(^|\|)\s*(table|fields)\s+([^|\]]+)")
_SECRET_SHAPE_RE = re.compile(
    r"(?i)(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{12,}"
)


class ManifestError(ValueError):
    """Raised when MCP tool source data is invalid."""


@dataclass(frozen=True)
class ValidationResult:
    path: Path
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def load_manifest(path: Path) -> dict[str, Any]:
    payload = load_yaml_or_json(path.read_text(encoding="utf-8"), source=str(path))
    if not isinstance(payload, dict):
        raise ManifestError(f"{path}: source manifest root must be an object")
    return payload


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ManifestError(f"{path}: JSON root must be an object")
    return payload


def find_source_manifests(paths: list[str] | None = None) -> list[Path]:
    if not paths:
        return sorted(SKILLS_DIR.glob(f"*/{SOURCE_FILENAME}"))

    manifests: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.is_absolute():
            path = REPO_ROOT / path
        if path.is_dir():
            path = path / SOURCE_FILENAME
        manifests.append(path)
    return sorted(manifests)


def find_legacy_json(paths: list[str] | None = None) -> list[Path]:
    if not paths:
        return sorted(SKILLS_DIR.glob(f"*/{GENERATED_FILENAME}"))

    json_paths: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.is_absolute():
            path = REPO_ROOT / path
        if path.is_dir():
            path = path / GENERATED_FILENAME
        elif path.name == SOURCE_FILENAME:
            path = path.with_name(GENERATED_FILENAME)
        json_paths.append(path)
    return sorted(json_paths)


def validate_manifest_payload(payload: dict[str, Any], *, source: str) -> list[str]:
    errors: list[str] = []
    required = MANIFEST_ROOT_KEYS
    missing = sorted(required - set(payload))
    if missing:
        errors.append(f"{source}: missing source keys: {', '.join(missing)}")
    unknown_root = sorted(set(payload) - MANIFEST_ROOT_KEYS)
    if unknown_root:
        errors.append(f"{source}: unknown source keys: {', '.join(unknown_root)}")

    external_app_id = str(payload.get("external_app_id", "")).strip()
    if external_app_id not in SUPPORTED_EXTERNAL_APP_IDS:
        errors.append(
            f"{source}: external_app_id must be one of "
            f"{', '.join(sorted(SUPPORTED_EXTERNAL_APP_IDS))}"
        )

    for key in ("name", "description", "version", "author"):
        if not isinstance(payload.get(key), str) or not payload.get(key, "").strip():
            errors.append(f"{source}: {key} must be a non-empty string")

    tools = payload.get("tools")
    tool_ids: set[str] = set()
    if not isinstance(tools, list) or not tools:
        errors.append(f"{source}: tools must be a non-empty list")
        tools = []

    for index, tool in enumerate(tools):
        if not isinstance(tool, dict):
            errors.append(f"{source}: tools[{index}] must be an object")
            continue
        unknown_tool_keys = sorted(set(tool) - MANIFEST_TOOL_KEYS)
        if unknown_tool_keys:
            errors.append(f"{source}: tools[{index}] unknown keys: {', '.join(unknown_tool_keys)}")
        tool_id = str(tool.get("id", "")).strip()
        if not _NAME_RE.fullmatch(tool_id):
            errors.append(f"{source}: tools[{index}].id must match {_NAME_RE.pattern}")
            continue
        if tool_id in tool_ids:
            errors.append(f"{source}: duplicate tool id: {tool_id}")
        tool_ids.add(tool_id)

        expected_name = f"{external_app_id}_{tool_id}" if external_app_id else ""
        name = str(tool.get("name") or expected_name)
        if expected_name and name != expected_name:
            errors.append(f"{source}: tools[{index}].name must be {expected_name}")
        if name.startswith("splunk_"):
            errors.append(f"{source}: tools[{index}].name must not use splunk_ prefix")

        for field in ("title", "description", "spl"):
            if not isinstance(tool.get(field), str) or not tool.get(field, "").strip():
                errors.append(f"{source}: tools[{index}].{field} must be a non-empty string")

        for field in ("time_range", "row_limiter"):
            if not isinstance(tool.get(field), bool):
                errors.append(f"{source}: tools[{index}].{field} must be a boolean")

        if tool.get("arguments") not in (None, []):
            errors.append(f"{source}: tools[{index}].arguments must be omitted or [] for v1")

        tags = tool.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            errors.append(f"{source}: tools[{index}].tags must be a list of strings")

        examples = tool.get("examples", [])
        if not isinstance(examples, list) or not all(
            isinstance(example, (str, dict)) for example in examples
        ):
            errors.append(f"{source}: tools[{index}].examples must be strings or objects")
        annotations = tool.get("annotations")
        if annotations is not None and not isinstance(annotations, dict):
            errors.append(f"{source}: tools[{index}].annotations must be an object")

        spl = str(tool.get("spl", ""))
        errors.extend(f"{source}: tools[{index}] {error}" for error in validate_spl_safety(spl))

    coverage = payload.get("coverage")
    if not isinstance(coverage, list) or not coverage:
        errors.append(f"{source}: coverage must be a non-empty list")
        coverage = []

    mcp_tool_refs: set[str] = set()
    coverage_ids: set[str] = set()
    for index, entry in enumerate(coverage):
        if not isinstance(entry, dict):
            errors.append(f"{source}: coverage[{index}] must be an object")
            continue
        unknown_coverage_keys = sorted(set(entry) - MANIFEST_COVERAGE_KEYS)
        if unknown_coverage_keys:
            errors.append(
                f"{source}: coverage[{index}] unknown keys: {', '.join(unknown_coverage_keys)}"
            )
        coverage_id = str(entry.get("id", "")).strip()
        if not coverage_id:
            errors.append(f"{source}: coverage[{index}].id is required")
        elif coverage_id in coverage_ids:
            errors.append(f"{source}: duplicate coverage id: {coverage_id}")
        coverage_ids.add(coverage_id)

        status = str(entry.get("status", "")).strip()
        if status not in VALID_COVERAGE_STATUSES:
            errors.append(
                f"{source}: coverage[{index}].status must be one of "
                f"{', '.join(sorted(VALID_COVERAGE_STATUSES))}"
            )
        if status == "mcp_tool":
            tool_ref = str(entry.get("tool", "")).strip()
            if not tool_ref:
                errors.append(f"{source}: coverage[{index}].tool is required for mcp_tool")
            elif tool_ref not in tool_ids:
                errors.append(f"{source}: coverage[{index}].tool references unknown tool {tool_ref}")
            else:
                mcp_tool_refs.add(tool_ref)
        if status in {"excluded_with_reason", "live_lab_only"}:
            reason = str(entry.get("reason", "")).strip()
            if not reason:
                errors.append(f"{source}: coverage[{index}].reason is required for {status}")
        if status == "covered_by_builtin_mcp":
            builtin = str(entry.get("builtin_tool", "")).strip()
            if not builtin:
                errors.append(f"{source}: coverage[{index}].builtin_tool is required")

    unreferenced_tools = sorted(tool_ids - mcp_tool_refs)
    if unreferenced_tools:
        errors.append(f"{source}: tools missing coverage entries: {', '.join(unreferenced_tools)}")

    return errors


def legacy_doc_from_manifest(payload: dict[str, Any], *, source: str) -> dict[str, Any]:
    errors = validate_manifest_payload(payload, source=source)
    if errors:
        raise ManifestError("\n".join(errors))

    external_app_id = str(payload["external_app_id"]).strip()
    tools = []
    for tool in payload["tools"]:
        tool_id = str(tool["id"]).strip()
        name = str(tool.get("name") or f"{external_app_id}_{tool_id}").strip()
        tags = [str(tag).strip() for tag in tool.get("tags", []) if str(tag).strip()]
        examples = _legacy_examples(tool.get("examples", []))
        tools.append(
            {
                "_key": f"{external_app_id}:{name}",
                "name": name,
                "title": str(tool["title"]).strip(),
                "description": str(tool["description"]).strip(),
                "category": str(tool.get("category") or external_app_id).strip(),
                "tags": tags,
                "time_range": bool(tool["time_range"]),
                "row_limiter": bool(tool["row_limiter"]),
                "spl": str(tool["spl"]).strip(),
                "arguments": [],
                "examples": examples,
            }
        )

    return {
        "name": str(payload["name"]).strip(),
        "description": str(payload["description"]).strip(),
        "version": str(payload["version"]).strip(),
        "author": str(payload["author"]).strip(),
        "tools": tools,
    }


def validate_legacy_doc(
    payload: dict[str, Any],
    *,
    source: str,
    enforce_generated_rules: bool = False,
) -> list[str]:
    errors: list[str] = []
    missing_root = sorted(LEGACY_ROOT_KEYS - set(payload))
    if missing_root:
        errors.append(f"{source}: missing root keys: {', '.join(missing_root)}")

    tools = payload.get("tools")
    if not isinstance(tools, list) or not tools:
        errors.append(f"{source}: tools must be a non-empty list")
        return errors

    seen_keys: set[str] = set()
    seen_names: set[str] = set()
    external_ids: set[str] = set()
    for index, tool in enumerate(tools):
        if not isinstance(tool, dict):
            errors.append(f"{source}: tools[{index}] must be an object")
            continue
        missing_tool = sorted(LEGACY_TOOL_KEYS - set(tool))
        if missing_tool:
            errors.append(f"{source}: tools[{index}] missing keys: {', '.join(missing_tool)}")
        key = str(tool.get("_key", "")).strip()
        name = str(tool.get("name", "")).strip()
        if key in seen_keys:
            errors.append(f"{source}: duplicate tool _key: {key}")
        if name in seen_names:
            errors.append(f"{source}: duplicate tool name: {name}")
        seen_keys.add(key)
        seen_names.add(name)
        if ":" in key:
            external_ids.add(key.split(":", 1)[0])

        if not name:
            errors.append(f"{source}: tools[{index}].name is required")
        if tool.get("arguments") not in ([], None):
            errors.append(f"{source}: tools[{index}].arguments must be [] for v1")
        if enforce_generated_rules:
            if not any(name.startswith(f"{prefix}_") for prefix in SUPPORTED_EXTERNAL_APP_IDS):
                errors.append(f"{source}: tools[{index}].name has unsupported prefix: {name}")
            if name.startswith("splunk_"):
                errors.append(f"{source}: tools[{index}].name must not use splunk_ prefix")
        errors.extend(
            f"{source}: tools[{index}] {error}"
            for error in validate_spl_safety(str(tool.get("spl", "")))
        )

    if enforce_generated_rules:
        unsupported = sorted(external_ids - SUPPORTED_EXTERNAL_APP_IDS)
        if unsupported:
            errors.append(f"{source}: unsupported generated external_app_id values: {', '.join(unsupported)}")
    return errors


def validate_spl_safety(spl: str) -> list[str]:
    errors: list[str] = []
    stripped = spl.strip()
    if not stripped:
        return ["SPL is empty"]
    if _SECRET_SHAPE_RE.search(stripped):
        errors.append("SPL appears to contain secret-shaped material")
    for field in _unsafe_projection_fields(stripped):
        if field == "*":
            errors.append("SPL uses wildcard output projection")
        else:
            errors.append(f"SPL outputs sensitive field: {field}")

    commands = _extract_spl_commands(stripped)
    if not commands:
        errors.append("SPL must start with | rest, | tstats, | mcatalog, | makeresults, or search")
        return errors

    first = commands[0]
    if first not in ALLOWED_INITIAL_COMMANDS:
        errors.append("SPL must start with | rest, | tstats, | mcatalog, | makeresults, or search")

    for command in commands:
        if command in RISKY_SPL_COMMANDS:
            errors.append(f"SPL uses risky command: {command}")
        elif command not in ALLOWED_PIPELINE_COMMANDS:
            errors.append(f"SPL uses unsupported command for generated tools: {command}")
    return errors


def _extract_spl_commands(spl: str) -> list[str]:
    if spl.lstrip().startswith("|"):
        return [match.group(2).lower() for match in _COMMAND_RE.finditer(spl)]

    first_segment, separator, remainder = spl.partition("|")
    first_token_match = re.match(r"\s*([A-Za-z][A-Za-z0-9_]*)", first_segment)
    first_token = first_token_match.group(1).lower() if first_token_match else ""
    if first_token == "search":
        return [match.group(2).lower() for match in _COMMAND_RE.finditer(spl)]
    if first_token in RISKY_SPL_COMMANDS or first_token in ALLOWED_PIPELINE_COMMANDS:
        return [match.group(2).lower() for match in _COMMAND_RE.finditer(spl)]
    if first_token in ALLOWED_INITIAL_COMMANDS:
        return [match.group(2).lower() for match in _COMMAND_RE.finditer(spl)]

    commands = ["search"]
    if separator:
        commands.extend(match.group(2).lower() for match in _COMMAND_RE.finditer(f"|{remainder}"))
    return commands


def _unsafe_projection_fields(spl: str) -> list[str]:
    fields: list[str] = []
    for match in _PROJECTION_FIELDS_RE.finditer(spl):
        command = match.group(2).lower()
        raw_fields = match.group(3)
        raw_tokens = [token for token in re.split(r"[\s,]+", raw_fields) if token]
        if command == "fields" and raw_tokens and raw_tokens[0] == "-":
            continue
        for raw_field in raw_tokens:
            field = raw_field.strip().strip("\"'`")
            if not field or field in {"+", "-"}:
                continue
            if field == "*":
                fields.append(field)
                continue
            normalized = re.sub(r"[^a-z0-9_]", "", field.lower())
            if normalized in SENSITIVE_OUTPUT_FIELDS:
                fields.append(field)
    return fields


def rest_batch_payload(legacy_doc: dict[str, Any], *, external_app_id: str | None = None) -> dict[str, Any]:
    app_id = external_app_id or infer_external_app_id(legacy_doc)
    return {
        "external_app_id": app_id,
        "tools": [legacy_tool_to_rest_tool(tool, app_id) for tool in legacy_doc.get("tools", [])],
    }


def infer_external_app_id(legacy_doc: dict[str, Any]) -> str:
    candidates: set[str] = set()
    for tool in legacy_doc.get("tools", []):
        if not isinstance(tool, dict):
            continue
        key = str(tool.get("_key", ""))
        if ":" in key:
            candidates.add(key.split(":", 1)[0])
            continue
        category = str(tool.get("category", "")).strip()
        if category:
            candidates.add(category)
    if len(candidates) != 1:
        raise ManifestError(
            "Unable to infer a single external_app_id from mcp_tools.json; "
            "use one app-specific file at a time"
        )
    return next(iter(candidates))


def legacy_tool_to_rest_tool(tool: dict[str, Any], external_app_id: str) -> dict[str, Any]:
    name = str(tool.get("name", "")).strip()
    input_schema = _input_schema_from_arguments(tool.get("arguments", []))
    rest_tool = {
        "name": name,
        "title": str(tool.get("title", name)).strip() or name,
        "description": str(tool.get("description", "")).strip(),
        "inputSchema": input_schema,
        "_meta": {
            "external_app_id": external_app_id,
            "tags": [str(tag).strip() for tag in tool.get("tags", []) if str(tag).strip()],
            "examples": _rest_examples(tool.get("examples", [])),
            "execution": {
                "type": "spl",
                "template": str(tool.get("spl", "")).strip(),
                "row_limiter": bool(tool.get("row_limiter", True)),
                "time_range": bool(tool.get("time_range", True)),
            },
        },
    }
    return rest_tool


def rest_tool_id(tool: dict[str, Any], external_app_id: str) -> str:
    name = str(tool.get("name", "")).strip()
    normalized_name = name if name.startswith(f"{external_app_id}_") else f"{external_app_id}_{name}"
    return f"{external_app_id}:{normalized_name}"


def generated_json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=False) + "\n"


def coverage_report() -> dict[str, Any]:
    skills: list[dict[str, Any]] = []
    totals = {
        "skills": 0,
        "with_manifest": 0,
        "legacy_mcp_json": 0,
        "uncovered": 0,
        "checks": 0,
        "mcp_tool": 0,
        "covered_by_builtin_mcp": 0,
        "live_lab_only": 0,
        "excluded_with_reason": 0,
    }
    for skill_dir in sorted(path for path in SKILLS_DIR.iterdir() if path.is_dir() and path.name != "shared"):
        totals["skills"] += 1
        manifest_path = skill_dir / SOURCE_FILENAME
        if not manifest_path.exists():
            legacy_path = skill_dir / GENERATED_FILENAME
            if legacy_path.exists():
                try:
                    legacy_doc = read_json(legacy_path)
                    external_app_id = infer_external_app_id(legacy_doc)
                    tool_count = len(legacy_doc.get("tools", [])) if isinstance(legacy_doc.get("tools"), list) else 0
                    entry = {
                        "skill": skill_dir.name,
                        "status": "legacy_mcp_json",
                        "external_app_id": external_app_id,
                        "tool_count": tool_count,
                        "checks": [],
                    }
                except Exception as exc:  # noqa: BLE001 - coverage report should surface broken legacy files
                    entry = {
                        "skill": skill_dir.name,
                        "status": "legacy_mcp_json",
                        "error": str(exc),
                        "checks": [],
                    }
                totals["legacy_mcp_json"] += 1
                skills.append(entry)
                continue
            totals["uncovered"] += 1
            skills.append({"skill": skill_dir.name, "status": "uncovered", "checks": []})
            continue
        payload = load_manifest(manifest_path)
        checks = payload.get("coverage", [])
        totals["with_manifest"] += 1
        if isinstance(checks, list):
            totals["checks"] += len(checks)
            for check in checks:
                if isinstance(check, dict):
                    status = str(check.get("status", ""))
                    if status in VALID_COVERAGE_STATUSES:
                        totals[status] += 1
        skills.append(
            {
                "skill": skill_dir.name,
                "status": "manifest",
                "external_app_id": payload.get("external_app_id"),
                "tool_count": len(payload.get("tools", [])) if isinstance(payload.get("tools"), list) else 0,
                "checks": deepcopy(checks) if isinstance(checks, list) else [],
            }
        )
    return {"totals": totals, "skills": skills}


def _legacy_examples(examples: Any) -> list[Any]:
    if not isinstance(examples, list):
        return []
    result: list[Any] = []
    for example in examples:
        if isinstance(example, str):
            result.append(example)
        elif isinstance(example, dict):
            name = example.get("name") or example.get("description")
            if isinstance(name, str) and name.strip():
                result.append(name.strip())
    return result


def _rest_examples(examples: Any) -> list[dict[str, Any]]:
    if not isinstance(examples, list):
        return []
    result: list[dict[str, Any]] = []
    for example in examples:
        if isinstance(example, str):
            result.append(
                {
                    "name": example,
                    "description": example,
                    "arguments": {},
                    "expected_use": "Read-only Splunk validation",
                }
            )
        elif isinstance(example, dict):
            item: dict[str, Any] = {}
            for field in ("name", "description", "expected_use"):
                value = example.get(field)
                if isinstance(value, str) and value.strip():
                    item[field] = value.strip()
            args = example.get("arguments")
            item["arguments"] = args if isinstance(args, dict) else {}
            if item:
                result.append(item)
    return result


def _input_schema_from_arguments(arguments: Any) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": {}}
    if not isinstance(arguments, list):
        return schema
    required: list[str] = []
    for arg in arguments:
        if not isinstance(arg, dict):
            continue
        name = arg.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        prop: dict[str, Any] = {
            "type": str(arg.get("type") or "string"),
            "description": str(arg.get("description") or name).strip(),
        }
        for field in ("default", "enum", "minimum", "maximum", "pattern", "validation_message", "title", "examples", "meta"):
            if field in arg:
                prop[field] = deepcopy(arg[field])
        schema["properties"][name.strip()] = prop
        if arg.get("required") is True:
            required.append(name.strip())
    if required:
        schema["required"] = required
    return schema
