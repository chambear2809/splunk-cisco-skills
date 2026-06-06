#!/usr/bin/env python3
"""Small deterministic renderer for render-first app/readiness skills."""

from __future__ import annotations

import argparse
import json
import re
import stat
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
EXACT_PLACEHOLDER_RE = re.compile(r"^\{\{([A-Za-z0-9_]+)\}\}$")


def add_config_arguments(parser: argparse.ArgumentParser, config: dict[str, Any]) -> None:
    for item in config.get("arguments", []):
        kwargs = {
            "default": item.get("default"),
            "help": item.get("help", ""),
        }
        if item.get("choices"):
            kwargs["choices"] = item["choices"]
        if item.get("action"):
            kwargs.pop("default", None)
            kwargs["action"] = item["action"]
        parser.add_argument(item["flag"], **kwargs)


def parse_args(config: dict[str, Any]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=str(config["description"]))
    parser.add_argument("--phase", choices=("render", "list"), default="render")
    parser.add_argument("--output-dir", default=str(REPO_ROOT / config["default_output_dir"]))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    add_config_arguments(parser, config)
    return parser.parse_args()


def render_template(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str):
        exact_match = EXACT_PLACEHOLDER_RE.match(value)
        if exact_match and exact_match.group(1) in context:
            return context[exact_match.group(1)]
        rendered = value
        for key, replacement in sorted(context.items(), key=lambda item: len(item[0]), reverse=True):
            if isinstance(replacement, (list, tuple)):
                text = ", ".join(str(item) for item in replacement)
            elif isinstance(replacement, bool):
                text = "true" if replacement else "false"
            else:
                text = str(replacement)
            rendered = rendered.replace("{{" + key + "}}", text)
        return rendered
    if isinstance(value, list):
        return [render_template(item, context) for item in value]
    if isinstance(value, dict):
        return {key: render_template(item, context) for key, item in value.items()}
    return value


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def context_from_args(config: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    context = {
        "skill_name": config["skill_name"],
        "profile_dir": config["profile_dir"],
        "title": config["title"],
        "primary_app_name": config.get("primary_app_name", "N/A"),
        "primary_splunkbase_id": config.get("primary_splunkbase_id", "N/A"),
    }
    context.update(vars(args))
    for item in config.get("computed_context", []):
        values = [str(context.get(field, "")) for field in item.get("fields", [])]
        context[item["name"]] = item.get("separator", ",").join(values)
    for field in config.get("csv_context_fields", []):
        context[f"{field}_list"] = [
            item.strip()
            for item in str(context.get(field, "")).split(",")
            if item.strip()
        ]
    for item in config.get("choice_context", []):
        field = item["field"]
        selected = str(context.get(field, ""))
        mapped = item.get("mapping", {}).get(selected, item.get("default", {}))
        if isinstance(mapped, dict):
            context.update(mapped)
    return context


def render_assets(config: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    context = context_from_args(config, args)
    output_root = Path(args.output_dir).expanduser().resolve()
    profile_dir = output_root / config["profile_dir"]
    file_specs = [
        ("metadata.json", None, False),
        ("profile-plan.md", config["plan_md"], False),
        ("handoffs.md", config["handoffs_md"], False),
        ("install-commands.sh", config["install_commands"], True),
        ("validation-searches.spl", config["validation_searches"], False),
        ("readiness-evidence-template.json", None, False),
    ]
    for file_spec in config.get("additional_files", []):
        file_specs.append((file_spec["path"], file_spec["content"], bool(file_spec.get("executable"))))

    files = sorted(path for path, _content, _executable in file_specs)
    if args.dry_run:
        return {"ok": True, "dry_run": True, "output_dir": str(profile_dir), "files": files}

    metadata = render_template(config.get("metadata", {}), context)
    metadata.update(
        {
            "skill_name": config["skill_name"],
            "title": config["title"],
            "render_args": {
                key: value
                for key, value in vars(args).items()
                if key not in {"json", "dry_run", "phase", "output_dir"}
            },
        }
    )
    evidence = render_template(config["readiness_evidence"], context)

    for rel_path, content, executable in file_specs:
        path = profile_dir / rel_path
        if rel_path == "metadata.json":
            write_file(path, json.dumps(metadata, indent=2, sort_keys=True), executable)
        elif rel_path == "readiness-evidence-template.json":
            write_file(path, json.dumps(evidence, indent=2, sort_keys=True), executable)
        else:
            write_file(path, str(render_template(content, context)), executable)

    return {
        "ok": True,
        "dry_run": False,
        "output_dir": str(profile_dir),
        "files": sorted(path.name for path in profile_dir.iterdir() if path.is_file()),
    }


def emit(payload: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(f"Output: {payload['output_dir']}")
    print("Files: " + ", ".join(payload.get("files", [])))


def main(config: dict[str, Any]) -> int:
    args = parse_args(config)
    if args.phase == "list":
        emit(
            {
                "ok": True,
                "skill_name": config["skill_name"],
                "title": config["title"],
                "primary_app_name": config.get("primary_app_name"),
                "primary_splunkbase_id": config.get("primary_splunkbase_id"),
                "arguments": config.get("arguments", []),
                "source_types": config.get("source_types", []),
                "handoff_skills": config.get("handoff_skills", []),
            },
            args.json,
        )
        return 0
    emit(render_assets(config, args), args.json)
    return 0
