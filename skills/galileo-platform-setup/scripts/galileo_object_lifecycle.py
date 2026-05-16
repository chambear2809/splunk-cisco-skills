#!/usr/bin/env python3
"""Create or validate Galileo platform objects from a local manifest.

The script is intentionally secret-file based. It reads the Galileo API key
from a local file, sets Galileo SDK environment variables, and writes a JSON
result without echoing secret values.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any, Callable


SUPPORTED_DATASET_SUFFIXES = {".csv", ".json", ".jsonl"}


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
    if not secret_path.is_file():
        raise SystemExit(f"ERROR: Galileo API key file is not readable: {secret_path}")
    value = secret_path.read_text(encoding="utf-8").strip()
    if not value:
        raise SystemExit(f"ERROR: Galileo API key file is empty: {secret_path}")
    return value


def configure_environment(args: argparse.Namespace, config: dict[str, Any]) -> None:
    os.environ["GALILEO_API_KEY"] = read_secret_file(args.galileo_api_key_file)
    if args.console_url:
        os.environ["GALILEO_CONSOLE_URL"] = args.console_url.rstrip("/")
    if args.api_base:
        api_base = args.api_base.rstrip("/")
        os.environ["GALILEO_API_URL"] = api_base
        os.environ["GALILEO_API_BASE"] = api_base
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
    if project_id:
        project = get_project(id=project_id)
    if project is None and name:
        project = get_project(name=name)
    if project is None and create:
        if not name:
            raise RuntimeError("Project name is required to create a project")
        project = create_project(name=name)
        status = "created"
    else:
        status = "exists" if project is not None else "missing"
    return {"status": status, **identity(project), "requested": {"id": project_id, "name": name}}, project


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
    from galileo.log_streams import create_log_stream, get_log_stream

    log_stream = None
    if log_stream_id:
        variants = [{"name": name, "project_id": project_id}, {"name": name, "project_name": project_name}]
        log_stream = call_with_retries(get_log_stream, variants) if name else None
    if log_stream is None and name:
        log_stream = call_with_retries(
            get_log_stream,
            [{"name": name, "project_id": project_id}, {"name": name, "project_name": project_name}],
        )
    if log_stream is None and create:
        if not name:
            raise RuntimeError("Log stream name is required to create a log stream")
        log_stream = call_with_retries(
            create_log_stream,
            [{"name": name, "project_id": project_id}, {"name": name, "project_name": project_name}],
        )
        status = "created"
    else:
        status = "exists" if log_stream is not None else "missing"
    return {"status": status, **identity(log_stream), "requested": {"id": log_stream_id, "name": name}}, log_stream


def enable_log_stream_metrics(config: dict[str, Any], log_stream: Any, dry_run: bool) -> dict[str, Any]:
    metrics = parse_metrics((config.get("log_stream") or {}).get("metrics"))
    if not metrics:
        return {"status": "skipped", "metrics": []}
    if dry_run:
        return {"status": "planned", "metrics": metrics}
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


def ensure_dataset(item: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    name = str(item.get("name") or "")
    dataset_id = str(item.get("id") or "")
    path = str(item.get("path") or "")
    content = item.get("content")
    create = bool(item.get("create", True))
    update_existing = bool(item.get("update_existing", False))
    if path:
        content = load_dataset_content(Path(path).expanduser())
    if not name and path:
        name = Path(path).stem
    if not name and not dataset_id:
        raise RuntimeError("Dataset name or id is required")
    if dry_run:
        return {"status": "planned", "id": dataset_id, "name": name, "rows": len(content or [])}
    from galileo.datasets import create_dataset, get_dataset

    dataset = None
    if dataset_id:
        dataset = get_dataset(id=dataset_id)
    if dataset is None and name:
        dataset = get_dataset(name=name)
    if dataset is None and create:
        rows = content or []
        dataset = create_dataset(name=name, content=rows)
        status = "created"
    elif dataset is not None and update_existing and content and hasattr(dataset, "add_rows"):
        dataset.add_rows(content)
        status = "updated"
    else:
        status = "exists" if dataset is not None else "missing"
    return {"status": status, **identity(dataset), "rows": len(content or [])}


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


def ensure_experiment(item: dict[str, Any], project: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    name = str(item.get("name") or item.get("experiment_name") or "")
    mode = str(item.get("mode") or "create_only")
    project_name = str(item.get("project_name") or project.get("name") or "")
    project_id = str(item.get("project_id") or project.get("id") or "")
    if not name:
        raise RuntimeError("Experiment name is required")
    if dry_run:
        return {"status": "planned", "name": name, "mode": mode}
    if mode == "run":
        from galileo.datasets import get_dataset
        from galileo.experiments import run_experiment
        from galileo.prompts import get_prompt

        dataset_name = str(item.get("dataset_name") or "")
        prompt_name = str(item.get("prompt_name") or "")
        dataset = item.get("dataset") or (get_dataset(name=dataset_name) if dataset_name else None)
        prompt = get_prompt(name=prompt_name) if prompt_name else None
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
                    "project": project_name,
                }
            )
        result = call_with_retries(run_experiment, variants)
        return {"status": "ran", **identity(result), "name": name}

    from galileo.experiments import create_experiment, get_experiment

    get_variants = []
    create_variants = []
    if project_id:
        get_variants.append({"experiment_name": name, "project_id": project_id})
        create_variants.append({"experiment_name": name, "project_id": project_id})
    if project_name:
        get_variants.append({"experiment_name": name, "project_name": project_name})
        create_variants.append({"experiment_name": name, "project_name": project_name})
    experiment = call_with_retries(get_experiment, get_variants)
    if experiment is not None:
        return {"status": "exists", **identity(experiment), "name": name}

    experiment = call_with_retries(create_experiment, create_variants)
    return {"status": "created", **identity(experiment), "name": name}


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


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = merge_inputs(args)
    if not args.dry_run:
        configure_environment(args, config)
        require_galileo_sdk()

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
    }
    errors: list[str] = []

    project_obj = None
    log_stream_obj = None
    try:
        project_result, project_obj = ensure_project(config, args.dry_run)
        results["project"] = project_result
        if project_result.get("id"):
            config["project"]["id"] = project_result["id"]
    except Exception as exc:
        errors.append(f"project: {exc}")

    try:
        log_stream_result, log_stream_obj = ensure_log_stream(config, project_obj, args.dry_run)
        results["log_stream"] = log_stream_result
        if log_stream_result.get("id"):
            config["log_stream"]["id"] = log_stream_result["id"]
    except Exception as exc:
        errors.append(f"log_stream: {exc}")

    if not errors:
        try:
            results["metrics"] = enable_log_stream_metrics(config, log_stream_obj, args.dry_run)
        except Exception as exc:
            errors.append(f"metrics: {exc}")

    for collection, key, handler in [
        (results["datasets"], "datasets", ensure_dataset),
        (results["prompts"], "prompts", lambda item, dry: ensure_prompt(item, config["project"], dry)),
        (results["experiments"], "experiments", lambda item, dry: ensure_experiment(item, config["project"], dry)),
        (results["protect_stages"], "protect_stages", lambda item, dry: ensure_protect_stage(item, config["project"], dry)),
        (
            results["agent_control_targets"],
            "agent_control_targets",
            lambda item, dry: resolve_agent_control_target(item, config["project"], config["log_stream"], dry),
        ),
    ]:
        for item in config.get(key, []):
            try:
                collection.append(handler(item, args.dry_run))
            except Exception as exc:
                collection.append({"status": "error", "name": item.get("name"), "error": str(exc)})
                errors.append(f"{key}: {exc}")

    results["status"] = "error" if errors else "ok"
    results["errors"] = errors

    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
