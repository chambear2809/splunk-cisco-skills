#!/usr/bin/env python3
"""Parse and optionally lint every tracked JSON and YAML configuration file."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_SUFFIXES = {".json", ".yaml", ".yml"}

# These six source files are render-time templates, not directly consumable
# YAML. They are still parsed after replacing their constrained {{TOKEN}}
# placeholders. No other tracked YAML file may use this exception.
YAML_TEMPLATE_FILES = frozenset(
    {
        "skills/splunk-connect-for-snmp-setup/templates/compose/docker-compose.yml",
        "skills/splunk-connect-for-snmp-setup/templates/kubernetes/namespace.yaml",
        "skills/splunk-connect-for-snmp-setup/templates/kubernetes/values.yaml",
        "skills/splunk-connect-for-syslog-setup/templates/host/docker-compose.yml",
        "skills/splunk-connect-for-syslog-setup/templates/kubernetes/namespace.yaml",
        "skills/splunk-connect-for-syslog-setup/templates/kubernetes/values.yaml",
    }
)
TEMPLATE_TOKEN_RE = re.compile(r"\{\{[A-Z][A-Z0-9_]*\}\}")
LEADING_TEMPLATE_TOKENS_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<tokens>(?:\{\{[A-Z][A-Z0-9_]*\}\})+)(?P<rest>.*)$"
)


class ConfigValidationError(ValueError):
    """Raised when a tracked configuration surface is invalid."""


def _git_tracked_configs() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.json", "*.yaml", "*.yml"],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.PIPE,
    )
    paths = sorted(
        item.decode("utf-8")
        for item in result.stdout.split(b"\0")
        if item
    )
    if not paths:
        raise ConfigValidationError("git reported no tracked JSON/YAML files")
    return paths


def _normalise_yaml_template(rel_path: str, text: str) -> str:
    if rel_path not in YAML_TEMPLATE_FILES:
        return text

    normalised: list[str] = []
    for source_line in text.splitlines(keepends=True):
        newline = ""
        body = source_line
        if body.endswith("\r\n"):
            body, newline = body[:-2], "\r\n"
        elif body.endswith("\n"):
            body, newline = body[:-1], "\n"

        leading_match = LEADING_TEMPLATE_TOKENS_RE.match(body)
        if leading_match:
            rest = leading_match.group("rest")
            if rest.strip() and rest[0].isspace():
                # A leading token expands to indentation or a YAML block. Keep
                # the literal suffix so its surrounding YAML shape is parsed.
                body = f"{leading_match.group('indent')}{rest}"
            elif not rest.strip():
                body = (
                    f"{leading_match.group('indent')}"
                    "# render-time YAML block placeholder"
                )

        body = TEMPLATE_TOKEN_RE.sub("__rendered_value__", body)
        normalised.append(f"{body}{newline}")

    rendered = "".join(normalised)
    if "{{" in rendered or "}}" in rendered:
        raise ConfigValidationError(
            f"{rel_path}: unsupported render-time YAML placeholder"
        )
    return rendered


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ConfigValidationError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def validate_configs(paths: list[str]) -> tuple[int, int]:
    json_count = 0
    yaml_count = 0
    errors: list[str] = []

    for rel_path in paths:
        path = REPO_ROOT / rel_path
        if not path.is_file():
            errors.append(f"{rel_path}: tracked configuration file is missing")
            continue
        try:
            text = path.read_text(encoding="utf-8")
            if path.suffix == ".json":
                json.loads(text, object_pairs_hook=_reject_duplicate_json_keys)
                json_count += 1
            else:
                text = _normalise_yaml_template(rel_path, text)
                list(yaml.safe_load_all(text))
                yaml_count += 1
        except (ConfigValidationError, json.JSONDecodeError, UnicodeError, yaml.YAMLError) as exc:
            errors.append(f"{rel_path}: {exc}")

    if errors:
        details = "\n".join(f"  - {error}" for error in errors)
        raise ConfigValidationError(
            f"tracked configuration validation failed:\n{details}"
        )
    return json_count, yaml_count


def lint_yaml(paths: list[str]) -> None:
    executable = shutil.which("yamllint")
    if executable is None:
        raise ConfigValidationError(
            "yamllint is required for --yamllint; install requirements-dev.txt"
        )
    yaml_paths = [
        rel_path
        for rel_path in paths
        if Path(rel_path).suffix in {".yaml", ".yml"}
    ]
    subprocess.run(
        [executable, "-c", ".yamllint.yml", *yaml_paths],
        cwd=REPO_ROOT,
        check=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yamllint",
        action="store_true",
        help="also run yamllint against every tracked YAML/YML file",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        paths = _git_tracked_configs()
        json_count, yaml_count = validate_configs(paths)
        if args.yamllint:
            lint_yaml(paths)
    except (ConfigValidationError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    suffix = " and YAML lint passed" if args.yamllint else ""
    print(
        f"Validated {json_count} tracked JSON files and "
        f"{yaml_count} tracked YAML/YML files{suffix}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
