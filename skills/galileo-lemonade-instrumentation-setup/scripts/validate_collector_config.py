#!/usr/bin/env python3
"""Validate a rendered Galileo/Lemonade collector configuration."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
from pathlib import Path
from typing import Any

from render_collector_config import (
    CLIENT_PIPELINE,
    CLIENT_PRIVACY,
    CLIENT_RECEIVER,
    CLIENT_RESOURCE,
    CLIENT_SEMANTICS,
    ERROR_PRIVACY,
    DEFAULT_GALILEO_PROXY_URL,
    GALILEO_EXPORTER,
    GALILEO_STORAGE,
    LEGACY_GALILEO_EXPORTER,
    SAFE_CLIENT_PROCESSOR_TYPES,
    ROUTE_GUARD,
    SERVER_FILTER,
    SERVER_PIPELINE,
    client_error_privacy_processor,
    client_semantics_processor,
    conflicting_galileo_artifacts,
    error_privacy_processor,
    existing_galileo_routes,
    galileo_exporter,
    galileo_storage,
    galileo_route_guard_processor,
    fingerprinted_queue_directory,
    processor_type,
    terminal_batch_split,
    validate_galileo_proxy_url,
)
from collector_runtime_wrapper import (
    SHA256,
    destination_fingerprint,
    validate_declared_fingerprint,
    validate_endpoint,
    validate_expected_origin,
    validate_selectors,
    validate_tinyproxy_contract,
)


def mapping(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"expected mapping at {key}")
    return value


def string_list(parent: dict[str, Any], key: str, location: str) -> list[str]:
    value = parent.get(key)
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
        or len(value) != len(set(value))
    ):
        raise ValueError(f"{location}.{key} must be a non-empty unique string list")
    return value


ENV_HOST = re.compile(r"\$\{(?:(?:env):)?([A-Za-z_][A-Za-z0-9_]*)\}")


def resolved_endpoint(value: str, location: str) -> tuple[str, int]:
    try:
        host, port = value.rsplit(":", 1)
        numeric_port = int(port)
        if not 1 <= numeric_port <= 65535:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError(f"{location} must be an explicit host:port endpoint") from None
    host = host.strip("[]")
    placeholder = ENV_HOST.fullmatch(host)
    if placeholder:
        variable = placeholder.group(1)
        host = os.environ.get(variable, "").strip().strip("[]")
        if not host:
            raise ValueError(
                f"{location} uses {placeholder.group(0)}; set {variable} for validation"
            )
    if any(character in host for character in "/?#@"):
        raise ValueError(f"{location} contains an invalid host")
    return host, numeric_port


def loopback(value: str, location: str) -> bool:
    host, _ = resolved_endpoint(value, location)
    try:
        return host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_receiver_loopback(receiver: dict[str, Any], location: str) -> None:
    protocols = receiver.get("protocols")
    endpoints: list[tuple[str, Any]] = []
    if protocols is not None:
        if not isinstance(protocols, dict) or not protocols:
            raise ValueError(f"{location}.protocols must be a non-empty mapping")
        for protocol_name, protocol in protocols.items():
            if not isinstance(protocol, dict) or "endpoint" not in protocol:
                raise ValueError(
                    f"{location}.protocols.{protocol_name} needs an explicit endpoint"
                )
            endpoints.append(
                (f"{location}.protocols.{protocol_name}.endpoint", protocol["endpoint"])
            )
    elif "endpoint" in receiver:
        endpoints.append((f"{location}.endpoint", receiver["endpoint"]))
    if not endpoints:
        raise ValueError(
            f"{location} has no explicit bind endpoint; shared server provenance is unverified"
        )
    for endpoint_location, endpoint in endpoints:
        if not isinstance(endpoint, str) or not loopback(endpoint, endpoint_location):
            raise ValueError(f"{endpoint_location} must be loopback-bound")


def before_first_batch(processors: list[str], components: tuple[str, ...]) -> bool:
    batch_indexes = [
        index
        for index, name in enumerate(processors)
        if processor_type(name) == "batch"
    ]
    boundary = min(batch_indexes) if batch_indexes else len(processors)
    return all(
        component in processors and processors.index(component) < boundary
        for component in components
    )


def require_terminal_guards(processors: list[str], *, privacy: str, label: str) -> None:
    """Require privacy and route deletion to be the final non-batch mutations."""

    non_batch, _ = terminal_batch_split(processors, label=label)
    if len(non_batch) < 2 or non_batch[-2:] != [privacy, ROUTE_GUARD]:
        raise ValueError(
            f"{label} must end its non-batch processors with {privacy}, {ROUTE_GUARD}"
        )


def client_resource(service_name: str) -> dict[str, Any]:
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


def validate(
    path: Path,
    mode: str,
    native_pipeline: str,
    lemonade_service_name: str = "lemonade-server",
    allow_client_mirror: bool = False,
    allow_custom_client_processors: bool = False,
    client_service_name: str = "lemonade-galileo-client",
    client_receiver_endpoint: str = "127.0.0.1:14318",
    queue_policy: str = "persistent",
    queue_storage_directory: str = "/var/lib/splunk-otel-collector/galileo-queue",
    production: bool = False,
    allow_server_shared_receiver: bool = False,
    destination_fingerprint_value: str = "",
    galileo_proxy_url: str = DEFAULT_GALILEO_PROXY_URL,
) -> None:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise ValueError(
            "PyYAML is required; install requirements-dev.txt in an isolated environment"
        ) from exc
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid collector YAML: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError("collector config root must be a mapping")
    receivers = mapping(document, "receivers")
    processors = mapping(document, "processors")
    exporters = mapping(document, "exporters")
    service = mapping(document, "service")
    pipelines = mapping(service, "pipelines")
    native = mapping(pipelines, native_pipeline)
    native_receivers = string_list(native, "receivers", f"pipelines.{native_pipeline}")
    native_processors = string_list(
        native, "processors", f"pipelines.{native_pipeline}"
    )
    native_routes = string_list(native, "exporters", f"pipelines.{native_pipeline}")
    production_selector_kind: str | None = None

    for name, config in exporters.items():
        component_type = name.split("/", 1)[0].casefold()
        if (
            isinstance(config, dict)
            and (
                name in native_routes
                or "splunk" in name.casefold()
                or component_type == "signalfx"
            )
            and "proxy_url" in config
        ):
            raise ValueError(f"Splunk exporter {name} must remain direct")

    conflicts = conflicting_galileo_artifacts(document)
    if conflicts:
        raise ValueError(
            "another Galileo-like exporter/route or dedicated receiver reference exists: "
            + ", ".join(conflicts)
        )
    if "resource/lemonade" in processors or "resource/lemonade" in (
        native.get("processors") or []
    ):
        raise ValueError(
            "legacy resource/lemonade relabeling remains; run the baseline migration first"
        )

    if LEGACY_GALILEO_EXPORTER in exporters or any(
        LEGACY_GALILEO_EXPORTER in (pipeline.get("exporters") or [])
        for pipeline in pipelines.values()
        if isinstance(pipeline, dict)
    ):
        raise ValueError(
            f"legacy collector component remains: {LEGACY_GALILEO_EXPORTER}"
        )

    routes = []
    for name, pipeline in pipelines.items():
        if not isinstance(pipeline, dict):
            continue
        values = pipeline.get("exporters")
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(item, str) and item for item in values)
            or len(values) != len(set(values))
        ):
            raise ValueError(
                f"pipeline {name} has empty, invalid, or duplicate exporters"
            )
        if GALILEO_EXPORTER in values:
            routes.append(name)

    if mode == "splunk-only":
        if (
            GALILEO_EXPORTER in exporters
            or routes
            or CLIENT_PIPELINE in pipelines
            or SERVER_PIPELINE in pipelines
            or CLIENT_RECEIVER in receivers
            or GALILEO_STORAGE in (document.get("extensions") or {})
            or GALILEO_STORAGE in (service.get("extensions") or [])
            or any(
                component in processors
                for component in (
                    CLIENT_RESOURCE,
                    CLIENT_SEMANTICS,
                    CLIENT_PRIVACY,
                    SERVER_FILTER,
                    ERROR_PRIVACY,
                    ROUTE_GUARD,
                )
            )
        ):
            raise ValueError("splunk-only mode still contains managed Galileo routing")
        print("Galileo/Lemonade collector validation passed (splunk-only)")
        return

    if queue_policy not in {"persistent", "memory"}:
        raise ValueError("queue policy must be persistent or memory")
    galileo_proxy_url = validate_galileo_proxy_url(galileo_proxy_url)
    if production:
        if queue_policy != "persistent":
            raise ValueError(
                "production validation requires the persistent queue policy"
            )
        if mode == "server-fanout" and not allow_server_shared_receiver:
            raise ValueError(
                "server-fanout shares a receiver and can replay Splunk spans on downstream "
                "failure; pass --allow-server-shared-receiver after accepting that risk"
            )
        if not SHA256.fullmatch(destination_fingerprint_value):
            raise ValueError(
                "production validation requires --destination-fingerprint as lowercase SHA-256"
            )
        queue_path = Path(queue_storage_directory)
        if not queue_path.is_absolute() or not fingerprinted_queue_directory(
            queue_path, destination_fingerprint_value
        ):
            raise ValueError(
                "production queue directory must end with the destination fingerprint"
            )
        endpoint_origin, canonical_endpoint = validate_endpoint(
            os.environ.get("GALILEO_OTLP_TRACES_ENDPOINT", "")
        )
        validate_expected_origin(
            os.environ.get("GALILEO_EXPECTED_ORIGIN", ""), endpoint_origin
        )
        selectors = validate_selectors(dict(os.environ))
        production_selector_kind = selectors[0]
        derived = destination_fingerprint(canonical_endpoint, selectors)
        validate_declared_fingerprint(
            {
                **dict(os.environ),
                "GALILEO_DESTINATION_FINGERPRINT": destination_fingerprint_value,
            },
            derived,
        )
        environment = dict(os.environ)
        if environment.get("GALILEO_PROXY_URL", "") != galileo_proxy_url:
            raise ValueError("--galileo-proxy-url must match GALILEO_PROXY_URL")
        validate_tinyproxy_contract(environment, canonical_endpoint)
        if os.environ.get("GALILEO_QUEUE_STORAGE_DIRECTORY", "") != str(queue_path):
            raise ValueError(
                "GALILEO_QUEUE_STORAGE_DIRECTORY must match the validated config path"
            )

    id_headers = {
        "Galileo-API-Key": "${env:GALILEO_API_KEY}",
        "projectid": "${env:GALILEO_PROJECT_ID}",
        "logstreamid": "${env:GALILEO_LOG_STREAM_ID}",
    }
    name_headers = {
        "Galileo-API-Key": "${env:GALILEO_API_KEY}",
        "project": "${env:GALILEO_PROJECT}",
        "logstream": "${env:GALILEO_LOG_STREAM}",
    }
    exporter = exporters.get(GALILEO_EXPORTER)
    if not isinstance(exporter, dict):
        raise ValueError(f"missing exporter {GALILEO_EXPORTER}")
    headers = exporter.get("headers")
    if headers == id_headers:
        routing = "ids"
    elif headers == name_headers:
        routing = "names"
    else:
        raise ValueError("Galileo exporter must use exactly one complete selector pair")
    if production and production_selector_kind != routing:
        raise ValueError(
            "runtime Galileo selector kind must match the rendered exporter routing kind"
        )
    if exporter != galileo_exporter(routing, queue_policy, galileo_proxy_url):
        raise ValueError(
            "Galileo exporter does not match the managed retry/queue shape"
        )

    extensions = document.get("extensions") or {}
    if not isinstance(extensions, dict):
        raise ValueError("extensions must be a mapping")
    service_extensions = service.get("extensions") or []
    if (
        not isinstance(service_extensions, list)
        or not all(isinstance(item, str) and item for item in service_extensions)
        or len(service_extensions) != len(set(service_extensions))
    ):
        raise ValueError("service.extensions must be a unique string list")
    if queue_policy == "persistent":
        expected_storage = galileo_storage(queue_storage_directory)
        if extensions.get(GALILEO_STORAGE) != expected_storage:
            raise ValueError("persistent Galileo file storage does not match policy")
        if service_extensions.count(GALILEO_STORAGE) != 1:
            raise ValueError("persistent Galileo file storage extension is not enabled")
    elif GALILEO_STORAGE in extensions or GALILEO_STORAGE in service_extensions:
        raise ValueError(
            "memory queue mode contains the managed file storage extension"
        )

    duplicates = existing_galileo_routes(document, native_receivers)
    if duplicates:
        raise ValueError(
            "another Galileo-like route is reachable from the native receiver set: "
            + ", ".join(sorted(duplicates))
        )

    if GALILEO_EXPORTER in native_routes:
        raise ValueError("native shared pipeline must never export directly to Galileo")
    if ERROR_PRIVACY not in native_processors:
        raise ValueError(
            "native pipeline is missing conditional Lemonade error redaction"
        )
    privacy_config = processors.get(ERROR_PRIVACY)
    if privacy_config != error_privacy_processor(lemonade_service_name):
        raise ValueError("managed error privacy processor does not match exact policy")
    if not before_first_batch(native_processors, (ERROR_PRIVACY,)):
        raise ValueError("native error privacy processor must run before batch")
    if mode == "server-fanout":
        if routes != [SERVER_PIPELINE]:
            raise ValueError(
                "server-fanout must route Galileo only from its filtered pipeline"
            )
        if CLIENT_PIPELINE in pipelines or CLIENT_RECEIVER in receivers:
            raise ValueError("server-fanout contains client-mode components")
        server = mapping(pipelines, SERVER_PIPELINE)
        server_receivers = string_list(
            server, "receivers", f"pipelines.{SERVER_PIPELINE}"
        )
        if server_receivers != native_receivers:
            raise ValueError(
                "server Galileo pipeline must share the reviewed native receiver set"
            )
        if string_list(server, "exporters", f"pipelines.{SERVER_PIPELINE}") != [
            GALILEO_EXPORTER
        ]:
            raise ValueError("server Galileo pipeline must be Galileo-only")
        server_processors = string_list(
            server, "processors", f"pipelines.{SERVER_PIPELINE}"
        )
        undefined = [name for name in server_processors if name not in processors]
        if undefined:
            raise ValueError(
                "server pipeline references undefined processors: "
                + ", ".join(undefined)
            )
        unsafe = [
            name
            for name in server_processors
            if name
            not in {
                SERVER_FILTER,
                ERROR_PRIVACY,
                ROUTE_GUARD,
                "transform/lemonade_resource_privacy",
            }
            and processor_type(name) not in SAFE_CLIENT_PROCESSOR_TYPES
        ]
        if unsafe:
            raise ValueError(
                "server pipeline has non-baseline processors: " + ", ".join(unsafe)
            )
        if not before_first_batch(
            server_processors, (SERVER_FILTER, ERROR_PRIVACY, ROUTE_GUARD)
        ):
            raise ValueError(
                "server filter, privacy, and route guard must run before batch"
            )
        require_terminal_guards(
            server_processors,
            privacy=ERROR_PRIVACY,
            label="server Galileo pipeline",
        )
        if processors.get(ROUTE_GUARD) != galileo_route_guard_processor():
            raise ValueError("Galileo route guard does not match exact policy")
        route_guard_index = server_processors.index(ROUTE_GUARD)
        if route_guard_index <= max(
            server_processors.index(SERVER_FILTER),
            server_processors.index(ERROR_PRIVACY),
        ):
            raise ValueError(
                "Galileo route guard must run after server privacy/filtering"
            )
        if (
            "transform/lemonade_resource_privacy" in native_processors
            and "transform/lemonade_resource_privacy" not in server_processors
        ):
            raise ValueError(
                "server Galileo branch dropped the baseline Lemonade transform"
            )
        filter_config = processors.get(SERVER_FILTER)
        expected_condition = f'resource.attributes["service.name"] != {json.dumps(lemonade_service_name)}'
        if (
            not isinstance(filter_config, dict)
            or filter_config.get("error_mode") != "propagate"
            or filter_config.get("trace_conditions") != [expected_condition]
        ):
            raise ValueError(
                "server source filter does not match the Lemonade service name"
            )
        for receiver_name in server_receivers:
            receiver = receivers.get(receiver_name)
            if not isinstance(receiver, dict):
                raise ValueError(f"server receiver is undefined: {receiver_name}")
            validate_receiver_loopback(receiver, f"receivers.{receiver_name}")
    elif mode == "client-fanout":
        if routes != [CLIENT_PIPELINE]:
            raise ValueError(
                "client-fanout must route Galileo only from the client pipeline"
            )
        pipeline = mapping(pipelines, CLIENT_PIPELINE)
        if string_list(pipeline, "receivers", f"pipelines.{CLIENT_PIPELINE}") != [
            CLIENT_RECEIVER
        ]:
            raise ValueError("client pipeline must use only its dedicated receiver")
        client_exporters = string_list(
            pipeline, "exporters", f"pipelines.{CLIENT_PIPELINE}"
        )
        if not allow_client_mirror and client_exporters != [GALILEO_EXPORTER]:
            raise ValueError(
                "client pipeline must be Galileo-only unless --allow-client-mirror is explicit"
            )
        if allow_client_mirror and client_exporters != [
            *native_routes,
            GALILEO_EXPORTER,
        ]:
            raise ValueError(
                "client mirror must contain the exact native exporter sequence "
                "followed by the Galileo exporter"
            )
        client_processors = string_list(
            pipeline, "processors", f"pipelines.{CLIENT_PIPELINE}"
        )
        undefined_processors = [
            item for item in client_processors if item not in processors
        ]
        if undefined_processors:
            raise ValueError(
                "client pipeline references undefined processor(s): "
                + ", ".join(undefined_processors)
            )
        unsafe_processors = [
            item
            for item in client_processors
            if item
            not in {CLIENT_RESOURCE, CLIENT_SEMANTICS, CLIENT_PRIVACY, ROUTE_GUARD}
            and processor_type(str(item)) not in SAFE_CLIENT_PROCESSOR_TYPES
        ]
        if unsafe_processors and not allow_custom_client_processors:
            raise ValueError(
                "client pipeline has non-baseline processors; review and pass "
                "--allow-custom-client-processors: " + ", ".join(unsafe_processors)
            )
        for required in (
            CLIENT_RESOURCE,
            CLIENT_SEMANTICS,
            CLIENT_PRIVACY,
            ROUTE_GUARD,
        ):
            if required not in client_processors:
                raise ValueError(
                    f"client pipeline is missing managed processor {required}"
                )
        if not before_first_batch(
            client_processors,
            (CLIENT_RESOURCE, CLIENT_SEMANTICS, CLIENT_PRIVACY, ROUTE_GUARD),
        ):
            raise ValueError("managed client processors must run before batch")
        indexes = [
            client_processors.index(name)
            for name in (
                CLIENT_RESOURCE,
                CLIENT_SEMANTICS,
                CLIENT_PRIVACY,
                ROUTE_GUARD,
            )
        ]
        if indexes != sorted(indexes):
            raise ValueError(
                "client resource, semantics, privacy, and route guard order is invalid"
            )
        require_terminal_guards(
            client_processors,
            privacy=CLIENT_PRIVACY,
            label="client Galileo pipeline",
        )
        if processors.get(CLIENT_RESOURCE) != client_resource(client_service_name):
            raise ValueError("client resource processor does not match exact policy")
        if processors.get(CLIENT_SEMANTICS) != client_semantics_processor():
            raise ValueError(
                "client semantic normalization does not match exact policy"
            )
        if processors.get(CLIENT_PRIVACY) != client_error_privacy_processor():
            raise ValueError("client content/error privacy does not match exact policy")
        if processors.get(ROUTE_GUARD) != galileo_route_guard_processor():
            raise ValueError("Galileo route guard does not match exact policy")
        receiver = mapping(receivers, CLIENT_RECEIVER)
        expected_receiver = {
            "protocols": {"http": {"endpoint": client_receiver_endpoint}}
        }
        if receiver != expected_receiver or not loopback(
            client_receiver_endpoint, "client receiver endpoint"
        ):
            raise ValueError("client OTLP/HTTP receiver must be loopback-bound")
    else:
        raise ValueError(f"unsupported mode: {mode}")
    print(f"Galileo/Lemonade collector validation passed ({mode})")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Production mode requires a persistent queue and the protected, live-probed "
            "tinyproxy exact-origin contract because the stock Collector follows redirects."
        ),
    )
    parser.add_argument("--collector-config", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=("server-fanout", "client-fanout", "splunk-only"),
        required=True,
    )
    parser.add_argument("--native-traces-pipeline", default="traces")
    parser.add_argument("--lemonade-service-name", default="lemonade-server")
    parser.add_argument("--client-service-name", default="lemonade-galileo-client")
    parser.add_argument("--client-receiver-endpoint", default="127.0.0.1:14318")
    parser.add_argument(
        "--queue-policy", choices=("persistent", "memory"), default="persistent"
    )
    parser.add_argument(
        "--queue-storage-directory",
        default="/var/lib/splunk-otel-collector/galileo-queue",
    )
    parser.add_argument("--destination-fingerprint", default="")
    parser.add_argument("--production", action="store_true")
    parser.add_argument(
        "--galileo-proxy-url",
        default=DEFAULT_GALILEO_PROXY_URL,
        help="Must match the Galileo exporter's canonical loopback proxy_url",
    )
    parser.add_argument("--allow-server-shared-receiver", action="store_true")
    parser.add_argument("--allow-client-mirror", action="store_true")
    parser.add_argument("--allow-custom-client-processors", action="store_true")
    args = parser.parse_args()
    try:
        validate(
            args.collector_config,
            args.mode,
            args.native_traces_pipeline,
            args.lemonade_service_name,
            args.allow_client_mirror,
            args.allow_custom_client_processors,
            args.client_service_name,
            args.client_receiver_endpoint,
            args.queue_policy,
            args.queue_storage_directory,
            args.production,
            args.allow_server_shared_receiver,
            args.destination_fingerprint,
            args.galileo_proxy_url,
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc


if __name__ == "__main__":
    main()
