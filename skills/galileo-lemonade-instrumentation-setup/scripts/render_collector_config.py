#!/usr/bin/env python3
"""Render-only setup for safe Galileo routing in a full Lemonade collector config."""

from __future__ import annotations

import argparse
import copy
import ipaddress
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


GALILEO_EXPORTER = "otlp_http/galileo_lemonade"
LEGACY_GALILEO_EXPORTER = "otlphttp/galileo_lemonade"
CLIENT_RECEIVER = "otlp/lemonade_galileo_client"
CLIENT_PIPELINE = "traces/lemonade_galileo_client"
CLIENT_RESOURCE = "resource/lemonade_galileo_client"
CLIENT_SEMANTICS = "transform/lemonade_client_semantics"
CLIENT_PRIVACY = "transform/lemonade_client_error_privacy"
ROUTE_GUARD = "transform/lemonade_galileo_route_guard"
SERVER_PIPELINE = "traces/lemonade_galileo_server"
SERVER_FILTER = "filter/lemonade_galileo_server"
ERROR_PRIVACY = "transform/lemonade_error_privacy"
GALILEO_STORAGE = "file_storage/galileo_lemonade"
DEFAULT_GALILEO_PROXY_URL = "http://127.0.0.1:18888"
MANAGED_PIPELINES = {CLIENT_PIPELINE, SERVER_PIPELINE}
MANAGED_PROCESSORS = {
    CLIENT_RESOURCE,
    CLIENT_SEMANTICS,
    CLIENT_PRIVACY,
    ROUTE_GUARD,
    SERVER_FILTER,
    ERROR_PRIVACY,
}
SAFE_CLIENT_PROCESSOR_TYPES = {
    "batch",
    "memory_limiter",
    "resource_detection",
    "resourcedetection",
}

# Defense-in-depth for openinference-semantic-conventions==0.1.30. Keep
# non-content routing/evaluation semantics (roles, names, IDs, content types,
# models, and providers), but remove values that can contain prompts,
# completions, images, reasoning payloads, tool arguments, or tool results.
CLIENT_CONTENT_ATTRIBUTE_PATTERN = (
    r"^(input[.]value|output[.]value|llm[.]invocation_parameters|"
    r"llm[.]function_call([.].*)?|"
    r"llm[.]tools([.].*)?|"
    r"llm[.]prompts[.][0-9]+[.]prompt[.]text|"
    r"llm[.]choices[.][0-9]+[.]completion[.]text|"
    r"llm[.]prompt_template[.](template|variables)([.].*)?|"
    r"llm[.](input|output)_messages[.][0-9]+[.]message[.]content|"
    r"llm[.](input|output)_messages[.][0-9]+[.]message[.]contents[.]"
    r"[0-9]+[.]message_content[.](text|data|encrypted_content|signature)|"
    r"llm[.](input|output)_messages[.][0-9]+[.]message[.]contents[.]"
    r"[0-9]+[.]message_content[.]image([.].*)?|"
    r"llm[.](input|output)_messages[.][0-9]+[.]message[.]contents[.]"
    r"[0-9]+[.]message_content[.]audio([.].*)?|"
    r"llm[.](input|output)_messages[.][0-9]+[.]message[.]"
    r"function_call_arguments_json|"
    r"llm[.](input|output)_messages[.][0-9]+[.]message[.]tool_calls[.]"
    r"[0-9]+[.]tool_call[.](function[.]arguments|reasoning_signature)|"
    r"gen_ai[.](prompt|completion)|"
    r"gen_ai[.](input|output)[.]messages($|[.][0-9]+[.]"
    r"(content|contents|parts)([.].*)?)|"
    r"gen_ai[.]system_instructions([.].*)?|"
    r"gen_ai[.]tool[.]definitions([.].*)?|"
    r"gen_ai[.]tool[.](description|parameters|arguments)([.].*)?|"
    r"gen_ai[.]tool[.]call[.](arguments|result)([.].*)?|"
    r"gen_ai[.]retrieval[.](documents|query([.]text)?)([.].*)?|"
    r"gen_ai[.](system|user|assistant|tool)[.]message([.].*)?|"
    r"embedding[.]invocation_parameters|"
    r"embedding[.]embeddings[.][0-9]+[.]embedding[.](text|vector)|"
    r"(audio[.](url|transcript|data)|image[.]url|prompt[.]url)|"
    r"tool[.](description|parameters|output|json_schema|schema)|"
    r"retrieval[.]documents[.][0-9]+[.]document[.](content|metadata)|"
    r"reranker[.]query|reranker[.](input|output)_documents[.][0-9]+[.]"
    r"document[.](content|metadata)|metadata|user[.]id|tag[.]tags)$"
)
CLIENT_EVENT_CONTENT_ATTRIBUTE_PATTERN = (
    r"(?i)^(gen_ai[.](input|output)[.]messages($|[.][0-9]+[.]"
    r"(content|contents|parts)([.].*)?)|gen_ai[.]system_instructions([.].*)?|"
    r"gen_ai[.]tool[.]definitions([.].*)?|"
    r"gen_ai[.].*(content|arguments|result|prompt|completion|description)"
    r"([.].*)?|gen_ai[.]retrieval[.](documents|query([.]text)?)([.].*)?|"
    r"llm[.].*(content|arguments|result)([.].*)?|"
    r"tool[.](arguments|result|output|description|parameters)([.].*)?|"
    r"(audio[.](url|transcript|data)|image[.]url|prompt[.]url))$"
)
GALILEO_ROUTE_ATTRIBUTE_PATTERN = r"(?i)^galileo[.]"
DESTINATION_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


def safe_text(value: str, option: str) -> str:
    if (
        not value
        or value != value.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(
            f"{option} must be a non-empty, trimmed string without control characters"
        )
    return value


def valid_network_host(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        labels = host.rstrip(".").split(".")
        return bool(labels) and all(
            label
            and len(label) <= 63
            and label[0].isascii()
            and label[0].isalnum()
            and label[-1].isascii()
            and label[-1].isalnum()
            and all(
                character.isascii() and (character.isalnum() or character == "-")
                for character in label
            )
            for label in labels
        )


def validate_galileo_proxy_url(value: str) -> str:
    """Require one explicit, credential-free IPv4 loopback HTTP proxy URL."""

    if not value or value != value.strip() or "\\" in value:
        raise ValueError("--galileo-proxy-url must be an explicit loopback HTTP URL")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("--galileo-proxy-url contains an invalid port") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.netloc != f"127.0.0.1:{port}"
        or not 1 <= port <= 65535
    ):
        raise ValueError("--galileo-proxy-url must be canonical http://127.0.0.1:PORT")
    return value


def resolve_console_url(value: str) -> dict[str, str]:
    """Map a safe console navigation URL to its origin and API candidate."""
    raw = value.strip()
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("--galileo-console-url must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError("--galileo-console-url must not contain credentials")
    if not valid_network_host(parsed.hostname):
        raise ValueError("--galileo-console-url contains an invalid hostname")
    if parsed.query or parsed.fragment or ";" in parsed.path:
        raise ValueError(
            "--galileo-console-url must not contain parameters, a query, or a fragment"
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in raw):
        raise ValueError("--galileo-console-url contains control characters")
    if "\\" in raw:
        raise ValueError("--galileo-console-url must not contain backslashes")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("--galileo-console-url contains an invalid port") from exc

    host = parsed.hostname.lower()
    if parsed.scheme == "http":
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host == "localhost" or host.endswith(".localhost")
        if not loopback:
            raise ValueError(
                "--galileo-console-url must use HTTPS outside loopback testing"
            )

    if host == "app.galileo.ai":
        api_host = "api.galileo.ai"
    elif host.startswith("console."):
        api_host = "api." + host[len("console.") :]
    elif host.startswith("console-"):
        api_host = "api-" + host[len("console-") :]
    elif host.startswith("api.") or host.startswith("api-"):
        api_host = host
    else:
        raise ValueError(
            "cannot derive the Galileo API host; obtain the tenant API base explicitly"
        )

    console_netloc = host + (f":{port}" if port is not None else "")
    api_netloc = api_host + (f":{port}" if port is not None else "")
    console_origin = urlunsplit((parsed.scheme, console_netloc, "/", "", ""))
    api_base = urlunsplit((parsed.scheme, api_netloc, "", "", ""))
    return {
        "console_origin": console_origin,
        "console_route": parsed.path or "/",
        "api_base_candidate": api_base,
        "otlp_traces_candidate": api_base + "/otel/traces",
    }


def mapping(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"expected mapping at {key}")
    return value


def string_list(parent: dict[str, Any], key: str) -> list[str]:
    value = parent.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"expected string list at {key}")
    return value


def append_unique(values: list[str], item: str) -> None:
    if item not in values:
        values.append(item)


def processor_type(name: str) -> str:
    return name.split("/", 1)[0]


def insert_before_batch(processors: list[str], component: str) -> None:
    processors[:] = [item for item in processors if item != component]
    for index, name in enumerate(processors):
        if processor_type(name) == "batch":
            processors.insert(index, component)
            return
    processors.append(component)


def terminal_batch_split(
    processors: list[str], *, label: str
) -> tuple[list[str], list[str]]:
    """Split a pipeline at its terminal batch suffix or fail closed.

    Privacy and routing guards cannot be meaningful if another processor can
    mutate a span after them.  A batch processor therefore starts a terminal
    suffix: every remaining processor must also be a batch component.
    """

    first_batch = next(
        (
            index
            for index, component in enumerate(processors)
            if processor_type(component) == "batch"
        ),
        len(processors),
    )
    non_batch = list(processors[:first_batch])
    batch_suffix = list(processors[first_batch:])
    if any(processor_type(component) != "batch" for component in batch_suffix):
        raise ValueError(
            f"{label} must not contain a non-batch processor after its first batch"
        )
    return non_batch, batch_suffix


def guarded_processor_order(
    processors: list[str],
    *,
    prefix: tuple[str, ...],
    privacy: str,
    label: str,
) -> list[str]:
    """Place privacy and route guards as the final non-batch processors."""

    managed = {*prefix, privacy, ROUTE_GUARD}
    without_managed = [
        component for component in processors if component not in managed
    ]
    non_batch, batch_suffix = terminal_batch_split(without_managed, label=label)
    return [*non_batch, *prefix, privacy, ROUTE_GUARD, *batch_suffix]


def loopback_endpoint(value: str) -> bool:
    try:
        host, port = value.rsplit(":", 1)
        if not 1 <= int(port) <= 65535:
            return False
        host = host.strip("[]")
        return host == "localhost" or ipaddress.ip_address(host).is_loopback
    except (ValueError, TypeError):
        return False


def validated_destination_fingerprint(value: str) -> str:
    if not DESTINATION_FINGERPRINT.fullmatch(value):
        raise ValueError("--destination-fingerprint must be a lowercase SHA-256 digest")
    return value


def fingerprinted_queue_directory(directory: Path, fingerprint: str) -> bool:
    """Require a dedicated final path component for one Galileo destination."""

    return directory.name == fingerprint


def client_resource_processor(service_name: str) -> dict[str, Any]:
    return {
        "attributes": [
            {"key": "service.name", "value": service_name, "action": "upsert"},
            {
                "key": "telemetry.source",
                "value": "lemonade-client",
                "action": "upsert",
            },
        ]
    }


def remove_managed_components(
    document: dict[str, Any],
    native_pipeline_name: str,
    native_receivers: list[str],
    native_processors: list[str],
    native_exporters: list[str],
    lemonade_service_name: str,
    client_service_name: str,
    client_receiver_endpoint: str,
) -> None:
    receivers = mapping(document, "receivers")
    processors = mapping(document, "processors")
    exporters = mapping(document, "exporters")
    service = mapping(document, "service")
    pipelines = mapping(service, "pipelines")
    extensions_value = document.setdefault("extensions", {})
    if not isinstance(extensions_value, dict):
        raise ValueError("expected mapping at extensions")
    extensions = extensions_value

    managed_definitions = (
        CLIENT_RECEIVER in receivers
        or any(name in processors for name in MANAGED_PROCESSORS)
        or GALILEO_EXPORTER in exporters
        or LEGACY_GALILEO_EXPORTER in exporters
        or GALILEO_STORAGE in extensions
    )
    managed_pipeline_names = [name for name in MANAGED_PIPELINES if name in pipelines]
    if managed_pipeline_names and not managed_definitions:
        raise ValueError(
            "managed Galileo pipeline exists without its component definitions"
        )
    if managed_definitions and len(managed_pipeline_names) != 1:
        raise ValueError(
            "managed Galileo component collision or partial prior render detected; "
            "restore/review the prior full config before mode switching"
        )
    if managed_pipeline_names:
        prior_name = managed_pipeline_names[0]
        prior = mapping(pipelines, prior_name)
        if set(prior) != {"receivers", "processors", "exporters"}:
            raise ValueError("managed Galileo pipeline has unknown fields")
        prior_receivers = string_list(prior, "receivers")
        prior_processors = string_list(prior, "processors")
        prior_exporters = string_list(prior, "exporters")
        for label, values in (
            ("receivers", prior_receivers),
            ("processors", prior_processors),
            ("exporters", prior_exporters),
        ):
            if not values or len(values) != len(set(values)):
                raise ValueError(
                    f"managed Galileo pipeline {label} are empty or duplicated"
                )

        if native_processors.count(ERROR_PRIVACY) != 1:
            raise ValueError("managed native error privacy reference has drifted")
        baseline_native_processors = [
            item for item in native_processors if item != ERROR_PRIVACY
        ]
        expected_native_processors = list(baseline_native_processors)
        insert_before_batch(expected_native_processors, ERROR_PRIVACY)
        if native_processors != expected_native_processors or processors.get(
            ERROR_PRIVACY
        ) != error_privacy_processor(lemonade_service_name):
            raise ValueError("managed native error privacy config has drifted")

        if processors.get(ROUTE_GUARD) != galileo_route_guard_processor():
            raise ValueError("managed Galileo route guard has drifted")

        if prior_name == CLIENT_PIPELINE:
            expected_processors = [
                item
                for item in baseline_native_processors
                if processor_type(item) in SAFE_CLIENT_PROCESSOR_TYPES
            ]
            expected_processors = [
                item
                for item in expected_processors
                if item not in {"resource/lemonade", CLIENT_RESOURCE}
            ]
            expected_processors = guarded_processor_order(
                expected_processors,
                prefix=(CLIENT_RESOURCE, CLIENT_SEMANTICS),
                privacy=CLIENT_PRIVACY,
                label="managed Galileo client pipeline",
            )
            expected_exporters = [GALILEO_EXPORTER]
            mirrored_exporters = [*native_exporters, GALILEO_EXPORTER]
            if (
                prior_receivers != [CLIENT_RECEIVER]
                or prior_processors != expected_processors
                or prior_exporters not in (expected_exporters, mirrored_exporters)
                or receivers.get(CLIENT_RECEIVER)
                != {"protocols": {"http": {"endpoint": client_receiver_endpoint}}}
                or processors.get(CLIENT_RESOURCE)
                != client_resource_processor(client_service_name)
                or processors.get(CLIENT_SEMANTICS) != client_semantics_processor()
                or processors.get(CLIENT_PRIVACY) != client_error_privacy_processor()
                or any(name in processors for name in (SERVER_FILTER,))
            ):
                raise ValueError("managed Galileo client pipeline has an unknown shape")
        else:
            expected_processors = [
                item
                for item in baseline_native_processors
                if processor_type(item) in SAFE_CLIENT_PROCESSOR_TYPES
                or item == "transform/lemonade_resource_privacy"
            ]
            expected_processors = guarded_processor_order(
                expected_processors,
                prefix=(SERVER_FILTER,),
                privacy=ERROR_PRIVACY,
                label="managed Galileo server pipeline",
            )
            expected_condition = (
                'resource.attributes["service.name"] != '
                f"{json.dumps(lemonade_service_name)}"
            )
            if (
                prior_receivers != native_receivers
                or prior_processors != expected_processors
                or prior_exporters != [GALILEO_EXPORTER]
                or processors.get(SERVER_FILTER)
                != {
                    "error_mode": "propagate",
                    "trace_conditions": [expected_condition],
                }
                or any(
                    name in processors
                    for name in (CLIENT_RESOURCE, CLIENT_SEMANTICS, CLIENT_PRIVACY)
                )
                or CLIENT_RECEIVER in receivers
            ):
                raise ValueError("managed Galileo server pipeline has an unknown shape")

        owned_exporter = exporters.get(GALILEO_EXPORTER)
        recognized_exporter = False
        if isinstance(owned_exporter, dict):
            proxy_url = owned_exporter.get("proxy_url")
            if isinstance(proxy_url, str):
                try:
                    proxy_url = validate_galileo_proxy_url(proxy_url)
                except ValueError:
                    proxy_url = ""
            for routing in ("ids", "names"):
                for queue_policy in ("persistent", "memory"):
                    if proxy_url and owned_exporter == galileo_exporter(
                        routing, queue_policy, proxy_url
                    ):
                        recognized_exporter = True
                    legacy_exporter = galileo_exporter(routing, queue_policy)
                    legacy_exporter.pop("proxy_url")
                    if owned_exporter == legacy_exporter:
                        # Exact pre-hardening managed shape. It is accepted only
                        # as migration input and is replaced before output.
                        recognized_exporter = True
        if not recognized_exporter:
            raise ValueError("managed Galileo exporter has drifted")

        queue = owned_exporter.get("sending_queue", {})
        if queue.get("storage") == GALILEO_STORAGE:
            storage = extensions.get(GALILEO_STORAGE)
            directory = storage.get("directory") if isinstance(storage, dict) else None
            if not isinstance(directory, str) or storage != galileo_storage(directory):
                raise ValueError("managed Galileo queue storage has drifted")
            service_extensions = service.get("extensions") or []
            if (
                not isinstance(service_extensions, list)
                or service_extensions.count(GALILEO_STORAGE) != 1
            ):
                raise ValueError("managed Galileo queue extension has drifted")
        elif GALILEO_STORAGE in extensions:
            raise ValueError("managed Galileo memory queue has unexpected storage")

        for pipeline_name, pipeline in pipelines.items():
            if pipeline_name in MANAGED_PIPELINES or not isinstance(pipeline, dict):
                continue
            processor_refs = pipeline.get("processors") or []
            forbidden = set(MANAGED_PROCESSORS) - {ERROR_PRIVACY}
            if set(processor_refs).intersection(forbidden):
                raise ValueError(
                    "managed Galileo processors are referenced by another pipeline"
                )
            if (
                ERROR_PRIVACY in processor_refs
                and pipeline_name != native_pipeline_name
            ):
                raise ValueError(
                    "managed Galileo error privacy is referenced by another pipeline"
                )
            if CLIENT_RECEIVER in (pipeline.get("receivers") or []):
                raise ValueError(
                    "managed Galileo receiver is referenced by another pipeline"
                )
            if any(
                item in {GALILEO_EXPORTER, LEGACY_GALILEO_EXPORTER}
                for item in (pipeline.get("exporters") or [])
            ):
                raise ValueError(
                    "managed Galileo exporter is referenced by another pipeline"
                )
        for exporter_name, exporter_config in exporters.items():
            if exporter_name == GALILEO_EXPORTER:
                continue
            if GALILEO_STORAGE in json.dumps(exporter_config, sort_keys=True):
                raise ValueError(
                    "managed Galileo storage is referenced by another exporter"
                )

    pipelines.pop(CLIENT_PIPELINE, None)
    pipelines.pop(SERVER_PIPELINE, None)
    receivers.pop(CLIENT_RECEIVER, None)
    processors.pop(CLIENT_RESOURCE, None)
    processors.pop(CLIENT_SEMANTICS, None)
    processors.pop(CLIENT_PRIVACY, None)
    processors.pop(SERVER_FILTER, None)
    processors.pop(ERROR_PRIVACY, None)
    processors.pop(ROUTE_GUARD, None)
    extensions.pop(GALILEO_STORAGE, None)
    if isinstance(service.get("extensions"), list):
        service["extensions"] = [
            item for item in service["extensions"] if item != GALILEO_STORAGE
        ]
    # Remove only components owned by this skill. A generic otlp_http/galileo
    # exporter may serve another application pipeline and must be preserved.
    exporters.pop(GALILEO_EXPORTER, None)
    exporters.pop(LEGACY_GALILEO_EXPORTER, None)
    for pipeline in pipelines.values():
        if not isinstance(pipeline, dict):
            continue
        if isinstance(pipeline.get("exporters"), list):
            pipeline["exporters"] = [
                item
                for item in pipeline["exporters"]
                if item not in {GALILEO_EXPORTER, LEGACY_GALILEO_EXPORTER}
            ]
        if isinstance(pipeline.get("processors"), list):
            pipeline["processors"] = [
                item
                for item in pipeline["processors"]
                if item
                not in {
                    CLIENT_SEMANTICS,
                    CLIENT_PRIVACY,
                    SERVER_FILTER,
                    ERROR_PRIVACY,
                    ROUTE_GUARD,
                }
            ]


def galileo_exporter(
    routing: str,
    queue_policy: str,
    proxy_url: str = DEFAULT_GALILEO_PROXY_URL,
) -> dict[str, Any]:
    proxy_url = validate_galileo_proxy_url(proxy_url)
    selector_headers = (
        {
            "projectid": "${env:GALILEO_PROJECT_ID}",
            "logstreamid": "${env:GALILEO_LOG_STREAM_ID}",
        }
        if routing == "ids"
        else {
            "project": "${env:GALILEO_PROJECT}",
            "logstream": "${env:GALILEO_LOG_STREAM}",
        }
    )
    queue: dict[str, Any] = {
        "enabled": True,
        "num_consumers": 10,
        "queue_size": 1000,
        "block_on_overflow": False,
        "sizer": "requests",
    }
    if queue_policy == "persistent":
        queue = {
            "enabled": True,
            "num_consumers": 4,
            "queue_size": 268_435_456,
            "block_on_overflow": False,
            "sizer": "bytes",
            "storage": GALILEO_STORAGE,
        }
    elif queue_policy != "memory":
        raise ValueError("--queue-policy must be memory or persistent")
    return {
        "traces_endpoint": "${env:GALILEO_OTLP_TRACES_ENDPOINT}",
        # Collector v0.156 confighttp.ClientConfig exposes proxy_url at this
        # exporter level. Keep it literal so only this Galileo exporter uses it.
        "proxy_url": proxy_url,
        "headers": {
            "Galileo-API-Key": "${env:GALILEO_API_KEY}",
            **selector_headers,
        },
        "compression": "gzip",
        "timeout": "30s",
        "retry_on_failure": {
            "enabled": True,
            "initial_interval": "5s",
            "max_interval": "30s",
            "max_elapsed_time": "30m",
        },
        "sending_queue": queue,
    }


def galileo_storage(directory: str) -> dict[str, Any]:
    compaction_directory = str(Path(directory) / "compaction")
    return {
        "directory": directory,
        "timeout": "10s",
        "max_size": 1_073_741_824,
        "fsync": True,
        "create_directory": True,
        "directory_permissions": "0700",
        "compaction": {
            "on_rebound": True,
            "directory": compaction_directory,
            "rebound_needed_threshold_mib": 256,
            "rebound_trigger_threshold_mib": 64,
            "check_interval": "5m",
        },
    }


def looks_like_galileo_exporter(config: Any) -> bool:
    if not isinstance(config, dict):
        return False
    headers = config.get("headers")
    header_names = (
        {str(name).lower() for name in headers} if isinstance(headers, dict) else set()
    )
    if {
        "galileo-api-key",
        "projectid",
        "logstreamid",
        "project",
        "logstream",
    } & header_names:
        return True
    endpoints = [config.get("traces_endpoint"), config.get("endpoint")]
    return any(
        isinstance(value, str)
        and ("galileo" in value.lower() or "${env:galileo_" in value.lower())
        for value in endpoints
    )


def is_galileo_exporter(name: str, config: Any) -> bool:
    return "galileo" in name.casefold() or looks_like_galileo_exporter(config)


def conflicting_galileo_artifacts(document: dict[str, Any]) -> list[str]:
    """Find every non-managed Galileo exporter/route or receiver reuse."""

    exporters = mapping(document, "exporters")
    pipelines = mapping(mapping(document, "service"), "pipelines")
    candidate_exporters = {
        name
        for name, config in exporters.items()
        if name not in {GALILEO_EXPORTER, LEGACY_GALILEO_EXPORTER}
        and is_galileo_exporter(name, config)
    }
    conflicts = [f"exporter:{name}" for name in sorted(candidate_exporters)]
    for name, pipeline in pipelines.items():
        if name in MANAGED_PIPELINES or not isinstance(pipeline, dict):
            continue
        pipeline_exporters = pipeline.get("exporters")
        pipeline_receivers = pipeline.get("receivers")
        exporter_conflict = isinstance(pipeline_exporters, list) and any(
            isinstance(item, str)
            and (
                item in candidate_exporters
                or item in {GALILEO_EXPORTER, LEGACY_GALILEO_EXPORTER}
                or "galileo" in item.casefold()
            )
            for item in pipeline_exporters
        )
        receiver_conflict = (
            isinstance(pipeline_receivers, list)
            and CLIENT_RECEIVER in pipeline_receivers
        )
        if exporter_conflict or receiver_conflict:
            conflicts.append(f"pipeline:{name}")
    return sorted(set(conflicts))


def existing_galileo_routes(
    document: dict[str, Any], native_receivers: list[str] | None = None
) -> list[str]:
    """Backward-compatible alias for strict whole-config conflict discovery."""

    del native_receivers
    return conflicting_galileo_artifacts(document)


def error_privacy_processor(server_service: str) -> dict[str, Any]:
    services = [server_service]
    span_statements: list[str] = []
    event_statements: list[str] = []
    for service in services:
        literal = json.dumps(service)
        condition = f'resource.attributes["service.name"] == {literal}'
        span_statements.extend(
            [
                (
                    'set(span.status.message, "[REDACTED]") where span.status.code == '
                    f"STATUS_CODE_ERROR and {condition}"
                ),
                (
                    'set(span.attributes["error.type"], "lemonade.error") where '
                    "span.status.code == STATUS_CODE_ERROR and "
                    f'span.attributes["error.type"] == nil and {condition}'
                ),
            ]
        )
        event_statements.extend(
            [
                (
                    'set(spanevent.attributes["exception.message"], "[REDACTED]") where '
                    f'spanevent.name == "exception" and {condition}'
                ),
                (
                    'set(spanevent.attributes["exception.stacktrace"], "[REDACTED]") where '
                    'spanevent.name == "exception" and '
                    'spanevent.attributes["exception.stacktrace"] != nil '
                    f"and {condition}"
                ),
            ]
        )
    return {
        "error_mode": "propagate",
        "trace_statements": [
            {"context": "span", "statements": span_statements},
            {"context": "spanevent", "statements": event_statements},
        ],
    }


def client_error_privacy_processor() -> dict[str, Any]:
    agent_or_tool = (
        'span.attributes["openinference.span.kind"] == "AGENT" or '
        'span.attributes["openinference.span.kind"] == "TOOL"'
    )
    tool = 'span.attributes["openinference.span.kind"] == "TOOL"'
    return {
        "error_mode": "propagate",
        "trace_statements": [
            {
                "context": "resource",
                "statements": [
                    "delete_matching_keys(resource.attributes, "
                    f'"{CLIENT_CONTENT_ATTRIBUTE_PATTERN}")'
                ],
            },
            {
                "context": "span",
                "statements": [
                    "delete_matching_keys(span.attributes, "
                    f'"{CLIENT_CONTENT_ATTRIBUTE_PATTERN}")',
                    (
                        'set(span.attributes["input.value"], "[REDACTED]") where '
                        f"{agent_or_tool}"
                    ),
                    (
                        'set(span.attributes["output.value"], "[REDACTED]") where '
                        f"{agent_or_tool}"
                    ),
                    (
                        'set(span.attributes["gen_ai.tool.call.arguments"], '
                        f'"[REDACTED]") where {tool}'
                    ),
                    (
                        'set(span.attributes["gen_ai.tool.call.result"], '
                        f'"[REDACTED]") where {tool}'
                    ),
                    'set(span.status.message, "[REDACTED]") where '
                    "span.status.code == STATUS_CODE_ERROR",
                    (
                        'set(span.attributes["error.type"], "lemonade.error") where '
                        "span.status.code == STATUS_CODE_ERROR and "
                        'span.attributes["error.type"] == nil'
                    ),
                ],
            },
            {
                "context": "spanevent",
                "statements": [
                    (
                        "delete_matching_keys(spanevent.attributes, "
                        f'"{CLIENT_EVENT_CONTENT_ATTRIBUTE_PATTERN}")'
                    ),
                    (
                        'set(spanevent.attributes["exception.message"], "[REDACTED]") where '
                        'spanevent.name == "exception"'
                    ),
                    (
                        'set(spanevent.attributes["exception.stacktrace"], "[REDACTED]") '
                        'where spanevent.name == "exception" and '
                        'spanevent.attributes["exception.stacktrace"] != nil'
                    ),
                ],
            },
        ],
    }


def galileo_route_guard_processor() -> dict[str, Any]:
    """Delete every in-band Galileo route/dataset override before export."""

    return {
        "error_mode": "propagate",
        "trace_statements": [
            {
                "context": "resource",
                "statements": [
                    "delete_matching_keys(resource.attributes, "
                    f'"{GALILEO_ROUTE_ATTRIBUTE_PATTERN}")'
                ],
            },
            {
                "context": "span",
                "statements": [
                    "delete_matching_keys(span.attributes, "
                    f'"{GALILEO_ROUTE_ATTRIBUTE_PATTERN}")'
                ],
            },
            {
                "context": "spanevent",
                "statements": [
                    "delete_matching_keys(spanevent.attributes, "
                    f'"{GALILEO_ROUTE_ATTRIBUTE_PATTERN}")'
                ],
            },
        ],
    }


def client_semantics_processor() -> dict[str, Any]:
    llm = 'span.attributes["openinference.span.kind"] == "LLM"'
    return {
        "error_mode": "propagate",
        "trace_statements": [
            {
                "context": "span",
                "statements": [
                    f'set(span.attributes["llm.provider"], "lemonade") where {llm}',
                    f'set(span.attributes["gen_ai.provider.name"], "lemonade") where {llm}',
                    (
                        'set(span.attributes["gen_ai.operation.name"], "chat") where '
                        f'{llm} and span.attributes["gen_ai.operation.name"] == nil'
                    ),
                    (
                        'set(span.attributes["gen_ai.request.model"], '
                        'span.attributes["llm.model_name"]) where '
                        f'{llm} and span.attributes["gen_ai.request.model"] == nil and '
                        'span.attributes["llm.model_name"] != nil'
                    ),
                    (
                        'set(span.attributes["gen_ai.response.model"], '
                        'span.attributes["llm.model_name"]) where '
                        f'{llm} and span.attributes["gen_ai.response.model"] == nil and '
                        'span.attributes["llm.model_name"] != nil'
                    ),
                    (
                        'set(span.attributes["llm.input_messages.0.message.role"], "user") '
                        f"where {llm} and "
                        'span.attributes["llm.input_messages.0.message.role"] == nil'
                    ),
                    (
                        'set(span.attributes["llm.output_messages.0.message.role"], "assistant") '
                        f"where {llm} and "
                        'span.attributes["llm.output_messages.0.message.role"] == nil'
                    ),
                ],
            }
        ],
    }


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
            "PyYAML is required; install requirements-dev.txt in an isolated environment"
        ) from exc
    try:
        document = yaml.safe_load(args.base.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid collector YAML: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError("collector config root must be a mapping")

    for option, value in (
        ("--native-traces-pipeline", args.native_traces_pipeline),
        ("--lemonade-service-name", args.lemonade_service_name),
        ("--client-service-name", args.client_service_name),
    ):
        safe_text(value, option)
    for value in args.client_processor:
        safe_text(value, "--client-processor")
    if not args.queue_storage_directory.is_absolute():
        raise ValueError("--queue-storage-directory must be an absolute path")
    safe_text(str(args.queue_storage_directory), "--queue-storage-directory")
    destination_fingerprint = ""
    galileo_proxy_url = validate_galileo_proxy_url(args.galileo_proxy_url)
    if args.destination_fingerprint:
        destination_fingerprint = validated_destination_fingerprint(
            args.destination_fingerprint
        )
    if args.production and args.mode != "splunk-only":
        if args.queue_policy != "persistent":
            raise ValueError("--production requires --queue-policy persistent")
        if not destination_fingerprint:
            raise ValueError("--production requires --destination-fingerprint")
        if not fingerprinted_queue_directory(
            args.queue_storage_directory, destination_fingerprint
        ):
            raise ValueError(
                "production queue directory must end with the destination fingerprint"
            )

    receivers = mapping(document, "receivers")
    processors = mapping(document, "processors")
    exporters = mapping(document, "exporters")
    pipelines = mapping(mapping(document, "service"), "pipelines")
    native = mapping(pipelines, args.native_traces_pipeline)
    native_receivers = copy.deepcopy(string_list(native, "receivers"))
    native_processors = copy.deepcopy(string_list(native, "processors"))
    native_exporters = copy.deepcopy(string_list(native, "exporters"))
    for label, values in (
        ("native receivers", native_receivers),
        ("native processors", native_processors),
        ("native exporters", native_exporters),
    ):
        if not values or len(values) != len(set(values)):
            raise ValueError(f"{label} must be non-empty and contain no duplicates")

    duplicate_routes = conflicting_galileo_artifacts(document)
    if duplicate_routes:
        raise ValueError(
            "another Galileo-like exporter/route or dedicated receiver reference exists; "
            "remove it before rendering any mode: "
            + ", ".join(sorted(duplicate_routes))
        )

    remove_managed_components(
        document,
        args.native_traces_pipeline,
        native_receivers,
        native_processors,
        native_exporters,
        args.lemonade_service_name,
        args.client_service_name,
        args.client_receiver_endpoint,
    )
    native = mapping(pipelines, args.native_traces_pipeline)
    native["exporters"] = [
        item
        for item in native_exporters
        if item not in {GALILEO_EXPORTER, LEGACY_GALILEO_EXPORTER}
    ]

    if args.mode == "splunk-only":
        atomic_yaml(args.output, document)
        return

    exporters[GALILEO_EXPORTER] = galileo_exporter(
        args.routing, args.queue_policy, galileo_proxy_url
    )
    if args.queue_policy == "persistent":
        extensions_value = document.setdefault("extensions", {})
        if not isinstance(extensions_value, dict):
            raise ValueError("expected mapping at extensions")
        extensions_value[GALILEO_STORAGE] = galileo_storage(
            str(args.queue_storage_directory)
        )
        service = mapping(document, "service")
        service_extensions = service.setdefault("extensions", [])
        if not isinstance(service_extensions, list) or not all(
            isinstance(item, str) for item in service_extensions
        ):
            raise ValueError("expected string list at service.extensions")
        append_unique(service_extensions, GALILEO_STORAGE)
    processors[ERROR_PRIVACY] = error_privacy_processor(args.lemonade_service_name)
    processors[ROUTE_GUARD] = galileo_route_guard_processor()
    insert_before_batch(string_list(native, "processors"), ERROR_PRIVACY)
    if args.mode == "server-fanout":
        service_literal = json.dumps(args.lemonade_service_name)
        processors[SERVER_FILTER] = {
            "error_mode": "propagate",
            "trace_conditions": [
                f'resource.attributes["service.name"] != {service_literal}'
            ],
        }
        server_processors = [
            item
            for item in native_processors
            if processor_type(item) in SAFE_CLIENT_PROCESSOR_TYPES
            or item == "transform/lemonade_resource_privacy"
        ]
        server_processors = guarded_processor_order(
            server_processors,
            prefix=(SERVER_FILTER,),
            privacy=ERROR_PRIVACY,
            label="server Galileo pipeline",
        )
        pipelines[SERVER_PIPELINE] = {
            "receivers": native_receivers,
            "processors": server_processors,
            "exporters": [GALILEO_EXPORTER],
        }
    elif args.mode == "client-fanout":
        if not loopback_endpoint(args.client_receiver_endpoint):
            raise ValueError("--client-receiver-endpoint must be a loopback host:port")
        receivers[CLIENT_RECEIVER] = {
            "protocols": {"http": {"endpoint": args.client_receiver_endpoint}}
        }
        processors[CLIENT_RESOURCE] = client_resource_processor(
            args.client_service_name
        )
        processors[CLIENT_SEMANTICS] = client_semantics_processor()
        processors[CLIENT_PRIVACY] = client_error_privacy_processor()
        if args.client_processor:
            missing = [item for item in args.client_processor if item not in processors]
            if missing:
                raise ValueError(
                    "--client-processor references undefined component(s): "
                    + ", ".join(missing)
                )
            client_processors = list(dict.fromkeys(args.client_processor))
        else:
            client_processors = [
                item
                for item in native_processors
                if processor_type(item) in SAFE_CLIENT_PROCESSOR_TYPES
            ]
        client_processors = [
            item
            for item in client_processors
            if item not in {"resource/lemonade", CLIENT_RESOURCE}
        ]
        client_processors = guarded_processor_order(
            client_processors,
            prefix=(CLIENT_RESOURCE, CLIENT_SEMANTICS),
            privacy=CLIENT_PRIVACY,
            label="client Galileo pipeline",
        )
        client_exporters = (
            list(native["exporters"]) if args.mirror_client_to_native_exporters else []
        )
        append_unique(client_exporters, GALILEO_EXPORTER)
        pipelines[CLIENT_PIPELINE] = {
            "receivers": [CLIENT_RECEIVER],
            "processors": client_processors,
            "exporters": client_exporters,
        }
    else:  # argparse constrains values; retained for direct function callers.
        raise ValueError(f"unsupported mode: {args.mode}")

    atomic_yaml(args.output, document)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Prerequisite: PyYAML from requirements-dev.txt. This command renders only; "
            "review the staged diff, then run scripts/validate.sh --production with the "
            "installed collector binary before any transactional apply."
        ),
    )
    parser.add_argument(
        "--galileo-console-url",
        default="",
        help=(
            "Validate the exact console/navigation URL and report its safe origin/API "
            "candidate; runtime endpoint and selectors remain environment-provided"
        ),
    )
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=("server-fanout", "client-fanout", "splunk-only"),
        required=True,
    )
    parser.add_argument("--routing", choices=("ids", "names"), default="ids")
    parser.add_argument(
        "--queue-policy",
        choices=("persistent", "memory"),
        default="persistent",
        help="Persistent is the production default; memory accepts restart/outage loss",
    )
    parser.add_argument(
        "--galileo-proxy-url",
        default=DEFAULT_GALILEO_PROXY_URL,
        help=(
            "Explicit loopback tinyproxy URL used only by the Galileo otlp_http "
            "exporter (canonical http://127.0.0.1:PORT)"
        ),
    )
    parser.add_argument(
        "--queue-storage-directory",
        type=Path,
        default=Path("/var/lib/splunk-otel-collector/galileo-queue"),
        help="Service-user-writable absolute directory for the persistent Galileo queue",
    )
    parser.add_argument(
        "--destination-fingerprint",
        default="",
        help=(
            "Lowercase SHA-256 emitted by collector_runtime_wrapper.py; production "
            "queues must end with this path component"
        ),
    )
    parser.add_argument(
        "--production",
        action="store_true",
        help="Require a destination-fingerprinted persistent queue render",
    )
    parser.add_argument("--native-traces-pipeline", default="traces")
    parser.add_argument("--lemonade-service-name", default="lemonade-server")
    parser.add_argument("--client-receiver-endpoint", default="127.0.0.1:14318")
    parser.add_argument("--client-service-name", default="lemonade-galileo-client")
    parser.add_argument(
        "--client-processor",
        action="append",
        default=[],
        help="Explicit client processor component; repeat to override the safe inherited set",
    )
    parser.add_argument(
        "--mirror-client-to-native-exporters",
        action="store_true",
        help="Also send caller spans to native exporters; may duplicate LLMs in Splunk",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.galileo_console_url:
        try:
            instance = resolve_console_url(args.galileo_console_url)
        except ValueError as exc:
            raise SystemExit(f"ERROR: {exc}") from exc
        print(f"Galileo console origin: {instance['console_origin']}")
        print(f"Galileo API base candidate: {instance['api_base_candidate']}")
        print(f"Galileo OTLP traces candidate: {instance['otlp_traces_candidate']}")
        if instance["console_route"] != "/":
            print(
                "Galileo console navigation route: "
                f"{instance['console_route']} (not a project or Log stream selector)"
            )
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
    print(f"Rendered {args.mode} collector config: {args.output}")


if __name__ == "__main__":
    main()
