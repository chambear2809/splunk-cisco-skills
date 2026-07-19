#!/usr/bin/env python3
"""Render one staged Lemonade collector config; this render-only action needs PyYAML."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Any


PRIVACY_PROCESSOR = "transform/lemonade_resource_privacy"
LOG_RESOURCE_PROCESSOR = "resource/lemonade_logs"
JOURNALD_RECEIVER = "journald/lemonade"
JOURNALD_PIPELINE = "logs/lemonade"
SECRET_PLACEHOLDER_RE = re.compile(r"\$\{(?:(?:env):)?[A-Z][A-Z0-9_]{0,127}\}")
SENSITIVE_FIELD_KEYS = frozenset(
    {
        "accesstoken",
        "apikey",
        "authorization",
        "clientsecret",
        "password",
        "secret",
        "splunkaccesstoken",
        "token",
        "xauthtoken",
        "xsftoken",
    }
)
SENSITIVE_HEADER_KEYS = frozenset(
    {
        "apikey",
        "authorization",
        "splunkaccesstoken",
        "xapikey",
        "xauthtoken",
        "xsftoken",
    }
)


def normalized_key(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[^a-z0-9]", "", value.lower())


def validate_secret_placeholders(
    value: object, *, parent_is_headers: bool = False
) -> None:
    """Reject literal credentials inherited from any Collector mapping."""

    if isinstance(value, dict):
        for key, child in value.items():
            normalized = normalized_key(key)
            sensitive = normalized in SENSITIVE_FIELD_KEYS or (
                parent_is_headers and normalized in SENSITIVE_HEADER_KEYS
            )
            if sensitive:
                if not isinstance(child, str) or not SECRET_PLACEHOLDER_RE.fullmatch(
                    child
                ):
                    raise ValueError(
                        "credential-bearing Collector fields must use an exact "
                        "uppercase environment placeholder"
                    )
                continue
            validate_secret_placeholders(
                child, parent_is_headers=normalized == "headers"
            )
    elif isinstance(value, list):
        for child in value:
            validate_secret_placeholders(child)


def mapping(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"expected mapping at {key}")
    return value


def strings(parent: dict[str, Any], key: str) -> list[str]:
    value = parent.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"expected string list at {key}")
    return value


def component_type(name: str) -> str:
    return name.split("/", 1)[0]


def validated_scalar(option: str, value: str) -> str:
    """Reject empty or control-bearing values before placing them in YAML/OTTL."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{option} must be non-empty")
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise ValueError(f"{option} must not contain control characters")
    return value


def insert_before_batch(values: list[str], item: str) -> None:
    values[:] = [value for value in values if value != item]
    for index, value in enumerate(values):
        if component_type(value) == "batch":
            values.insert(index, item)
            return
    values.append(item)


def privacy_processor(service_name: str, environment: str) -> dict[str, Any]:
    service_literal = json.dumps(service_name)
    environment_literal = json.dumps(environment)
    return {
        "error_mode": "propagate",
        "trace_statements": [
            {
                "context": "span",
                "statements": [
                    (
                        'set(resource.attributes["deployment.environment.name"], '
                        f"{environment_literal}) where "
                        'resource.attributes["service.name"] '
                        f"== {service_literal} and "
                        'resource.attributes["deployment.environment.name"] == nil'
                    ),
                    (
                        'set(resource.attributes["deployment.environment"], '
                        f"{environment_literal}) where "
                        'resource.attributes["service.name"] '
                        f"== {service_literal} and "
                        'resource.attributes["deployment.environment"] == nil'
                    ),
                    (
                        'set(span.status.message, "[REDACTED]") where '
                        "span.status.code == STATUS_CODE_ERROR and "
                        'resource.attributes["service.name"] '
                        f"== {service_literal}"
                    ),
                    (
                        'set(span.attributes["error.type"], "lemonade.error") where '
                        "span.status.code == STATUS_CODE_ERROR and "
                        'span.attributes["error.type"] == nil and '
                        'resource.attributes["service.name"] '
                        f"== {service_literal}"
                    ),
                ],
            }
        ],
    }


def log_resource_processor(service_name: str, environment: str) -> dict[str, Any]:
    return {
        "attributes": [
            {"key": "service.name", "value": service_name, "action": "upsert"},
            {
                "key": "deployment.environment.name",
                "value": environment,
                "action": "insert",
            },
            {
                "key": "deployment.environment",
                "value": environment,
                "action": "insert",
            },
        ]
    }


def journald_receiver(unit: str) -> dict[str, Any]:
    return {
        "start_at": "end",
        "units": [unit],
        "priority": "info",
    }


def log_processors(source: dict[str, Any]) -> list[str]:
    result = [
        item
        for item in strings(source, "processors")
        if component_type(item)
        in {"memory_limiter", "resource_detection", "resourcedetection", "batch"}
    ]
    insert_before_batch(result, LOG_RESOURCE_PROCESSOR)
    return result


def journald_pipeline(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "receivers": [JOURNALD_RECEIVER],
        "processors": log_processors(source),
        "exporters": list(strings(source, "exporters")),
    }


def component_references(
    pipelines: dict[str, Any], component: str
) -> list[tuple[str, str, int]]:
    references: list[tuple[str, str, int]] = []
    for pipeline_name, pipeline in pipelines.items():
        if not isinstance(pipeline, dict):
            continue
        for field in ("receivers", "processors", "exporters"):
            values = pipeline.get(field)
            if not isinstance(values, list):
                continue
            references.extend(
                (str(pipeline_name), field, index)
                for index, value in enumerate(values)
                if value == component
            )
    return references


def recognize_privacy_processor(component: Any) -> tuple[str, str]:
    """Return the prior service/environment only for our exact rendered shape."""

    try:
        first_statement = component["trace_statements"][0]["statements"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(
            f"managed component collision at {PRIVACY_PROCESSOR}: unknown shape"
        ) from exc
    if not isinstance(first_statement, str):
        raise ValueError(
            f"managed component collision at {PRIVACY_PROCESSOR}: unknown shape"
        )

    prefix = 'set(resource.attributes["deployment.environment.name"], '
    middle = ') where resource.attributes["service.name"] == '
    decoder = json.JSONDecoder()
    if not first_statement.startswith(prefix):
        raise ValueError(
            f"managed component collision at {PRIVACY_PROCESSOR}: unknown shape"
        )
    try:
        environment, position = decoder.raw_decode(first_statement, len(prefix))
        if not first_statement.startswith(middle, position):
            raise ValueError
        service_name, _ = decoder.raw_decode(first_statement, position + len(middle))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"managed component collision at {PRIVACY_PROCESSOR}: unknown shape"
        ) from exc
    if not isinstance(service_name, str) or not isinstance(environment, str):
        raise ValueError(
            f"managed component collision at {PRIVACY_PROCESSOR}: unknown values"
        )
    validated_scalar("prior rendered service name", service_name)
    validated_scalar("prior rendered deployment environment", environment)
    if component != privacy_processor(service_name, environment):
        raise ValueError(
            f"managed component collision at {PRIVACY_PROCESSOR}: "
            "not an exact recognized prior render"
        )
    return service_name, environment


def recognize_log_resource_processor(component: Any) -> tuple[str, str]:
    """Return the prior service/environment only for our exact rendered shape."""

    try:
        attributes = component["attributes"]
        service_name = attributes[0]["value"]
        environment = attributes[1]["value"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(
            f"managed component collision at {LOG_RESOURCE_PROCESSOR}: unknown shape"
        ) from exc
    if not isinstance(service_name, str) or not isinstance(environment, str):
        raise ValueError(
            f"managed component collision at {LOG_RESOURCE_PROCESSOR}: unknown values"
        )
    validated_scalar("prior rendered service name", service_name)
    validated_scalar("prior rendered deployment environment", environment)
    if component != log_resource_processor(service_name, environment):
        raise ValueError(
            f"managed component collision at {LOG_RESOURCE_PROCESSOR}: "
            "not an exact recognized prior render"
        )
    return service_name, environment


def recognize_journald_receiver(component: Any) -> str:
    """Return the prior unit only for our exact rendered shape."""

    try:
        unit = component["units"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(
            f"managed component collision at {JOURNALD_RECEIVER}: unknown shape"
        ) from exc
    if not isinstance(unit, str):
        raise ValueError(
            f"managed component collision at {JOURNALD_RECEIVER}: unknown values"
        )
    validated_scalar("prior rendered journald unit", unit)
    if component != journald_receiver(unit):
        raise ValueError(
            f"managed component collision at {JOURNALD_RECEIVER}: "
            "not an exact recognized prior render"
        )
    return unit


def remove_recognized_privacy_render(
    processors: dict[str, Any],
    pipelines: dict[str, Any],
    selected_pipeline_name: str,
) -> tuple[str, str] | None:
    present = PRIVACY_PROCESSOR in processors
    references = component_references(pipelines, PRIVACY_PROCESSOR)
    if not present:
        if references:
            raise ValueError(
                f"dangling managed reference to {PRIVACY_PROCESSOR} detected"
            )
        return None

    identity = recognize_privacy_processor(processors[PRIVACY_PROCESSOR])
    expected_reference = (selected_pipeline_name, "processors")
    actual_references = [(pipeline, field) for pipeline, field, _ in references]
    if actual_references != [expected_reference]:
        raise ValueError(
            f"managed reference collision for {PRIVACY_PROCESSOR}: expected "
            f"exactly one processor reference in selected pipeline "
            f"{selected_pipeline_name}"
        )
    pipeline_name, _, _ = references[0]
    pipeline = mapping(pipelines, pipeline_name)
    current = strings(pipeline, "processors")
    without_managed = [item for item in current if item != PRIVACY_PROCESSOR]
    expected = list(without_managed)
    insert_before_batch(expected, PRIVACY_PROCESSOR)
    if current != expected:
        raise ValueError(
            f"managed reference collision for {PRIVACY_PROCESSOR}: "
            "unrecognized processor ordering"
        )

    pipeline["processors"] = without_managed
    processors.pop(PRIVACY_PROCESSOR)
    return identity


def remove_recognized_journald_render(
    receivers: dict[str, Any],
    processors: dict[str, Any],
    pipelines: dict[str, Any],
    source_pipeline_name: str,
    privacy_identity: tuple[str, str] | None,
) -> None:
    receiver_present = JOURNALD_RECEIVER in receivers
    processor_present = LOG_RESOURCE_PROCESSOR in processors
    pipeline_present = JOURNALD_PIPELINE in pipelines
    receiver_references = component_references(pipelines, JOURNALD_RECEIVER)
    processor_references = component_references(pipelines, LOG_RESOURCE_PROCESSOR)
    any_managed_state = any(
        (
            receiver_present,
            processor_present,
            pipeline_present,
            bool(receiver_references),
            bool(processor_references),
        )
    )
    if not any_managed_state:
        return
    if not (receiver_present and processor_present and pipeline_present):
        raise ValueError(
            "partial or dangling managed journald render detected; refusing to "
            "overwrite or remove it"
        )
    if privacy_identity is None:
        raise ValueError(
            "managed journald render exists without its recognized privacy render"
        )

    recognize_journald_receiver(receivers[JOURNALD_RECEIVER])
    log_identity = recognize_log_resource_processor(processors[LOG_RESOURCE_PROCESSOR])
    if log_identity != privacy_identity:
        raise ValueError(
            "managed journald and privacy components have mismatched prior-render "
            "service or environment values"
        )

    if receiver_references != [(JOURNALD_PIPELINE, "receivers", 0)]:
        raise ValueError(
            f"managed reference collision for {JOURNALD_RECEIVER}: expected only "
            f"{JOURNALD_PIPELINE}"
        )
    expected_processors = journald_pipeline(mapping(pipelines, source_pipeline_name))[
        "processors"
    ]
    expected_processor_index = expected_processors.index(LOG_RESOURCE_PROCESSOR)
    if processor_references != [
        (JOURNALD_PIPELINE, "processors", expected_processor_index)
    ]:
        raise ValueError(
            f"managed reference collision for {LOG_RESOURCE_PROCESSOR}: expected "
            f"only {JOURNALD_PIPELINE}"
        )

    if pipelines[JOURNALD_PIPELINE] != journald_pipeline(
        mapping(pipelines, source_pipeline_name)
    ):
        raise ValueError(
            f"managed pipeline collision at {JOURNALD_PIPELINE}: "
            "not an exact recognized prior render"
        )

    pipelines.pop(JOURNALD_PIPELINE)
    receivers.pop(JOURNALD_RECEIVER)
    processors.pop(LOG_RESOURCE_PROCESSOR)


def migrate_legacy_renderer(
    document: dict[str, Any],
    enabled: bool,
    *,
    service_name: str,
    traces_pipeline_name: str,
    logs_pipeline_name: str,
) -> None:
    processors = mapping(document, "processors")
    pipelines = mapping(mapping(document, "service"), "pipelines")
    legacy_present = "resource/lemonade" in processors
    legacy_resource = processors.get("resource/lemonade")
    references = component_references(pipelines, "resource/lemonade")

    if not legacy_present and references:
        joined = ", ".join(
            sorted(
                f"{pipeline}.{field}[{index}]" for pipeline, field, index in references
            )
        )
        raise ValueError(f"dangling resource/lemonade reference detected at: {joined}")
    if legacy_present and not enabled:
        raise ValueError(
            "legacy shared resource/lemonade component detected; review and pass "
            "--migrate-legacy-lemonade-renderer"
        )

    if legacy_present:
        if not isinstance(legacy_resource, dict):
            raise ValueError("conflicting resource/lemonade component is not a mapping")
        if set(legacy_resource) != {"attributes"}:
            raise ValueError(
                "conflicting resource/lemonade component has an unknown shape"
            )
        attributes = legacy_resource.get("attributes")
        if (
            not isinstance(attributes, list)
            or len(attributes) != 3
            or not all(isinstance(item, dict) for item in attributes)
        ):
            raise ValueError(
                "conflicting resource/lemonade component has an unknown shape"
            )
        expected_keys = [
            "service.name",
            "deployment.environment.name",
            "deployment.environment",
        ]
        if any(set(item) != {"key", "value", "action"} for item in attributes):
            raise ValueError(
                "refusing to remove a non-legacy resource/lemonade component"
            )
        if [item.get("key") for item in attributes] != expected_keys or any(
            item.get("action") != "insert" for item in attributes
        ):
            raise ValueError(
                "refusing to remove a non-legacy resource/lemonade component"
            )
        values = [item.get("value") for item in attributes]
        if not all(isinstance(value, str) for value in values):
            raise ValueError(
                "refusing to remove a legacy component with non-string values"
            )
        for index, value in enumerate(values):
            validated_scalar(f"legacy {expected_keys[index]} value", value)
        if values[0] != service_name or values[1] != values[2]:
            raise ValueError(
                "refusing to remove a legacy component with unrecognized values"
            )
        if traces_pipeline_name == logs_pipeline_name:
            raise ValueError(
                "legacy resource/lemonade migration requires distinct selected "
                "trace and log pipelines"
            )
        selected_processor_lists = {
            pipeline_name: strings(mapping(pipelines, pipeline_name), "processors")
            for pipeline_name in (traces_pipeline_name, logs_pipeline_name)
        }
        expected_topology = sorted(
            (
                pipeline_name,
                "processors",
                len(selected_processor_lists[pipeline_name]) - 1,
            )
            for pipeline_name in (traces_pipeline_name, logs_pipeline_name)
        )
        actual_topology = sorted(references)
        if actual_topology != expected_topology:
            raise ValueError(
                "refusing legacy resource/lemonade migration: expected exactly "
                "one final processor reference in each selected trace and log "
                "pipeline"
            )
        processors.pop("resource/lemonade")

    if not legacy_present:
        return
    for pipeline_name in (traces_pipeline_name, logs_pipeline_name):
        pipeline = mapping(pipelines, pipeline_name)
        pipeline["processors"] = [
            item for item in pipeline["processors"] if item != "resource/lemonade"
        ]


def atomic_yaml(path: Path, document: dict[str, Any]) -> None:
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            yaml.safe_dump(document, handle, sort_keys=False, default_flow_style=False)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def render(args: argparse.Namespace) -> None:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise ValueError(
            "PyYAML is required; on Debian install python3-yaml or install "
            "the repository's requirements-dev.txt in an isolated environment"
        ) from exc
    try:
        document = yaml.safe_load(args.base.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid collector YAML: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError("collector config root must be a mapping")
    validate_secret_placeholders(document)

    for option, value in (
        ("--deployment-environment", args.deployment_environment),
        ("--service-name", args.service_name),
        ("--unit", args.unit),
        ("--traces-pipeline", args.traces_pipeline),
        ("--logs-pipeline", args.logs_pipeline),
    ):
        validated_scalar(option, value)
    if args.traces_pipeline == JOURNALD_PIPELINE:
        raise ValueError(
            f"--traces-pipeline reserves the managed pipeline ID {JOURNALD_PIPELINE}"
        )
    if args.logs_pipeline == JOURNALD_PIPELINE:
        raise ValueError(
            f"--logs-pipeline reserves the managed pipeline ID {JOURNALD_PIPELINE}"
        )
    if component_type(args.traces_pipeline) != "traces":
        raise ValueError("--traces-pipeline must identify a traces[/name] pipeline")
    if component_type(args.logs_pipeline) != "logs":
        raise ValueError("--logs-pipeline must identify a logs[/name] pipeline")

    migrate_legacy_renderer(
        document,
        args.migrate_legacy_lemonade_renderer,
        service_name=args.service_name,
        traces_pipeline_name=args.traces_pipeline,
        logs_pipeline_name=args.logs_pipeline,
    )

    receivers = mapping(document, "receivers")
    processors = mapping(document, "processors")
    mapping(document, "exporters")
    pipelines = mapping(mapping(document, "service"), "pipelines")
    traces = mapping(pipelines, args.traces_pipeline)

    prior_privacy_identity = remove_recognized_privacy_render(
        processors, pipelines, args.traces_pipeline
    )
    remove_recognized_journald_render(
        receivers,
        processors,
        pipelines,
        args.logs_pipeline,
        prior_privacy_identity,
    )

    processors[PRIVACY_PROCESSOR] = privacy_processor(
        args.service_name, args.deployment_environment
    )
    insert_before_batch(strings(traces, "processors"), PRIVACY_PROCESSOR)

    if args.enable_journald:
        logs = mapping(pipelines, args.logs_pipeline)
        receivers[JOURNALD_RECEIVER] = journald_receiver(args.unit)
        processors[LOG_RESOURCE_PROCESSOR] = log_resource_processor(
            args.service_name, args.deployment_environment
        )
        pipelines[JOURNALD_PIPELINE] = journald_pipeline(logs)

    validate_secret_placeholders(document)
    atomic_yaml(args.output, document)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "The default action is render-only: it writes a staged file and never "
            "replaces the base. PyYAML is required; on Debian install python3-yaml."
        ),
    )
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--deployment-environment", required=True)
    parser.add_argument("--service-name", default="lemonade-server")
    parser.add_argument("--unit", default="lemond.service")
    parser.add_argument("--traces-pipeline", default="traces")
    parser.add_argument("--logs-pipeline", default="logs")
    parser.add_argument("--enable-journald", action="store_true")
    parser.add_argument("--migrate-legacy-lemonade-renderer", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.base.is_file():
        raise SystemExit(f"ERROR: base collector config not found: {args.base}")
    if args.base.resolve() == args.output.resolve():
        raise SystemExit(
            "ERROR: --output must be a staging path, not the live base config"
        )
    try:
        render(args)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    print(f"Rendered staged collector config: {args.output}")


if __name__ == "__main__":
    main()
