"""Small YAML compatibility helpers for render-only skill scripts.

PyYAML is preferred when it is installed. The fallback intentionally supports
the conservative YAML subset used by this repository's templates and rendered
assets: nested mappings, lists, booleans, numbers, quoted/plain strings, inline
empty lists, and literal block strings.
"""

from __future__ import annotations

import json
import re
from typing import Any


class YamlCompatError(ValueError):
    """Raised when neither JSON nor the supported YAML subset can be parsed."""


def load_yaml_or_json(text: str, *, source: str = "<string>") -> Any:
    """Load JSON first, then YAML with PyYAML or the local fallback parser."""

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    yaml = None
    try:
        import yaml as _yaml  # type: ignore[import-not-found]
        yaml = _yaml
    except ModuleNotFoundError:
        pass

    if yaml is None:
        return _SimpleYamlParser(text, source=source).parse()

    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise YamlCompatError(f"Failed to parse YAML {source}: {exc}") from exc


def dump_yaml(payload: Any, *, sort_keys: bool = True) -> str:
    """Dump YAML with PyYAML when available, otherwise use the local emitter."""

    try:
        import yaml  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        return _dump_node(payload, indent=0, sort_keys=sort_keys).rstrip() + "\n"
    return yaml.safe_dump(payload, sort_keys=sort_keys, default_flow_style=False)


class _SimpleYamlParser:
    def __init__(self, text: str, *, source: str) -> None:
        self.source = source
        self.lines = self._prepare(text)

    def parse(self) -> Any:
        if not self.lines:
            return None
        value, index = self._parse_block(0, self.lines[0][0])
        if index != len(self.lines):
            raise YamlCompatError(f"Unexpected trailing content in {self.source}")
        return value

    def _prepare(self, text: str) -> list[tuple[int, str]]:
        prepared: list[tuple[int, str]] = []
        for line_no, raw in enumerate(text.splitlines(), start=1):
            if "\t" in raw[: len(raw) - len(raw.lstrip())]:
                raise YamlCompatError(f"Tabs are not supported in YAML indentation at {self.source}:{line_no}")
            stripped = _strip_comment(raw).rstrip()
            if not stripped.strip():
                continue
            indent = len(stripped) - len(stripped.lstrip(" "))
            prepared.append((indent, stripped[indent:]))
        return prepared

    def _parse_block(self, index: int, indent: int) -> tuple[Any, int]:
        if index >= len(self.lines):
            return None, index
        current_indent, content = self.lines[index]
        if current_indent < indent:
            return None, index
        if current_indent != indent:
            raise YamlCompatError(
                f"Unexpected indentation in {self.source}: expected {indent}, got {current_indent}"
            )
        if content == "-" or content.startswith("- "):
            return self._parse_list(index, indent)
        return self._parse_mapping(index, indent)

    def _parse_mapping(self, index: int, indent: int) -> tuple[dict[str, Any], int]:
        mapping: dict[str, Any] = {}
        while index < len(self.lines):
            current_indent, content = self.lines[index]
            if current_indent < indent:
                break
            if current_indent != indent or content == "-" or content.startswith("- "):
                break
            key, raw_value = _split_key_value(content, self.source)
            index += 1
            if raw_value == "":
                if index < len(self.lines) and self.lines[index][0] > indent:
                    value, index = self._parse_block(index, self.lines[index][0])
                else:
                    value = {}
            elif raw_value in {"|", "|-", "|+", ">", ">-", ">+"}:
                value, index = self._parse_block_scalar(index, indent)
            else:
                value = _parse_scalar(raw_value)
            mapping[key] = value
        return mapping, index

    def _parse_list(self, index: int, indent: int) -> tuple[list[Any], int]:
        items: list[Any] = []
        while index < len(self.lines):
            current_indent, content = self.lines[index]
            if current_indent < indent:
                break
            if current_indent != indent or not (content == "-" or content.startswith("- ")):
                break
            raw_item = "" if content == "-" else content[2:].strip()
            index += 1
            if raw_item == "":
                if index < len(self.lines) and self.lines[index][0] > indent:
                    item, index = self._parse_block(index, self.lines[index][0])
                else:
                    item = None
            elif _looks_like_mapping_item(raw_item):
                key, raw_value = _split_key_value(raw_item, self.source)
                item = {key: _parse_scalar(raw_value) if raw_value else {}}
                if index < len(self.lines) and self.lines[index][0] > indent:
                    extra, index = self._parse_block(index, self.lines[index][0])
                    if isinstance(extra, dict):
                        item = _deep_merge(item, extra)
                    else:
                        raise YamlCompatError(f"Mixed list item structure is not supported in {self.source}")
            else:
                item = _parse_scalar(raw_item)
            items.append(item)
        return items, index

    def _parse_block_scalar(self, index: int, parent_indent: int) -> tuple[str, int]:
        parts: list[str] = []
        while index < len(self.lines):
            current_indent, content = self.lines[index]
            if current_indent <= parent_indent:
                break
            parts.append(" " * max(current_indent - parent_indent - 2, 0) + content)
            index += 1
        return "\n".join(parts), index


def _dump_node(value: Any, *, indent: int, sort_keys: bool) -> str:
    pad = " " * indent
    if isinstance(value, dict):
        if not value:
            return "{}"
        lines: list[str] = []
        keys = sorted(value, key=lambda item: str(item)) if sort_keys else list(value)
        for key in keys:
            child = value[key]
            rendered_key = _format_key(str(key))
            if isinstance(child, dict) and child:
                lines.append(f"{pad}{rendered_key}:")
                lines.append(_dump_node(child, indent=indent + 2, sort_keys=sort_keys))
            elif isinstance(child, list) and child:
                lines.append(f"{pad}{rendered_key}:")
                lines.append(_dump_node(child, indent=indent + 2, sort_keys=sort_keys))
            else:
                lines.append(f"{pad}{rendered_key}: {_format_scalar(child)}")
        return "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return "[]"
        lines = []
        for item in value:
            if isinstance(item, (dict, list)) and item:
                lines.append(f"{pad}-")
                lines.append(_dump_node(item, indent=indent + 2, sort_keys=sort_keys))
            else:
                lines.append(f"{pad}- {_format_scalar(item)}")
        return "\n".join(lines)
    return f"{pad}{_format_scalar(value)}"


def _format_key(value: str) -> str:
    return value if _is_plain_safe(value, key=True) else _single_quote(value)


def _format_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[]"
    if isinstance(value, dict):
        return "{}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    text = str(value)
    if "\n" in text:
        body = "\n".join(f"  {line}" if line else "" for line in text.splitlines())
        return "|\n" + body
    if text == "":
        return "''"
    return text if _is_plain_safe(text, key=False) else _single_quote(text)


def _single_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _is_plain_safe(value: str, *, key: bool) -> bool:
    if not value or value.strip() != value:
        return False
    lowered = value.lower()
    # Quote anything that would be coerced to a YAML 1.1 boolean / null on
    # parse. Matches the literals recognized by _parse_scalar above so dump +
    # load is a stable round-trip even when the value is a string like "y" or
    # "no" (the classic YAML "Norway problem" workaround).
    if lowered == "~":
        return False
    if lowered in _YAML_TRUE_LITERALS or lowered in _YAML_FALSE_LITERALS:
        return False
    if lowered == "null":
        return False
    if re.fullmatch(r"[-+]?(?:0|[1-9]\d*)(?:\.\d+)?", value):
        return False
    if value[0] in "-?:,[]{}#&*!|>'\"%@`":
        return False
    if ": " in value or " #" in value:
        return False
    if not key and value in {"[]", "{}"}:
        return False
    return True


def _strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(line):
        if in_double and escaped:
            escaped = False
            continue
        if in_double and char == "\\":
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if char == "#" and not in_single and not in_double:
            if index == 0 or line[index - 1].isspace():
                return line[:index]
    return line


def _split_key_value(content: str, source: str) -> tuple[str, str]:
    in_single = False
    in_double = False
    for index, char in enumerate(content):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == ":" and not in_single and not in_double:
            if index + 1 == len(content) or content[index + 1].isspace():
                return _parse_key(content[:index].strip()), content[index + 1 :].strip()
    raise YamlCompatError(f"Expected key/value mapping in {source}: {content!r}")


def _parse_key(raw: str) -> str:
    value = raw.strip()
    parsed = _parse_scalar(value)
    return str(parsed)


_YAML_TRUE_LITERALS = frozenset({"true", "yes", "on", "y"})
_YAML_FALSE_LITERALS = frozenset({"false", "no", "off", "n"})


def _parse_scalar(raw: str) -> Any:
    value = raw.strip()
    lowered = value.lower()
    if value == "[]":
        return []
    if value == "{}":
        return {}
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part.strip()) for part in _split_inline(inner)]
    if lowered in {"null", "~"}:
        return None
    # YAML 1.1 booleans: PyYAML's safe_load treats yes/no/on/off/y/n (case
    # insensitive) as bools, so the fallback must do the same to round-trip
    # operator-authored specs identically. _is_plain_safe already quotes these
    # literals on dump to avoid accidental coercion.
    if lowered in _YAML_TRUE_LITERALS:
        return True
    if lowered in _YAML_FALSE_LITERALS:
        return False
    if (value.startswith("'") and value.endswith("'")) or (value.startswith('"') and value.endswith('"')):
        return _parse_quoted(value)
    if re.fullmatch(r"[-+]?(?:0|[1-9]\d*)", value):
        try:
            return int(value)
        except ValueError:
            pass
    if re.fullmatch(r"[-+]?(?:0|[1-9]\d*)\.\d+", value):
        try:
            return float(value)
        except ValueError:
            pass
    return value


def _parse_quoted(value: str) -> str:
    if value.startswith("'"):
        return value[1:-1].replace("''", "'")
    return json.loads(value)


def _split_inline(value: str) -> list[str]:
    parts: list[str] = []
    start = 0
    in_single = False
    in_double = False
    for index, char in enumerate(value):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "," and not in_single and not in_double:
            parts.append(value[start:index])
            start = index + 1
    parts.append(value[start:])
    return parts


def _looks_like_mapping_item(value: str) -> bool:
    try:
        _split_key_value(value, "<list item>")
        return True
    except YamlCompatError:
        return False


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
