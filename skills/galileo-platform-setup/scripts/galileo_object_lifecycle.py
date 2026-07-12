#!/usr/bin/env python3
"""Create or validate Galileo platform objects from a local manifest.

The script is intentionally secret-file based. It reads the Galileo API key
from a local file, sets Galileo SDK environment variables, and writes a JSON
result without echoing secret values.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import ipaddress
import json
import os
import re
import ssl
import stat
import urllib.error
import urllib.parse
import urllib.request
import uuid
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable


SUPPORTED_DATASET_SUFFIXES = {".csv", ".json", ".jsonl"}
MAX_SECRET_FILE_BYTES = 64 * 1024


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--galileo-api-key-file", required=True)
    parser.add_argument("--project-name", default="")
    parser.add_argument("--project-id", default="")
    parser.add_argument("--log-stream-name", default="")
    parser.add_argument("--log-stream-id", default="")
    parser.add_argument("--console-url", default="")
    parser.add_argument("--api-base", default="")
    parser.add_argument("--manifest", default="")
    parser.add_argument("--dataset-dir", default="")
    parser.add_argument("--prompt-manifest", default="")
    parser.add_argument("--experiment-manifest", default="")
    parser.add_argument("--protect-stage-manifest", default="")
    parser.add_argument("--metrics", default="")
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--ownership-ledger",
        default="",
        help="Created-object ledger path (defaults beside --output).",
    )
    parser.add_argument(
        "--cleanup-created",
        action="store_true",
        help="Delete only exact IDs recorded by a prior run's ownership ledger.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def load_structured_file(path: Path) -> Any:
    if not path.is_file():
        raise SystemExit(f"ERROR: File not found: {path}")
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix == ".json":
        return json.loads(text)
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore[import-not-found]
        except ModuleNotFoundError as exc:
            raise SystemExit(f"ERROR: YAML manifest requires PyYAML: {path}") from exc
        return yaml.safe_load(text) or {}
    if suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    raise SystemExit(f"ERROR: Unsupported structured file type: {path}")


def load_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def load_dataset_content(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        rows = load_csv(path)
    else:
        data = load_structured_file(path)
        if isinstance(data, dict):
            rows = data.get("content") or data.get("rows") or data.get("data") or []
        else:
            rows = data
    if not isinstance(rows, list):
        raise SystemExit(f"ERROR: Dataset content must be a list of rows: {path}")
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise SystemExit(f"ERROR: Dataset row must be an object: {path}")
        normalized.append(dict(row))
    return normalized


def read_manifest(path: str) -> dict[str, Any]:
    if not path:
        return {}
    loaded = load_structured_file(Path(path).expanduser())
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise SystemExit("ERROR: Lifecycle manifest must be a mapping")
    return loaded


def read_items(path: str, key: str) -> list[dict[str, Any]]:
    if not path:
        return []
    loaded = load_structured_file(Path(path).expanduser())
    if isinstance(loaded, list):
        items = loaded
    elif isinstance(loaded, dict):
        items = loaded.get(key) or loaded.get("items") or [loaded]
    else:
        raise SystemExit(f"ERROR: {path} must contain a list or mapping")
    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise SystemExit(f"ERROR: {path} contains a non-object item")
        result.append(dict(item))
    return result


def discover_dataset_dir(path: str) -> list[dict[str, Any]]:
    if not path:
        return []
    root = Path(path).expanduser()
    if not root.is_dir():
        raise SystemExit(f"ERROR: Dataset directory not found: {root}")
    datasets: list[dict[str, Any]] = []
    for candidate in sorted(root.iterdir()):
        if candidate.suffix.lower() not in SUPPORTED_DATASET_SUFFIXES:
            continue
        datasets.append({"name": candidate.stem, "path": str(candidate), "create": True})
    return datasets


def parse_metrics(value: str | list[Any] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def merge_inputs(args: argparse.Namespace) -> dict[str, Any]:
    manifest = read_manifest(args.manifest)
    project = dict(manifest.get("project") or {})
    project.setdefault("name", args.project_name)
    project.setdefault("id", args.project_id)
    project.setdefault("create", True)

    log_stream = dict(manifest.get("log_stream") or {})
    log_stream.setdefault("name", args.log_stream_name)
    log_stream.setdefault("id", args.log_stream_id)
    log_stream.setdefault("create", True)
    if args.metrics and "metrics" not in log_stream:
        log_stream["metrics"] = parse_metrics(args.metrics)

    datasets = list(manifest.get("datasets") or [])
    datasets.extend(discover_dataset_dir(args.dataset_dir))
    prompts = list(manifest.get("prompts") or [])
    prompts.extend(read_items(args.prompt_manifest, "prompts"))
    experiments = list(manifest.get("experiments") or [])
    experiments.extend(read_items(args.experiment_manifest, "experiments"))
    protect_stages = list(manifest.get("protect_stages") or [])
    protect_stages.extend(read_items(args.protect_stage_manifest, "protect_stages"))
    agent_targets = list(manifest.get("agent_control_targets") or [])

    return {
        "api_version": manifest.get("api_version", "galileo-platform-setup/object-lifecycle/v1"),
        "project": project,
        "log_stream": log_stream,
        "datasets": [dict(item) for item in datasets if isinstance(item, dict)],
        "prompts": [dict(item) for item in prompts if isinstance(item, dict)],
        "experiments": [dict(item) for item in experiments if isinstance(item, dict)],
        "protect_stages": [dict(item) for item in protect_stages if isinstance(item, dict)],
        "agent_control_targets": [dict(item) for item in agent_targets if isinstance(item, dict)],
    }


def read_secret_file(path: str) -> str:
    secret_path = Path(path).expanduser()
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "geteuid"):
        raise SystemExit("ERROR: Galileo API key cannot be read safely on this platform")
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
    try:
        descriptor = os.open(secret_path, flags)
    except OSError as exc:
        raise SystemExit(
            f"ERROR: Galileo API key file must be a readable, non-symlink regular file: {secret_path}"
        ) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise SystemExit(
                f"ERROR: Galileo API key file must be a single-link regular file: {secret_path}"
            )
        if before.st_uid != os.geteuid():
            raise SystemExit(
                f"ERROR: Galileo API key file must be owned by the current user: {secret_path}"
            )
        mode = stat.S_IMODE(before.st_mode)
        if mode & 0o077:
            raise SystemExit(
                f"ERROR: Galileo API key file permissions must be 0600 or stricter: "
                f"{secret_path} has {mode:04o}"
            )
        if not 1 <= before.st_size <= MAX_SECRET_FILE_BYTES:
            raise SystemExit(
                f"ERROR: Galileo API key file size must be between 1 and "
                f"{MAX_SECRET_FILE_BYTES} bytes: {secret_path}"
            )
        chunks: list[bytes] = []
        remaining = MAX_SECRET_FILE_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 8192))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        before_fingerprint = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
            before.st_nlink,
        )
        after_fingerprint = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
            after.st_nlink,
        )
        data = b"".join(chunks)
        if before_fingerprint != after_fingerprint or len(data) != before.st_size:
            raise SystemExit(f"ERROR: Galileo API key file changed while it was read: {secret_path}")
    finally:
        os.close(descriptor)
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise SystemExit(
            f"ERROR: Galileo API key file must contain UTF-8 text: {secret_path}"
        ) from exc
    if len(lines) != 1 or not lines[0] or "\x00" in lines[0]:
        raise SystemExit(
            f"ERROR: Galileo API key file must contain exactly one non-empty line: {secret_path}"
        )
    return lines[0]


def configure_environment(args: argparse.Namespace, config: dict[str, Any]) -> None:
    os.environ["GALILEO_API_KEY"] = read_secret_file(args.galileo_api_key_file)
    if args.console_url:
        os.environ["GALILEO_CONSOLE_URL"] = args.console_url.rstrip("/")
    if args.api_base:
        api_base = args.api_base.rstrip("/")
        os.environ["GALILEO_API_URL"] = api_base
        os.environ["GALILEO_API_BASE"] = api_base
    if args.api_base or args.console_url:
        _validated_api_base()
    project = config.get("project") or {}
    log_stream = config.get("log_stream") or {}
    if project.get("name"):
        os.environ["GALILEO_PROJECT"] = str(project["name"])
    if project.get("id"):
        os.environ["GALILEO_PROJECT_ID"] = str(project["id"])
    if log_stream.get("name"):
        os.environ["GALILEO_LOG_STREAM"] = str(log_stream["name"])
    if log_stream.get("id"):
        os.environ["GALILEO_LOG_STREAM_ID"] = str(log_stream["id"])


def require_galileo_sdk() -> None:
    try:
        import galileo  # noqa: F401
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "ERROR: Galileo Python SDK is not installed. Install with `pip install galileo` "
            "before applying object lifecycle provisioning."
        ) from exc


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects so the Galileo API key never crosses origins."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


def _validated_api_base() -> str:
    raw = (os.environ.get("GALILEO_API_BASE") or os.environ.get("GALILEO_API_URL") or "").strip()
    if not raw:
        console = os.environ.get("GALILEO_CONSOLE_URL", "").strip()
        parsed_console = urllib.parse.urlparse(console)
        if parsed_console.scheme not in {"http", "https"} or not parsed_console.hostname:
            raise RuntimeError(
                "The project compatibility fallback requires --api-base or a derivable --console-url"
            )
        host = parsed_console.hostname.lower()
        if host == "app.galileo.ai":
            api_host = "api.galileo.ai"
        elif host.startswith("console."):
            api_host = "api." + host.removeprefix("console.")
        elif host.startswith("console-"):
            api_host = "api-" + host.removeprefix("console-")
        else:
            raise RuntimeError(
                "The project compatibility fallback cannot derive an API host from --console-url; "
                "pass --api-base"
            )
        raw = urllib.parse.urlunparse(
            (
                parsed_console.scheme,
                api_host + (f":{parsed_console.port}" if parsed_console.port else ""),
                "",
                "",
                "",
                "",
            )
        )
    parsed = urllib.parse.urlparse(raw)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("Galileo API base must be a credential-free HTTP(S) origin")
    try:
        parsed.port
    except ValueError as exc:
        raise RuntimeError("Galileo API base contains an invalid port") from exc
    if parsed.scheme == "http":
        host = parsed.hostname or ""
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host.lower() == "localhost"
        if not loopback:
            raise RuntimeError(
                "Galileo API base must use HTTPS unless the host is loopback; "
                "refusing to send Galileo-API-Key over cleartext"
            )
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "", "", "", "")).rstrip("/")


def _project_rest_request(
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    not_found_is_none: bool = False,
) -> dict[str, Any] | None:
    api_key = os.environ.get("GALILEO_API_KEY", "")
    if not api_key:
        raise RuntimeError("Galileo API key is unavailable for the project compatibility fallback")
    encoded = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        _validated_api_base() + path,
        data=encoded,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Galileo-API-Key": api_key,
        },
    )
    opener = urllib.request.build_opener(
        NoRedirectHandler(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )
    try:
        with opener.open(request, timeout=60) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and not_found_is_none:
            return None
        raise RuntimeError(
            f"Galileo project compatibility request failed with HTTP {exc.code}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Galileo project compatibility request failed") from exc
    if not payload.strip():
        return {}
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Galileo project compatibility response was not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError("Galileo project compatibility response was not a JSON object")
    return decoded


def _is_known_project_schema_error(exc: Exception) -> bool:
    """Match only the SDK 2.4 permission-enum incompatibility seen on newer tenants."""

    message = str(exc).lower()
    error_type = type(exc).__name__.lower()
    permission_marker = any(
        marker in message for marker in ("update_control_bindings", "use_control_runtime")
    )
    enum_marker = "not a valid" in message or (
        "validationerror" in error_type and ("enum" in message or "input should be" in message)
    )
    return permission_marker and enum_marker


def _is_exact_not_found_error(exc: Exception) -> bool:
    """Recognize only an explicit HTTP 404 from an exact-ID SDK lookup."""

    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    if status == 404:
        return True
    message = str(exc).lower()
    return "not found" in message and bool(
        re.search(r"(?:\bhttp\s*404\b|\bstatus(?:_code| code)?\s*[=:]?\s*404\b)", message)
    )


def _get_project_rest(*, project_id: str = "", name: str = "") -> dict[str, Any] | None:
    if bool(project_id) == bool(name):
        raise RuntimeError("Project REST fallback requires exactly one of id or name")
    if project_id:
        project = _project_rest_request(
            "GET",
            "/v2/projects/" + urllib.parse.quote(project_id, safe=""),
            not_found_is_none=True,
        )
        if project is not None and str(project.get("id") or "") != project_id:
            raise RuntimeError("Galileo project compatibility lookup returned a different project ID")
        return project

    response = _project_rest_request(
        "POST",
        "/v2/projects/paginated?starting_token=0&limit=100",
        body={
            "filters": [
                {
                    "operator": "eq",
                    "value": name,
                    "name": "name",
                    "case_sensitive": True,
                }
            ],
            "sort": {"name": "created_at", "ascending": False, "sort_type": "column"},
        },
    )
    projects = response.get("projects") if response else None
    if not isinstance(projects, list):
        raise RuntimeError("Galileo project compatibility list response omitted projects")
    exact = [item for item in projects if isinstance(item, dict) and item.get("name") == name]
    if len(exact) > 1:
        raise RuntimeError(f"Galileo project compatibility lookup found duplicate exact name {name!r}")
    return exact[0] if exact else None


def get_project_compat(
    get_project: Callable[..., Any], *, project_id: str = "", name: str = ""
) -> tuple[Any, str]:
    kwargs = {"id": project_id} if project_id else {"name": name}
    try:
        return get_project(**kwargs), "sdk"
    except Exception as exc:
        if not _is_known_project_schema_error(exc):
            raise
        return _get_project_rest(project_id=project_id, name=name), "documented_rest_fallback"


def delete_project_compat(delete_project: Callable[..., Any], *, project_id: str) -> str:
    """Delete an exact project ID, narrowly bypassing the known SDK enum readback bug."""

    if _get_project_rest(project_id=project_id) is None:
        return "already_absent_verified"
    source = "sdk"
    try:
        deleted = delete_project(id=project_id)
        if deleted is not True:
            raise RuntimeError(f"Galileo did not confirm deletion of exact project ID {project_id}")
    except Exception as exc:
        if not _is_known_project_schema_error(exc):
            raise
        _project_rest_request(
            "DELETE",
            "/v2/projects/" + urllib.parse.quote(project_id, safe=""),
            not_found_is_none=True,
        )
        source = "documented_rest_fallback"
    if _get_project_rest(project_id=project_id) is not None:
        raise RuntimeError(f"Exact project ID {project_id} still exists after deletion")
    return source


def call_dataset_project_scoped(
    fn: Callable[..., Any],
    *,
    project_id: str,
    project_name: str,
    kwargs: dict[str, Any],
) -> tuple[Any, str]:
    """Call a dataset API with project association despite the SDK 2.4 enum read bug."""

    scope = {"project_id": project_id} if project_id else {"project_name": project_name}
    try:
        return fn(**kwargs, **scope), "sdk"
    except Exception as exc:
        if not _is_known_project_schema_error(exc):
            raise

        project = _get_project_rest(project_id=project_id, name="" if project_id else project_name)
        if project is None:
            raise RuntimeError("Dataset project association could not be verified") from exc
        verified_project_id = str(project.get("id") or "")
        if not verified_project_id:
            raise RuntimeError("Dataset project compatibility readback omitted the project ID") from exc

        # galileo.datasets imports resolve_project_id into its module namespace. The
        # SDK 2.4 implementation redundantly reads the project and deserializes the
        # tenant's newer permission enum before every scoped dataset operation. The
        # REST lookup above already verified this exact ID, so bypass only that one
        # redundant lookup for this synchronous CLI call, then restore immediately.
        import galileo.datasets as datasets_module

        original_resolver = datasets_module.resolve_project_id

        def exact_verified_resolver(
            candidate_id: str | None = None,
            candidate_name: str | None = None,
            allow_none: bool = False,
            validate: bool = True,
        ) -> str | None:
            if candidate_id == verified_project_id and candidate_name is None:
                return verified_project_id
            return original_resolver(
                candidate_id,
                candidate_name,
                allow_none=allow_none,
                validate=validate,
            )

        datasets_module.resolve_project_id = exact_verified_resolver
        try:
            return (
                fn(**kwargs, project_id=verified_project_id),
                "documented_rest_project_validation_sdk_workaround",
            )
        finally:
            datasets_module.resolve_project_id = original_resolver


def call_experiment_project_scoped(
    fn: Callable[..., Any],
    *,
    project_id: str,
    project_name: str,
    variants: list[dict[str, Any]],
) -> tuple[Any, str]:
    """Call experiment helpers despite the SDK 2.4 project enum read bug."""

    last_type_error: TypeError | None = None
    for variant in variants:
        kwargs = {
            key: value for key, value in variant.items() if value not in ("", None)
        }
        try:
            return fn(**kwargs), "sdk"
        except TypeError as exc:
            last_type_error = exc
            continue
        except Exception as exc:
            if not _is_known_project_schema_error(exc):
                raise

            project = _get_project_rest(
                project_id=project_id,
                name="" if project_id else project_name,
            )
            if project is None:
                raise RuntimeError(
                    "Experiment project association could not be verified"
                ) from exc
            verified_project_id = str(project.get("id") or "")
            verified_project_name = str(project.get("name") or project_name)
            if not verified_project_id:
                raise RuntimeError(
                    "Experiment project compatibility readback omitted the project ID"
                ) from exc

            # The public experiment convenience helpers redundantly deserialize
            # Project permissions before calling ID-scoped experiment routes.
            # The exact REST read above already verified this project, so bypass
            # only that lookup for this synchronous call and restore immediately.
            import galileo.experiments as experiments_module

            original_get = experiments_module.Projects.get_with_env_fallbacks

            def exact_verified_project(
                _self: Any,
                *,
                id: str | None = None,
                name: str | None = None,
            ) -> Any:
                if (id and id == verified_project_id) or (
                    not id and name and name == verified_project_name
                ):
                    return SimpleNamespace(
                        id=verified_project_id,
                        name=verified_project_name,
                    )
                return original_get(_self, id=id, name=name)

            experiments_module.Projects.get_with_env_fallbacks = (
                exact_verified_project
            )
            try:
                return (
                    fn(**kwargs),
                    "documented_rest_project_validation_sdk_workaround",
                )
            finally:
                experiments_module.Projects.get_with_env_fallbacks = original_get

    if last_type_error is not None:
        raise last_type_error
    return fn(), "sdk"


def get_value(obj: Any, *names: str) -> Any:
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj[name]
        if hasattr(obj, name):
            return getattr(obj, name)
    props = getattr(obj, "additional_properties", None)
    if isinstance(props, dict):
        for name in names:
            if name in props:
                return props[name]
    return None


def identity(obj: Any) -> dict[str, Any]:
    return {
        "id": get_value(obj, "id"),
        "name": get_value(obj, "name"),
    }


def experiment_group_contains(
    grouped: Any,
    *,
    experiment_id: str,
    experiment_name: str,
) -> bool:
    """Require an exact ID match when Galileo returned an experiment ID."""

    if experiment_id:
        return any(
            str(get_value(candidate, "id") or "") == experiment_id
            for candidate in grouped
        )
    return any(
        str(get_value(candidate, "name") or "") == experiment_name
        for candidate in grouped
    )


def require_cleanup_owned_project(project: dict[str, Any], object_kind: str) -> None:
    if not bool(project.get("_created_by_operation", False)):
        raise RuntimeError(
            f"Refusing to create {object_kind} in a pre-existing project: Galileo exposes no "
            "documented exact-ID cleanup for this object in the lifecycle helper. Create a "
            "disposable project in the same ownership ledger instead."
        )


def call_with_retries(fn: Callable[..., Any], variants: list[dict[str, Any]]) -> Any:
    last_error: Exception | None = None
    for kwargs in variants:
        try:
            return fn(**{key: value for key, value in kwargs.items() if value not in ("", None)})
        except TypeError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    return fn()


def ensure_project(config: dict[str, Any], dry_run: bool) -> tuple[dict[str, Any], Any]:
    item = config["project"]
    name = str(item.get("name") or "")
    project_id = str(item.get("id") or "")
    create = bool(item.get("create", True))
    if dry_run:
        return {"status": "planned", "id": project_id, "name": name, "create": create}, None
    from galileo.projects import create_project, get_project

    project = None
    resolution = "sdk"
    if project_id:
        project, resolution = get_project_compat(get_project, project_id=project_id)
        if project is None:
            raise RuntimeError(f"Requested project ID {project_id!r} was not found")
        actual_name = str(get_value(project, "name") or "")
        if name and actual_name and actual_name != name:
            raise RuntimeError(
                f"Requested project ID {project_id!r} resolves to {actual_name!r}, not {name!r}"
            )
    elif name:
        project, resolution = get_project_compat(get_project, name=name)
    if project is None and create:
        if not name:
            raise RuntimeError("Project name is required to create a project")
        try:
            project = create_project(name=name)
        except Exception as exc:
            if not _is_known_project_schema_error(exc):
                raise
            project = _get_project_rest(name=name)
            if project is None:
                raise RuntimeError(
                    "Galileo accepted project creation but the compatibility readback did not find it"
                ) from exc
            resolution = "documented_rest_fallback_after_create"
        status = "created"
    else:
        status = "exists" if project is not None else "missing"
    result = {
        "status": status,
        **identity(project),
        "requested": {"id": project_id, "name": name},
        "resolution": resolution,
    }
    if project is not None and not result.get("id"):
        raise RuntimeError("Galileo project response omitted its ID")
    return result, project


def ensure_log_stream(config: dict[str, Any], project: Any, dry_run: bool) -> tuple[dict[str, Any], Any]:
    item = config["log_stream"]
    name = str(item.get("name") or "")
    log_stream_id = str(item.get("id") or "")
    project_name = str((config["project"] or {}).get("name") or get_value(project, "name") or "")
    project_id = str((config["project"] or {}).get("id") or get_value(project, "id") or "")
    create = bool(item.get("create", True))
    if dry_run:
        return {
            "status": "planned",
            "id": log_stream_id,
            "name": name,
            "project_id": project_id,
            "project_name": project_name,
            "create": create,
        }, None
    if project is None or not (project_id or project_name):
        raise RuntimeError("A resolved project is required before resolving a log stream")
    from galileo.log_streams import create_log_stream, get_log_stream

    log_stream = None
    if log_stream_id:
        if not name:
            raise RuntimeError(
                "Log stream name is required with --log-stream-id because Galileo SDK 2.4.0 "
                "does not expose ID lookup; the project-scoped name result is verified by exact ID"
            )
        variants = (
            [{"name": name, "project_id": project_id}]
            if project_id
            else [{"name": name, "project_name": project_name}]
        )
        log_stream = call_with_retries(get_log_stream, variants)
        if log_stream is None:
            raise RuntimeError(f"Requested log stream ID {log_stream_id!r} was not found")
        actual_id = str(get_value(log_stream, "id") or "")
        actual_name = str(get_value(log_stream, "name") or "")
        actual_project_id = str(get_value(log_stream, "project_id") or "")
        if actual_id != log_stream_id:
            raise RuntimeError(
                f"Requested log stream ID {log_stream_id!r} resolved to a different ID {actual_id!r}"
            )
        if name and actual_name and actual_name != name:
            raise RuntimeError(
                f"Requested log stream ID {log_stream_id!r} resolves to {actual_name!r}, not {name!r}"
            )
        if project_id and actual_project_id and actual_project_id != project_id:
            raise RuntimeError(
                f"Requested log stream ID {log_stream_id!r} belongs to a different project"
            )
    elif name:
        log_stream = call_with_retries(
            get_log_stream,
            (
                [{"name": name, "project_id": project_id}]
                if project_id
                else [{"name": name, "project_name": project_name}]
            ),
        )
    if log_stream is None and create:
        if not name:
            raise RuntimeError("Log stream name is required to create a log stream")
        require_cleanup_owned_project(config["project"], "a log stream")
        log_stream = call_with_retries(
            create_log_stream,
            [{"name": name, "project_id": project_id}, {"name": name, "project_name": project_name}],
        )
        status = "created"
    else:
        status = "exists" if log_stream is not None else "missing"
    result = {
        "status": status,
        **identity(log_stream),
        "project_id": str(get_value(log_stream, "project_id") or project_id),
        "requested": {"id": log_stream_id, "name": name},
    }
    if log_stream is not None and not result.get("id"):
        raise RuntimeError("Galileo log stream response omitted its ID")
    return result, log_stream


def enable_log_stream_metrics(config: dict[str, Any], log_stream: Any, dry_run: bool) -> dict[str, Any]:
    metrics = parse_metrics((config.get("log_stream") or {}).get("metrics"))
    if not metrics:
        return {"status": "skipped", "metrics": []}
    if dry_run:
        return {"status": "planned", "metrics": metrics}
    if not bool((config.get("log_stream") or {}).get("_created_by_operation", False)):
        raise RuntimeError(
            "Refusing to change metrics on a pre-existing log stream: Galileo metric enablement "
            "can replace prior scorer settings and this lifecycle operation has no captured "
            "restore state. Use a disposable stream created by the same ownership ledger."
        )
    if log_stream is not None and hasattr(log_stream, "enable_metrics"):
        local_metrics = log_stream.enable_metrics(metrics)
        return {"status": "enabled", "metrics": metrics, "local_metrics": len(local_metrics or [])}
    from galileo.log_streams import enable_metrics

    project_name = str((config["project"] or {}).get("name") or "")
    log_stream_name = str((config["log_stream"] or {}).get("name") or "")
    local_metrics = enable_metrics(
        log_stream_name=log_stream_name,
        project_name=project_name,
        metrics=metrics,
    )
    return {"status": "enabled", "metrics": metrics, "local_metrics": len(local_metrics or [])}


def ensure_dataset(item: dict[str, Any], project: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    name = str(item.get("name") or "")
    dataset_id = str(item.get("id") or "")
    path = str(item.get("path") or "")
    content = item.get("content")
    project_name = str(item.get("project_name") or project.get("name") or "")
    project_id = str(item.get("project_id") or project.get("id") or "")
    create = bool(item.get("create", True))
    update_existing = bool(item.get("update_existing", False))
    if path:
        content = load_dataset_content(Path(path).expanduser())
    if not name and path:
        name = Path(path).stem
    if not name and not dataset_id:
        raise RuntimeError("Dataset name or id is required")
    if dry_run:
        return {
            "status": "planned",
            "id": dataset_id,
            "name": name,
            "project_id": project_id,
            "project_name": project_name,
            "rows": len(content or []),
        }
    if not (project_id or project_name):
        raise RuntimeError("A resolved project is required before resolving a dataset")
    from galileo.datasets import create_dataset, get_dataset

    dataset = None
    project_scope_resolution = "sdk"
    if dataset_id:
        dataset, project_scope_resolution = call_dataset_project_scoped(
            get_dataset,
            project_id=project_id,
            project_name=project_name,
            kwargs={"id": dataset_id},
        )
        if dataset is None:
            raise RuntimeError(
                f"Requested dataset ID {dataset_id!r} is not associated with the resolved project"
            )
        actual_id = str(get_value(dataset, "id") or "")
        actual_name = str(get_value(dataset, "name") or "")
        if actual_id != dataset_id:
            raise RuntimeError(
                f"Requested dataset ID {dataset_id!r} resolved to a different ID {actual_id!r}"
            )
        if name and actual_name and actual_name != name:
            raise RuntimeError(
                f"Requested dataset ID {dataset_id!r} resolves to {actual_name!r}, not {name!r}"
            )
    elif name:
        dataset, project_scope_resolution = call_dataset_project_scoped(
            get_dataset,
            project_id=project_id,
            project_name=project_name,
            kwargs={"name": name},
        )
    if dataset is None and create:
        rows = content or []
        dataset, project_scope_resolution = call_dataset_project_scoped(
            create_dataset,
            project_id=project_id,
            project_name=project_name,
            kwargs={"name": name, "content": rows},
        )
        status = "created"
    elif dataset is not None and update_existing and content and hasattr(dataset, "add_rows"):
        dataset.add_rows(content)
        status = "rows_appended_new_version"
    else:
        status = "exists" if dataset is not None else "missing"
    result = {
        "status": status,
        **identity(dataset),
        "project_id": project_id,
        "project_name": project_name,
        "project_scope_validated": True,
        "project_scope_resolution": project_scope_resolution,
        "rows": len(content or []),
    }
    if dataset is not None and not result.get("id"):
        raise RuntimeError("Galileo dataset response omitted its ID")
    if status == "rows_appended_new_version":
        result.update(
            {
                "reversible": False,
                "rollback": "not_supported_restore_or_delete_a_reviewed_dataset_version_manually",
            }
        )
    return result


def load_prompt_template(item: dict[str, Any]) -> Any:
    if "template" in item:
        template = item["template"]
    elif "messages" in item:
        template = item["messages"]
    elif item.get("path"):
        path = Path(str(item["path"])).expanduser()
        if path.suffix.lower() in {".json", ".jsonl", ".yaml", ".yml"}:
            data = load_structured_file(path)
            if isinstance(data, dict):
                template = data.get("template") or data.get("messages") or data
            else:
                template = data
        else:
            template = [{"role": item.get("role", "system"), "content": path.read_text(encoding="utf-8")}]
    else:
        template = [{"role": "system", "content": str(item.get("content") or "")}]

    if isinstance(template, str):
        template = [{"role": item.get("role", "system"), "content": template}]
    if not isinstance(template, list):
        return template
    try:
        from galileo import Message, MessageRole
    except Exception:
        return template
    role_map = {
        "system": getattr(MessageRole, "system", "system"),
        "user": getattr(MessageRole, "user", "user"),
        "assistant": getattr(MessageRole, "assistant", "assistant"),
    }
    messages = []
    for message in template:
        if not isinstance(message, dict):
            messages.append(message)
            continue
        role = str(message.get("role", "user")).lower()
        messages.append(Message(role=role_map.get(role, role), content=str(message.get("content", ""))))
    return messages


def ensure_prompt(item: dict[str, Any], project: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    name = str(item.get("name") or "")
    prompt_id = str(item.get("id") or "")
    project_name = str(item.get("project_name") or project.get("name") or "")
    project_id = str(item.get("project_id") or project.get("id") or "")
    create = bool(item.get("create", True))
    if not name and not prompt_id:
        raise RuntimeError("Prompt name or id is required")
    if dry_run:
        return {"status": "planned", "id": prompt_id, "name": name}
    from galileo.prompts import create_prompt, get_prompt

    prompt = None
    if prompt_id:
        prompt = call_with_retries(
            get_prompt,
            [{"id": prompt_id, "project_id": project_id}, {"id": prompt_id}, {"name": name}],
        )
    if prompt is None and name:
        prompt = call_with_retries(
            get_prompt,
            [
                {"name": name, "project_id": project_id},
                {"name": name, "project_name": project_name},
                {"name": name},
            ],
        )
    if prompt is None and create:
        template = load_prompt_template(item)
        prompt = call_with_retries(
            create_prompt,
            [
                {"name": name, "template": template, "project_id": project_id},
                {"name": name, "template": template, "project_name": project_name},
                {"name": name, "template": template},
            ],
        )
        status = "created"
    else:
        status = "exists" if prompt is not None else "missing"
    return {"status": status, **identity(prompt)}


def resolve_metrics(metric_names: list[str]) -> list[Any]:
    try:
        from galileo import GalileoMetrics
    except Exception:
        return metric_names
    resolved: list[Any] = []
    for name in metric_names:
        attr = name.strip().replace("-", "_").replace(" ", "_")
        resolved.append(getattr(GalileoMetrics, attr, name))
    return resolved


def require_experiment_group_sdk() -> None:
    try:
        installed = version("galileo")
    except PackageNotFoundError as exc:
        raise RuntimeError(
            "Experiment groups require the Galileo Python SDK >= 2.2.0"
        ) from exc
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)(.*)$", installed)
    if not match:
        raise RuntimeError(f"Cannot parse installed Galileo SDK version {installed!r}")
    normalized = tuple(int(match.group(index)) for index in (1, 2, 3))
    suffix = match.group(4).lower()
    public_suffix = suffix.split("+", 1)[0]
    minimum_prerelease = normalized == (2, 2, 0) and any(
        marker in public_suffix for marker in ("a", "b", "rc", "dev")
    )
    if normalized < (2, 2, 0) or minimum_prerelease:
        raise RuntimeError(
            f"Experiment groups require the Galileo Python SDK >= 2.2.0; found {installed}"
        )


def ensure_experiment(item: dict[str, Any], project: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    name = str(item.get("name") or item.get("experiment_name") or "")
    mode = str(item.get("mode") or "create_only")
    project_name = str(item.get("project_name") or project.get("name") or "")
    project_id = str(item.get("project_id") or project.get("id") or "")
    experiment_group = str(item.get("experiment_group") or "")
    experiment_group_id = str(item.get("experiment_group_id") or "")
    group_request = {
        "experiment_group": experiment_group,
        "experiment_group_id": experiment_group_id,
    }
    if not name:
        raise RuntimeError("Experiment name is required")
    if dry_run:
        return {
            "status": "planned",
            "name": name,
            "mode": mode,
            **{key: value for key, value in group_request.items() if value},
        }
    if experiment_group or experiment_group_id:
        require_experiment_group_sdk()
    if mode == "run":
        require_cleanup_owned_project(project, "an experiment run")
        from galileo.datasets import get_dataset
        from galileo.experiments import run_experiment
        from galileo.prompts import get_prompt

        dataset_name = str(item.get("dataset_name") or "")
        prompt_name = str(item.get("prompt_name") or "")
        dataset = item.get("dataset")
        dataset_project_scope_resolution = "provided_inline"
        if dataset is None and dataset_name:
            dataset, dataset_project_scope_resolution = call_dataset_project_scoped(
                get_dataset,
                project_id=project_id,
                project_name=project_name,
                kwargs={"name": dataset_name},
            )
        prompt = (
            call_with_retries(
                get_prompt,
                [
                    {"name": prompt_name, "project_id": project_id},
                    {"name": prompt_name, "project_name": project_name},
                ],
            )
            if prompt_name
            else None
        )
        metrics = resolve_metrics(parse_metrics(item.get("metrics")))
        variants: list[dict[str, Any]] = []
        if project_id:
            variants.append(
                {
                    "experiment_name": name,
                    "dataset": dataset,
                    "prompt_template": prompt,
                    "prompt_settings": item.get("prompt_settings"),
                    "metrics": metrics,
                    "experiment_tags": item.get("tags") or item.get("experiment_tags"),
                    **group_request,
                    "project_id": project_id,
                }
            )
        if project_name:
            variants.append(
                {
                    "experiment_name": name,
                    "dataset": dataset,
                    "prompt_template": prompt,
                    "prompt_settings": item.get("prompt_settings"),
                    "metrics": metrics,
                    "experiment_tags": item.get("tags") or item.get("experiment_tags"),
                    **group_request,
                    "project": project_name,
                }
            )
        result, experiment_project_scope_resolution = call_experiment_project_scoped(
            run_experiment,
            project_id=project_id,
            project_name=project_name,
            variants=variants,
        )
        return {
            "status": "ran",
            **identity(result),
            "name": name,
            "dataset_project_scope_resolution": dataset_project_scope_resolution,
            "experiment_project_scope_resolution": experiment_project_scope_resolution,
            **{key: value for key, value in group_request.items() if value},
        }

    from galileo.experiments import create_experiment, get_experiment, get_experiments

    get_variants = []
    create_variants = []
    if project_id:
        get_variants.append({"experiment_name": name, "project_id": project_id})
        create_variants.append(
            {"experiment_name": name, "project_id": project_id, **group_request}
        )
    if project_name:
        get_variants.append({"experiment_name": name, "project_name": project_name})
        create_variants.append(
            {"experiment_name": name, "project_name": project_name, **group_request}
        )
    experiment, experiment_project_scope_resolution = call_experiment_project_scoped(
        get_experiment,
        project_id=project_id,
        project_name=project_name,
        variants=get_variants,
    )
    if experiment is not None:
        group_verified = False
        if experiment_group or experiment_group_id:
            group_variants: list[dict[str, Any]] = []
            if project_id:
                group_variants.append({"project_id": project_id, **group_request})
            if project_name:
                group_variants.append({"project_name": project_name, **group_request})
            grouped, group_project_scope_resolution = call_experiment_project_scoped(
                get_experiments,
                project_id=project_id,
                project_name=project_name,
                variants=group_variants,
            )
            grouped = grouped or []
            requested_id = str(get_value(experiment, "id") or "")
            group_verified = experiment_group_contains(
                grouped,
                experiment_id=requested_id,
                experiment_name=name,
            )
            if not group_verified:
                requested = experiment_group_id or experiment_group
                raise RuntimeError(
                    f"Existing experiment {name!r} is not in requested group {requested!r}; "
                    "move it through a reviewed group-update workflow"
                )
        return {
            "status": "exists",
            **identity(experiment),
            "name": name,
            "experiment_group_verified": group_verified,
            "experiment_project_scope_resolution": experiment_project_scope_resolution,
            "experiment_group_scope_resolution": (
                group_project_scope_resolution
                if experiment_group or experiment_group_id
                else "not_requested"
            ),
            **{key: value for key, value in group_request.items() if value},
        }

    require_cleanup_owned_project(project, "an experiment")
    experiment, experiment_project_scope_resolution = call_experiment_project_scoped(
        create_experiment,
        project_id=project_id,
        project_name=project_name,
        variants=create_variants,
    )
    result = {
        "status": "created",
        **identity(experiment),
        "name": name,
        "experiment_project_scope_resolution": experiment_project_scope_resolution,
        **{key: value for key, value in group_request.items() if value},
    }
    if experiment_group or experiment_group_id:
        group_variants = []
        if project_id:
            group_variants.append({"project_id": project_id, **group_request})
        if project_name:
            group_variants.append({"project_name": project_name, **group_request})
        grouped, group_project_scope_resolution = call_experiment_project_scoped(
            get_experiments,
            project_id=project_id,
            project_name=project_name,
            variants=group_variants,
        )
        grouped = grouped or []
        created_id = str(result.get("id") or "")
        group_verified = experiment_group_contains(
            grouped,
            experiment_id=created_id,
            experiment_name=name,
        )
        if not group_verified:
            requested = experiment_group_id or experiment_group
            raise RuntimeError(
                f"Created experiment {name!r} was not found in requested group "
                f"{requested!r}; the owned disposable project must be cleaned"
            )
        result.update(
            {
                "experiment_group_verified": True,
                "experiment_group_scope_resolution": group_project_scope_resolution,
            }
        )
    return result


def ensure_protect_stage(item: dict[str, Any], project: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    name = str(item.get("name") or item.get("stage_name") or "")
    create = bool(item.get("create", False))
    stage_id = str(item.get("id") or item.get("stage_id") or "")
    project_id = str(item.get("project_id") or project.get("id") or "")
    project_name = str(item.get("project_name") or project.get("name") or "")
    if not create:
        return {"status": "skipped", "name": name, "reason": "create=false"}
    if dry_run:
        return {"status": "planned", "id": stage_id, "name": name, "project_id": project_id}
    try:
        from galileo.stages import create_protect_stage, get_protect_stage
    except (ImportError, ModuleNotFoundError):
        create_protect_stage = None
        get_protect_stage = None
    if create_protect_stage is not None and get_protect_stage is not None:
        get_variants = []
        if stage_id and project_id:
            get_variants.append({"stage_id": stage_id, "project_id": project_id})
        if name and project_id:
            get_variants.append({"stage_name": name, "project_id": project_id})
        if name and project_name:
            get_variants.append({"stage_name": name, "project_name": project_name})
        stage = call_with_retries(get_protect_stage, get_variants)
        if stage is not None:
            return {"status": "exists", **identity(stage), "name": name, "project_id": project_id}
        require_cleanup_owned_project(project, "a Protect stage")
        create_variants = []
        if project_id:
            create_variants.append(
                {
                    "project_id": project_id,
                    "name": name,
                    "pause": bool(item.get("pause", False)),
                    "description": item.get("description"),
                    "prioritized_rulesets": item.get("prioritized_rulesets"),
                }
            )
        if project_name:
            create_variants.append(
                {
                    "project_name": project_name,
                    "name": name,
                    "pause": bool(item.get("pause", False)),
                    "description": item.get("description"),
                    "prioritized_rulesets": item.get("prioritized_rulesets"),
                }
            )
        stage = call_with_retries(create_protect_stage, create_variants)
        return {"status": "created", **identity(stage), "name": name, "project_id": project_id}

    require_cleanup_owned_project(project, "a Protect stage")
    try:
        import galileo_protect as gp
    except ModuleNotFoundError as exc:
        raise RuntimeError("galileo.stages or galileo-protect is required to create Protect stages") from exc
    if not project_id and project_name:
        protect_project = gp.create_project(project_name)
        project_id = str(get_value(protect_project, "id") or "")
    stage = gp.create_stage(name=name, project_id=project_id)
    return {"status": "created", **identity(stage), "name": name, "project_id": project_id}


def resolve_agent_control_target(item: dict[str, Any], project: dict[str, Any], log_stream: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    target_type = str(item.get("target_type") or "log_stream")
    target_id = str(item.get("target_id") or "")
    log_stream_id = str(item.get("log_stream_id") or log_stream.get("id") or "")
    project_id = str(item.get("project_id") or project.get("id") or "")
    if dry_run:
        return {
            "status": "planned",
            "target_type": target_type,
            "target_id": target_id,
            "log_stream_id": log_stream_id,
            "project_id": project_id,
        }
    from galileo.agent_control import get_agent_control_target

    target = get_agent_control_target(
        target_type=target_type,
        target_id=target_id or None,
        log_stream_id=log_stream_id or None,
        project_id=project_id or None,
    )
    return {
        "status": "resolved",
        "target_type": get_value(target, "target_type") or target_type,
        "target_id": get_value(target, "target_id") or target_id,
        "project_id": get_value(target, "project_id") or project_id,
    }


def run_step(name: str, results: dict[str, Any], fn: Callable[[], Any]) -> Any:
    try:
        value = fn()
    except Exception as exc:
        results[name] = {"status": "error", "error": str(exc)}
        raise
    results[name] = value[0] if isinstance(value, tuple) else value
    return value


def _write_json_atomic(path: Path, payload: dict[str, Any], *, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if private:
        temporary.chmod(0o600)
    os.replace(temporary, path)


def ownership_ledger_path(args: argparse.Namespace) -> Path:
    if args.ownership_ledger:
        return Path(args.ownership_ledger).expanduser()
    output = Path(args.output).expanduser()
    return output.with_name(output.name + ".ownership.json")


def initialize_ownership_ledger(path: Path) -> dict[str, Any]:
    if path.exists():
        existing = load_structured_file(path)
        if not isinstance(existing, dict):
            raise RuntimeError(f"Existing ownership ledger is not a JSON object: {path}")
        active = [
            item
            for item in existing.get("created_objects", [])
            if isinstance(item, dict) and item.get("cleanup_status", "pending") == "pending"
        ]
        if active:
            raise RuntimeError(
                f"Ownership ledger has {len(active)} uncleaned object(s); run --cleanup-created "
                f"with --ownership-ledger {path} before reusing it"
            )
    ledger = {
        "api_version": "galileo-platform-setup/object-lifecycle-ownership/v1",
        "created_by": "galileo_object_lifecycle.py",
        "operation_id": str(uuid.uuid4()),
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "secret_values_rendered": False,
        "status": "active",
        "created_objects": [],
    }
    _write_json_atomic(path, ledger, private=True)
    return ledger


def record_created_object(
    ledger: dict[str, Any],
    path: Path,
    *,
    kind: str,
    result: dict[str, Any],
    project_id: str = "",
) -> None:
    if result.get("status") not in {"created", "ran"}:
        return
    object_id = str(result.get("id") or "")
    if not object_id:
        raise RuntimeError(f"Created Galileo {kind} response omitted its ID; cleanup cannot be proven")
    entry = {
        "kind": kind,
        "id": object_id,
        "name": str(result.get("name") or ""),
        "project_id": object_id if kind == "project" else project_id,
        "cleanup_status": "pending",
    }
    ledger["created_objects"].append(entry)
    _write_json_atomic(path, ledger, private=True)


def _validated_exact_id(value: Any, label: str) -> str:
    raw = str(value or "")
    try:
        parsed = uuid.UUID(raw)
    except (ValueError, TypeError, AttributeError) as exc:
        raise RuntimeError(f"{label} must be an exact UUID, got {raw!r}") from exc
    if str(parsed) != raw.lower():
        raise RuntimeError(f"{label} must be a canonical exact UUID, got {raw!r}")
    return raw


def cleanup_created_objects(
    ledger_path: Path,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    loaded = load_structured_file(ledger_path)
    if not isinstance(loaded, dict):
        raise RuntimeError("Ownership ledger must be a JSON object")
    if loaded.get("api_version") != "galileo-platform-setup/object-lifecycle-ownership/v1":
        raise RuntimeError("Ownership ledger has an unsupported api_version")
    if loaded.get("created_by") != "galileo_object_lifecycle.py":
        raise RuntimeError("Ownership ledger does not identify the lifecycle helper as its creator")
    try:
        uuid.UUID(str(loaded.get("operation_id") or ""))
    except (ValueError, TypeError, AttributeError) as exc:
        raise RuntimeError("Ownership ledger operation_id is invalid") from exc
    entries = loaded.get("created_objects")
    if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
        raise RuntimeError("Ownership ledger created_objects must be a list of objects")

    known_kinds = {"project", "log_stream", "dataset", "prompt", "experiment", "protect_stage"}
    pending: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        kind = str(entry.get("kind") or "")
        if kind not in known_kinds:
            raise RuntimeError(f"Ownership ledger contains unsupported object kind {kind!r}")
        object_id = _validated_exact_id(entry.get("id"), f"{kind} ID")
        key = (kind, object_id)
        if key in seen:
            raise RuntimeError(f"Ownership ledger contains duplicate exact ID {kind}:{object_id}")
        seen.add(key)
        if entry.get("cleanup_status", "pending") == "pending":
            pending.append(entry)

    owned_project_ids = {
        _validated_exact_id(entry.get("id"), "project ID")
        for entry in pending
        if entry.get("kind") == "project"
    }
    for entry in pending:
        kind = str(entry["kind"])
        if kind == "project":
            continue
        project_id = _validated_exact_id(entry.get("project_id"), f"{kind} project ID")
        if kind not in {"dataset", "prompt"} and project_id not in owned_project_ids:
            raise RuntimeError(
                f"Cannot safely clean {kind} {entry['id']}: its project was not created by this ledger"
            )

    actions = [
        {
            "kind": entry["kind"],
            "id": entry["id"],
            "project_id": entry.get("project_id", ""),
            "status": "planned" if dry_run else "pending",
        }
        for entry in pending
    ]
    if dry_run:
        return {
            "status": "planned",
            "operation_id": loaded["operation_id"],
            "exact_id_only": True,
            "objects": actions,
        }
    if not pending:
        return {
            "status": "already_clean",
            "operation_id": loaded["operation_id"],
            "exact_id_only": True,
            "objects": [],
        }

    from galileo.datasets import delete_dataset, get_dataset
    from galileo.projects import delete_project
    from galileo.prompts import delete_prompt, get_prompt

    def get_dataset_for_cleanup(object_id: str, project_id: str) -> tuple[Any, str]:
        try:
            return call_dataset_project_scoped(
                get_dataset,
                project_id=project_id,
                project_name="",
                kwargs={"id": object_id},
            )
        except Exception as exc:
            if not _is_exact_not_found_error(exc):
                raise
            return None, "sdk_http_404_exact_id_absence"

    def get_prompt_for_cleanup(object_id: str) -> Any:
        try:
            return get_prompt(id=object_id)
        except Exception as exc:
            if not _is_exact_not_found_error(exc):
                raise
            return None

    action_by_key = {(item["kind"], item["id"]): item for item in actions}
    for entry in pending:
        if entry["kind"] != "dataset":
            continue
        object_id = str(entry["id"])
        project_id = str(entry["project_id"])
        existing, lookup_source = get_dataset_for_cleanup(object_id, project_id)
        if existing is None:
            cleanup_status = "already_absent_verified"
            deletion_source = lookup_source
        else:
            _deleted, deletion_source = call_dataset_project_scoped(
                delete_dataset,
                project_id=project_id,
                project_name="",
                kwargs={"id": object_id},
            )
            remaining, _verification_source = get_dataset_for_cleanup(
                object_id, project_id
            )
            if remaining is not None:
                raise RuntimeError(
                    f"Exact dataset ID {object_id} still exists after deletion; "
                    "ownership ledger remains pending"
                )
            cleanup_status = "deleted_by_exact_id"
        entry["cleanup_status"] = cleanup_status
        entry["cleanup_source"] = deletion_source
        entry["cleaned_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        action_by_key[("dataset", object_id)]["status"] = cleanup_status
        action_by_key[("dataset", object_id)]["source"] = deletion_source
        _write_json_atomic(ledger_path, loaded, private=True)

    for entry in pending:
        if entry["kind"] != "prompt":
            continue
        object_id = str(entry["id"])
        if get_prompt_for_cleanup(object_id) is None:
            cleanup_status = "already_absent_verified"
        else:
            delete_prompt(id=object_id)
            if get_prompt_for_cleanup(object_id) is not None:
                raise RuntimeError(
                    f"Exact prompt ID {object_id} still exists after deletion; "
                    "ownership ledger remains pending"
                )
            cleanup_status = "deleted_by_exact_id"
        entry["cleanup_status"] = cleanup_status
        entry["cleanup_source"] = "sdk"
        entry["cleaned_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        action_by_key[("prompt", object_id)]["status"] = cleanup_status
        action_by_key[("prompt", object_id)]["source"] = "sdk"
        _write_json_atomic(ledger_path, loaded, private=True)

    for entry in pending:
        if entry["kind"] != "project":
            continue
        project_id = str(entry["id"])
        deletion_source = delete_project_compat(delete_project, project_id=project_id)
        project_cleanup_status = (
            "already_absent_verified"
            if deletion_source == "already_absent_verified"
            else "deleted_by_exact_id"
        )
        entry["cleanup_status"] = project_cleanup_status
        entry["cleanup_source"] = deletion_source
        entry["cleaned_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        action_by_key[("project", project_id)]["status"] = project_cleanup_status
        action_by_key[("project", project_id)]["source"] = deletion_source
        for child in pending:
            if child["kind"] in {"project", "dataset", "prompt"} or child.get("project_id") != project_id:
                continue
            child["cleanup_status"] = "covered_by_exact_project_delete"
            child["cleaned_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            action_by_key[(str(child["kind"]), str(child["id"]))][
                "status"
            ] = "covered_by_exact_project_delete"
        _write_json_atomic(ledger_path, loaded, private=True)

    remaining = [
        entry
        for entry in entries
        if entry.get("cleanup_status", "pending") == "pending"
    ]
    if remaining:
        raise RuntimeError(
            f"Cleanup left {len(remaining)} object(s) pending; ledger retained for reviewed recovery"
        )
    loaded["status"] = "cleaned"
    loaded["cleaned_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    _write_json_atomic(ledger_path, loaded, private=True)
    return {
        "status": "cleaned",
        "operation_id": loaded["operation_id"],
        "exact_id_only": True,
        "objects": actions,
    }


def _skipped_children(config: dict[str, Any], reason: str) -> dict[str, list[dict[str, Any]]]:
    return {
        key: [
            {
                "status": "skipped",
                "name": str(item.get("name") or ""),
                "reason": reason,
            }
            for item in config.get(key, [])
        ]
        for key in (
            "datasets",
            "prompts",
            "experiments",
            "protect_stages",
            "agent_control_targets",
        )
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = merge_inputs(args)
    ledger_path = ownership_ledger_path(args)
    if not args.dry_run:
        configure_environment(args, config)
        require_galileo_sdk()

    if args.cleanup_created:
        cleanup_result: dict[str, Any] = {
            "api_version": "galileo-platform-setup/object-lifecycle-cleanup-result/v1",
            "secret_values_rendered": False,
            "dry_run": args.dry_run,
            "ownership_ledger": str(ledger_path),
        }
        try:
            cleanup_result["cleanup"] = cleanup_created_objects(
                ledger_path,
                dry_run=args.dry_run,
            )
            cleanup_result["status"] = "ok"
            return_code = 0
        except Exception as exc:
            cleanup_result["cleanup"] = {"status": "error", "error": str(exc)}
            cleanup_result["status"] = "error"
            return_code = 1
        output = Path(args.output).expanduser()
        _write_json_atomic(output, cleanup_result)
        print(json.dumps(cleanup_result, indent=2, sort_keys=True))
        return return_code

    results: dict[str, Any] = {
        "api_version": "galileo-platform-setup/object-lifecycle-result/v1",
        "secret_values_rendered": False,
        "dry_run": args.dry_run,
        "project": {},
        "log_stream": {},
        "metrics": {},
        "datasets": [],
        "prompts": [],
        "experiments": [],
        "protect_stages": [],
        "agent_control_targets": [],
        "ownership_ledger": str(ledger_path) if not args.dry_run else "not_written_in_dry_run",
    }
    errors: list[str] = []
    ledger: dict[str, Any] | None = None
    if not args.dry_run:
        try:
            ledger = initialize_ownership_ledger(ledger_path)
        except Exception as exc:
            errors.append(f"ownership_ledger: {exc}")

    project_obj = None
    log_stream_obj = None
    setup_ok = not errors
    if setup_ok:
        try:
            project_result, project_obj = ensure_project(config, args.dry_run)
            results["project"] = project_result
            if not args.dry_run and project_result.get("status") == "missing":
                raise RuntimeError("Project is missing and create=false")
            config["project"]["_created_by_operation"] = (
                project_result.get("status") == "created"
            )
            if project_result.get("id"):
                config["project"]["id"] = project_result["id"]
            if ledger is not None:
                record_created_object(
                    ledger,
                    ledger_path,
                    kind="project",
                    result=project_result,
                )
        except Exception as exc:
            errors.append(f"project: {exc}")
            setup_ok = False

    if setup_ok:
        try:
            log_stream_result, log_stream_obj = ensure_log_stream(
                config, project_obj, args.dry_run
            )
            results["log_stream"] = log_stream_result
            if not args.dry_run and log_stream_result.get("status") == "missing":
                raise RuntimeError("Log stream is missing and create=false")
            if log_stream_result.get("id"):
                config["log_stream"]["id"] = log_stream_result["id"]
            config["log_stream"]["_created_by_operation"] = (
                log_stream_result.get("status") == "created"
            )
            if ledger is not None:
                record_created_object(
                    ledger,
                    ledger_path,
                    kind="log_stream",
                    result=log_stream_result,
                    project_id=str(config["project"].get("id") or ""),
                )
        except Exception as exc:
            errors.append(f"log_stream: {exc}")
            setup_ok = False
    else:
        results["log_stream"] = {
            "status": "skipped",
            "reason": "project setup failed",
        }

    if setup_ok:
        try:
            results["metrics"] = enable_log_stream_metrics(config, log_stream_obj, args.dry_run)
        except Exception as exc:
            errors.append(f"metrics: {exc}")
    else:
        results["metrics"] = {
            "status": "skipped",
            "reason": "project or log-stream setup failed",
        }

    if setup_ok:
        for collection, key, kind, handler in [
            (
                results["datasets"],
                "datasets",
                "dataset",
                lambda item, dry: ensure_dataset(item, config["project"], dry),
            ),
            (
                results["prompts"],
                "prompts",
                "prompt",
                lambda item, dry: ensure_prompt(item, config["project"], dry),
            ),
            (
                results["experiments"],
                "experiments",
                "experiment",
                lambda item, dry: ensure_experiment(item, config["project"], dry),
            ),
            (
                results["protect_stages"],
                "protect_stages",
                "protect_stage",
                lambda item, dry: ensure_protect_stage(item, config["project"], dry),
            ),
            (
                results["agent_control_targets"],
                "agent_control_targets",
                "agent_control_target",
                lambda item, dry: resolve_agent_control_target(
                    item, config["project"], config["log_stream"], dry
                ),
            ),
        ]:
            for item in config.get(key, []):
                try:
                    item_result = handler(item, args.dry_run)
                    collection.append(item_result)
                    if ledger is not None and kind != "agent_control_target":
                        record_created_object(
                            ledger,
                            ledger_path,
                            kind=kind,
                            result=item_result,
                            project_id=str(config["project"].get("id") or ""),
                        )
                except Exception as exc:
                    collection.append(
                        {"status": "error", "name": item.get("name"), "error": str(exc)}
                    )
                    errors.append(f"{key}: {exc}")
    else:
        skipped = _skipped_children(config, "project or log-stream setup failed")
        for key, value in skipped.items():
            results[key] = value

    results["status"] = "error" if errors else "ok"
    results["errors"] = errors
    if ledger is not None:
        ledger["status"] = "partial_error" if errors else "complete"
        ledger["completed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        _write_json_atomic(ledger_path, ledger, private=True)

    output = Path(args.output).expanduser()
    _write_json_atomic(output, results)
    print(json.dumps(results, indent=2, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
