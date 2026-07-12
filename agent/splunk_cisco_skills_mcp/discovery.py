"""Bounded, read-only discovery for the repository-local MCP server.

This module deliberately does not import the MCP SDK and never starts a
subprocess.  It provides product-first skill discovery plus narrowly scoped
reads of skill instructions, references, and templates.  Repository content is
opened relative to a trusted directory descriptor with no-follow semantics so
that a path validation check cannot be separated from the file that is read.
"""

from __future__ import annotations

import base64
import codecs
import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from typing_extensions import TypedDict

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_RELATIVE_PATH = "skills"
PRODUCT_REGISTRY_PARTS = ("shared", "skill_product_registry.json")
CISCO_CATALOG_PARTS = ("cisco-product-setup", "catalog.json")

MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_LIMIT = 25
MIN_READ_BYTES = 1
MAX_READ_BYTES = 256 * 1024
DEFAULT_READ_BYTES = 64 * 1024
MAX_TEXT_FILE_BYTES = 8 * 1024 * 1024
MAX_CATALOG_BYTES = 4 * 1024 * 1024
MAX_FILES_PER_SKILL = 512
MAX_RESOURCE_BYTES_PER_SKILL = 32 * 1024 * 1024
MAX_RESOURCE_DIRECTORIES = 128
MAX_RESOURCE_DEPTH = 16
MAX_RESOURCE_ENTRIES = 1024
MAX_CURSOR_CHARS = 4096
MAX_QUERY_CHARS = 4096
MAX_DESCRIPTION_CHARS = 500
MAX_FRONTMATTER_BYTES = 64 * 1024
MAX_FRONTMATTER_KEYS = 64
MAX_FRONTMATTER_NODES = 2048
MAX_FRONTMATTER_DEPTH = 32
MAX_CATALOG_NODES = 100_000
MAX_CATALOG_DEPTH = 64

SkillFileKind = Literal["instructions", "reference", "template"]

_SKILL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,253}[a-z0-9])?$")
_IDENTIFIER_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---(?:\s*\n|\Z)", re.DOTALL)
_TRANSIENT_NAMES = {
    ".DS_Store",
    "__pycache__",
    "node_modules",
    "Thumbs.db",
}
_TRANSIENT_SUFFIXES = (".pyc", ".pyo", ".swp", ".swo", ".tmp", "~")
_REFERENCE_SUFFIXES = {".json", ".md", ".txt", ".yaml", ".yml"}
_TEMPLATE_SUFFIXES = {
    ".conf",
    ".example",
    ".json",
    ".md",
    ".service",
    ".txt",
    ".yaml",
    ".yml",
}
_CURATED_ENTRYPOINTS: tuple[tuple[str, str, str], ...] = (
    ("setup", "scripts/setup.sh", "mutating"),
    # Names are not an authorization boundary: some validation/doctor scripts
    # create reports, caches, or remote sessions. Only typed workflows may
    # claim a narrower read-only execution classification.
    ("validate", "scripts/validate.sh", "potentially-mutating"),
    ("doctor", "scripts/doctor.sh", "potentially-mutating"),
)
_CURSOR_SECRET = secrets.token_bytes(32)
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
_FILE_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
)


class _NoAliasSafeLoader(yaml.SafeLoader):
    """SafeLoader variant that rejects YAML aliases in skill metadata."""

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(yaml.AliasEvent):
            event = self.peek_event()
            raise yaml.YAMLError(
                f"YAML aliases are not allowed in skill frontmatter at {event.start_mark}"
            )
        node_count = getattr(self, "_bounded_node_count", 0) + 1
        depth = getattr(self, "_bounded_node_depth", 0) + 1
        if node_count > MAX_FRONTMATTER_NODES:
            raise yaml.YAMLError("skill frontmatter exceeds the YAML node limit")
        if depth > MAX_FRONTMATTER_DEPTH:
            raise yaml.YAMLError("skill frontmatter exceeds the YAML depth limit")
        self._bounded_node_count = node_count
        self._bounded_node_depth = depth
        try:
            return super().compose_node(parent, index)
        finally:
            self._bounded_node_depth -= 1

    def construct_mapping(self, node: Any, deep: bool = False) -> dict[Any, Any]:
        if not isinstance(node, yaml.MappingNode):
            return super().construct_mapping(node, deep=deep)
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as exc:
                raise yaml.YAMLError("frontmatter mapping key is not hashable") from exc
            if duplicate:
                raise yaml.YAMLError(f"duplicate frontmatter key: {key!r}")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


class DiscoveryError(ValueError):
    """Base class for safe, user-presentable discovery failures."""

    code = "discovery_error"


class InvalidDiscoveryRequest(DiscoveryError):
    """An argument is malformed or outside a documented bound."""

    code = "invalid_request"


class DiscoveryNotFound(DiscoveryError):
    """A requested skill, filter, or resource does not exist."""

    code = "not_found"


class InvalidCursor(DiscoveryError):
    """A pagination cursor is invalid, stale, or belongs to another query."""

    code = "invalid_cursor"


class UnsafeDiscoveryPath(DiscoveryError):
    """A requested path is outside the curated, no-follow resource surface."""

    code = "unsafe_path"


class DiscoveryLimitExceeded(DiscoveryError):
    """Catalog or resource content exceeds a defensive size/count bound."""

    code = "limit_exceeded"


class BinaryResourceRejected(DiscoveryError):
    """A resource advertised as text is not valid UTF-8 text."""

    code = "binary_resource"


class DiscoveryCatalogError(DiscoveryError):
    """The checked-in product or skill catalog is malformed or inconsistent."""

    code = "catalog_error"


class ProductRef(TypedDict):
    id: str
    name: str


class CapabilityRef(TypedDict):
    id: str
    name: str


class SkillSearchRecord(TypedDict):
    skill: str
    description: str
    product: ProductRef
    capability: CapabilityRef


class SearchSkillsResult(TypedDict):
    skills: list[SkillSearchRecord]
    total: int
    next_cursor: str | None
    revision: str


class ResourceSummary(TypedDict):
    kind: SkillFileKind
    count: int


class RunnableEntrypoint(TypedDict):
    operation: str
    path: str
    risk: str


class SkillManifestResult(TypedDict):
    skill: str
    description: str
    product: ProductRef
    capability: CapabilityRef
    resources: list[ResourceSummary]
    entrypoints: list[RunnableEntrypoint]
    revision: str


class SkillFileRecord(TypedDict):
    path: str
    kind: SkillFileKind
    size: int
    mime_type: str


class ListSkillFilesResult(TypedDict):
    skill: str
    kind: SkillFileKind
    files: list[SkillFileRecord]
    total: int
    next_cursor: str | None
    revision: str


class ReadSkillFileResult(TypedDict):
    skill: str
    path: str
    mime_type: str
    offset: int
    next_offset: int
    size: int
    eof: bool
    text: str
    revision: str


class ResolveCiscoProductResult(TypedDict):
    status: Literal["resolved", "ambiguous", "not_found"]
    query: str
    matches: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class _SkillRecord:
    skill: str
    description: str
    product_id: str
    product_name: str
    capability_id: str
    capability_name: str
    product_order: int
    capability_order: int

    def public(self) -> SkillSearchRecord:
        return {
            "skill": self.skill,
            "description": self.description,
            "product": {"id": self.product_id, "name": self.product_name},
            "capability": {
                "id": self.capability_id,
                "name": self.capability_name,
            },
        }


@dataclass(frozen=True, slots=True)
class _Catalog:
    revision: str
    records: tuple[_SkillRecord, ...]
    by_skill: dict[str, _SkillRecord]
    product_filters: dict[str, str]
    capability_filters: dict[str, str]


@dataclass(frozen=True, slots=True)
class _OpenedTextFile:
    descriptor: int
    stat_before: os.stat_result


def _compact(value: str, *, limit: int = MAX_DESCRIPTION_CHARS) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3].rsplit(" ", 1)[0].rstrip(".,;:") + "..."


def _normalize(value: str) -> str:
    value = value.lower().replace("&", " and ").replace("_", " ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate JSON key: {key!r}")
        payload[key] = value
    return payload


def _load_catalog_json(text: str, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(text, object_pairs_hook=_reject_duplicate_json_keys)
    except (json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise DiscoveryCatalogError(f"{label} is invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise DiscoveryCatalogError(f"{label} must be a JSON object")
    stack: list[tuple[Any, int]] = [(payload, 0)]
    node_count = 0
    while stack:
        value, depth = stack.pop()
        node_count += 1
        if node_count > MAX_CATALOG_NODES:
            raise DiscoveryCatalogError(f"{label} exceeds the JSON node limit")
        if depth > MAX_CATALOG_DEPTH:
            raise DiscoveryCatalogError(f"{label} exceeds the JSON depth limit")
        if isinstance(value, dict):
            stack.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            stack.extend((item, depth + 1) for item in value)
    return payload


def _validate_skill(skill: str) -> str:
    if not isinstance(skill, str) or not _SKILL_RE.fullmatch(skill):
        raise InvalidDiscoveryRequest(
            "skill must be a lowercase, hyphenated identifier of at most 255 characters"
        )
    return skill


def _validate_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise InvalidDiscoveryRequest("limit must be an integer")
    if not MIN_PAGE_LIMIT <= limit <= MAX_PAGE_LIMIT:
        raise InvalidDiscoveryRequest(
            f"limit must be between {MIN_PAGE_LIMIT} and {MAX_PAGE_LIMIT}"
        )
    return limit


def _validate_read_range(offset: int, max_bytes: int) -> tuple[int, int]:
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise InvalidDiscoveryRequest("offset must be a non-negative integer")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int):
        raise InvalidDiscoveryRequest("max_bytes must be an integer")
    if not MIN_READ_BYTES <= max_bytes <= MAX_READ_BYTES:
        raise InvalidDiscoveryRequest(
            f"max_bytes must be between {MIN_READ_BYTES} and {MAX_READ_BYTES}"
        )
    return offset, max_bytes


def _safe_parts(path: str) -> tuple[str, ...]:
    if not isinstance(path, str) or not path or len(path) > 4096:
        raise InvalidDiscoveryRequest(
            "path must be a non-empty string of at most 4096 characters"
        )
    if "\\" in path or "\x00" in path:
        raise UnsafeDiscoveryPath("path must use normalized POSIX separators")
    parsed = PurePosixPath(path)
    parts = parsed.parts
    if (
        parsed.is_absolute()
        or not parts
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise UnsafeDiscoveryPath(
            "absolute paths and traversal components are forbidden"
        )
    if parsed.as_posix() != path:
        raise UnsafeDiscoveryPath("path must be normalized")
    if any(_is_hidden_or_transient(part) for part in parts):
        raise UnsafeDiscoveryPath("hidden and transient paths are not readable")
    return parts


def _is_hidden_or_transient(name: str) -> bool:
    return (
        name.startswith(".")
        or name in _TRANSIENT_NAMES
        or name.endswith(_TRANSIENT_SUFFIXES)
    )


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode),
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _mime_type(path: str) -> str:
    suffix = PurePosixPath(path).suffix.lower()
    if suffix == ".md":
        return "text/markdown"
    if suffix == ".json":
        return "application/json"
    if suffix in {".yaml", ".yml"}:
        return "application/yaml"
    return "text/plain"


def _cursor_context(operation: str, values: dict[str, Any]) -> str:
    encoded = json.dumps(
        {"operation": operation, **values},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _encode_cursor(*, revision: str, context: str, offset: int) -> str:
    body = json.dumps(
        {"v": 1, "revision": revision, "context": context, "offset": offset},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    signature = hmac.digest(_CURSOR_SECRET, body, "sha256")
    return base64.urlsafe_b64encode(body + signature).decode("ascii").rstrip("=")


def _decode_cursor(
    cursor: str | None,
    *,
    revision: str,
    context: str,
    total: int,
) -> int:
    if cursor is None:
        return 0
    if not isinstance(cursor, str) or not cursor or len(cursor) > MAX_CURSOR_CHARS:
        raise InvalidCursor("cursor is empty or exceeds its size bound")
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.b64decode(cursor + padding, altchars=b"-_", validate=True)
    except (ValueError, TypeError) as exc:
        raise InvalidCursor("cursor is not valid URL-safe base64") from exc
    canonical = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    if not hmac.compare_digest(canonical, cursor):
        raise InvalidCursor("cursor is not canonically encoded")
    if len(raw) <= hashlib.sha256().digest_size:
        raise InvalidCursor("cursor is truncated")
    body, signature = raw[:-32], raw[-32:]
    expected = hmac.digest(_CURSOR_SECRET, body, "sha256")
    if not hmac.compare_digest(signature, expected):
        raise InvalidCursor("cursor authentication failed")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidCursor("cursor payload is invalid") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "v",
        "revision",
        "context",
        "offset",
    }:
        raise InvalidCursor("cursor payload has an unsupported shape")
    if payload["v"] != 1:
        raise InvalidCursor("cursor version is unsupported")
    if payload["revision"] != revision or payload["context"] != context:
        raise InvalidCursor("cursor is stale or belongs to another query")
    offset = payload["offset"]
    if (
        isinstance(offset, bool)
        or not isinstance(offset, int)
        or not 0 <= offset <= total
    ):
        raise InvalidCursor("cursor offset is outside the result set")
    return offset


class SkillDiscovery:
    """Thread-safe discovery service rooted at one repository checkout."""

    def __init__(self, repo_root: Path = REPO_ROOT) -> None:
        root = Path(repo_root)
        try:
            root_stat = root.lstat()
        except OSError as exc:
            raise DiscoveryCatalogError(
                f"repository root is unavailable: {exc}"
            ) from exc
        if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
            raise DiscoveryCatalogError(
                "repository root must be a real directory, not a symlink"
            )
        self.repo_root = root.absolute()
        self.skills_dir = self.repo_root / SKILLS_RELATIVE_PATH
        self._cache_lock = threading.Lock()
        self._resource_cache_lock = threading.Lock()
        self._catalog_cache: tuple[tuple[Any, ...], _Catalog] | None = None
        self._cisco_cache: (
            tuple[tuple[int, int, int, int, int], tuple[dict[str, Any], ...]] | None
        ) = None
        self._resource_cache: dict[
            tuple[str, SkillFileKind],
            tuple[tuple[tuple[Any, ...], ...], tuple[SkillFileRecord, ...]],
        ] = {}
        self._validated_resource_identities: dict[
            tuple[str, str],
            tuple[int, int, int, int, int, int],
        ] = {}

    def clear_cache(self) -> None:
        """Discard cached catalog data, primarily for controlled repository reloads."""

        with self._cache_lock:
            self._catalog_cache = None
            self._cisco_cache = None
        with self._resource_cache_lock:
            self._resource_cache.clear()
            self._validated_resource_identities.clear()

    def search_skills(
        self,
        query: str | None = None,
        product: str | None = None,
        capability: str | None = None,
        limit: int = DEFAULT_PAGE_LIMIT,
        cursor: str | None = None,
    ) -> SearchSkillsResult:
        """Search classified skills with product-first filtering and pagination."""

        limit = _validate_limit(limit)
        query_norm = self._optional_search_value(query, "query")
        product_norm = self._optional_search_value(product, "product")
        capability_norm = self._optional_search_value(capability, "capability")
        catalog = self._catalog()

        product_id: str | None = None
        if product_norm is not None:
            product_id = catalog.product_filters.get(product_norm)
            if product_id is None:
                raise DiscoveryNotFound(f"unknown product filter: {product!r}")
        capability_id: str | None = None
        if capability_norm is not None:
            capability_id = catalog.capability_filters.get(capability_norm)
            if capability_id is None:
                raise DiscoveryNotFound(f"unknown capability filter: {capability!r}")

        ranked: list[tuple[int, int, int, str, _SkillRecord]] = []
        for record in catalog.records:
            if product_id is not None and record.product_id != product_id:
                continue
            if capability_id is not None and record.capability_id != capability_id:
                continue
            score = self._query_score(record, query_norm)
            if score is None:
                continue
            ranked.append(
                (
                    score,
                    record.product_order,
                    record.capability_order,
                    record.skill,
                    record,
                )
            )
        ranked.sort(key=lambda item: item[:4])
        records = [item[4] for item in ranked]
        context = _cursor_context(
            "search_skills",
            {
                "query": query_norm,
                "product": product_id,
                "capability": capability_id,
            },
        )
        start = _decode_cursor(
            cursor,
            revision=catalog.revision,
            context=context,
            total=len(records),
        )
        page = records[start : start + limit]
        next_offset = start + len(page)
        next_cursor = (
            _encode_cursor(
                revision=catalog.revision,
                context=context,
                offset=next_offset,
            )
            if next_offset < len(records)
            else None
        )
        return {
            "skills": [record.public() for record in page],
            "total": len(records),
            "next_cursor": next_cursor,
            "revision": catalog.revision,
        }

    def get_skill_manifest(self, skill: str) -> SkillManifestResult:
        """Return classification, resource counts, and reviewed entrypoints."""

        skill = _validate_skill(skill)
        catalog = self._catalog()
        record = catalog.by_skill.get(skill)
        if record is None:
            raise DiscoveryNotFound(f"unknown skill: {skill}")
        resources: list[ResourceSummary] = []
        resource_revisions: list[str] = []
        for kind in ("instructions", "reference", "template"):
            paths = self._resource_paths(skill, kind)
            resources.append({"kind": kind, "count": len(paths)})
            resource_revisions.append(
                self._resource_revision(catalog.revision, skill, kind)
            )
        entrypoints = self._entrypoints(skill)
        revision = hashlib.sha256(
            json.dumps(
                {
                    "catalog": catalog.revision,
                    "resources": resource_revisions,
                    "entrypoints": entrypoints,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return {
            **record.public(),
            "resources": resources,
            "entrypoints": entrypoints,
            "revision": revision,
        }

    def list_skill_files(
        self,
        skill: str,
        kind: SkillFileKind,
        limit: int = DEFAULT_PAGE_LIMIT,
        cursor: str | None = None,
    ) -> ListSkillFilesResult:
        """List one bounded class of curated, UTF-8 skill resources."""

        skill = _validate_skill(skill)
        kind = self._validate_kind(kind)
        limit = _validate_limit(limit)
        catalog = self._catalog()
        if skill not in catalog.by_skill:
            raise DiscoveryNotFound(f"unknown skill: {skill}")
        records = self._resource_paths(skill, kind)
        revision = self._resource_revision(catalog.revision, skill, kind)
        inventory = [f"{item['path']}:{item['size']}" for item in records]
        context = _cursor_context(
            "list_skill_files",
            {"skill": skill, "kind": kind, "inventory": inventory},
        )
        start = _decode_cursor(
            cursor,
            revision=revision,
            context=context,
            total=len(records),
        )
        page = records[start : start + limit]
        next_offset = start + len(page)
        next_cursor = (
            _encode_cursor(
                revision=revision,
                context=context,
                offset=next_offset,
            )
            if next_offset < len(records)
            else None
        )
        return {
            "skill": skill,
            "kind": kind,
            "files": page,
            "total": len(records),
            "next_cursor": next_cursor,
            "revision": revision,
        }

    def read_skill_file(
        self,
        skill: str,
        path: str,
        offset: int = 0,
        max_bytes: int = DEFAULT_READ_BYTES,
    ) -> ReadSkillFileResult:
        """Read one page from a curated UTF-8 resource using stable descriptors."""

        skill = _validate_skill(skill)
        offset, max_bytes = _validate_read_range(offset, max_bytes)
        path_parts = _safe_parts(path)
        catalog = self._catalog()
        if skill not in catalog.by_skill:
            raise DiscoveryNotFound(f"unknown skill: {skill}")
        if path == "SKILL.md":
            resource_kind: SkillFileKind = "instructions"
        elif path == "reference.md" or (
            path.startswith("references/")
            and PurePosixPath(path).suffix.lower() in _REFERENCE_SUFFIXES
        ):
            resource_kind = "reference"
        elif path == "template.example" or (
            path.startswith("templates/")
            and PurePosixPath(path).suffix.lower() in _TEMPLATE_SUFFIXES
        ):
            resource_kind = "template"
        else:
            raise UnsafeDiscoveryPath(
                "path is not a curated instruction, reference, or template resource"
            )
        allowed = {
            item["path"]: item for item in self._resource_paths(skill, resource_kind)
        }
        revision = self._resource_revision(
            catalog.revision,
            skill,
            resource_kind,
        )
        resource = allowed.get(path)
        if resource is None:
            raise UnsafeDiscoveryPath(
                "path is not a curated instruction, reference, or template resource"
            )
        opened = self._open_text_file(
            (skill, *path_parts), max_size=MAX_TEXT_FILE_BYTES
        )
        try:
            file_size = opened.stat_before.st_size
            if offset > file_size:
                raise InvalidDiscoveryRequest(
                    f"offset {offset} exceeds file size {file_size}"
                )
            opened_identity = _stat_identity(opened.stat_before)
            with self._resource_cache_lock:
                validated_identity = self._validated_resource_identities.get(
                    (skill, path)
                )
            if validated_identity != opened_identity:
                self._validate_utf8_descriptor(opened.descriptor, file_size)
            raw = os.pread(opened.descriptor, max_bytes, offset)
            if raw and offset and raw[0] & 0xC0 == 0x80:
                raise InvalidDiscoveryRequest(
                    "offset is not on a UTF-8 character boundary"
                )
            text, consumed = self._decode_bounded_chunk(raw)
            if raw and consumed == 0:
                raise DiscoveryLimitExceeded(
                    "max_bytes is too small to contain the next UTF-8 character"
                )
            stat_after = os.fstat(opened.descriptor)
            if _stat_identity(stat_after) != _stat_identity(opened.stat_before):
                raise UnsafeDiscoveryPath("resource changed while it was being read")
            with self._resource_cache_lock:
                self._validated_resource_identities[(skill, path)] = opened_identity
        finally:
            os.close(opened.descriptor)
        next_offset = offset + consumed
        return {
            "skill": skill,
            "path": path,
            "mime_type": resource["mime_type"],
            "offset": offset,
            "next_offset": next_offset,
            "size": file_size,
            "eof": next_offset >= file_size,
            "text": text,
            "revision": revision,
        }

    def resolve_cisco_product(self, query: str) -> ResolveCiscoProductResult:
        """Resolve a Cisco product without launching the legacy shell wrapper."""

        if not isinstance(query, str) or not query or len(query) > MAX_QUERY_CHARS:
            raise InvalidDiscoveryRequest(
                f"query must be a non-empty string of at most {MAX_QUERY_CHARS} characters"
            )
        if "\x00" in query:
            raise InvalidDiscoveryRequest("query must not contain NUL")
        products = self._cisco_products()
        query_norm = _normalize(query)
        ranked: list[tuple[int, int, dict[str, Any]]] = []
        for product in products:
            terms = product.get("normalized_search_terms", [])
            display_terms = {
                _normalize(alias)
                for alias in self._display_aliases(str(product.get("display_name", "")))
            }
            aliases = product.get("aliases", [])
            alias_terms = {
                _normalize(alias) for alias in aliases if isinstance(alias, str)
            }
            product_id = str(product.get("id", ""))
            score: int | None = None
            if query == product_id or query_norm == _normalize(product_id):
                score = 0
            elif query_norm in display_terms:
                score = 1
            elif query_norm in alias_terms:
                score = 2
            elif isinstance(terms, list) and query_norm in terms:
                score = 3
            elif isinstance(terms, list) and any(
                isinstance(term, str) and query_norm and query_norm in term
                for term in terms
            ):
                score = 4
            if score is not None:
                ranked.append((score, self._product_state_rank(product), product))

        if not ranked:
            return {"status": "not_found", "query": query, "matches": []}
        ranked.sort(
            key=lambda item: (
                item[0],
                item[1],
                str(item[2].get("display_name", "")).lower(),
                str(item[2].get("id", "")),
            )
        )
        best_score, best_state = ranked[0][:2]
        matches = [
            copy.deepcopy(product)
            for score, state_rank, product in ranked
            if score == best_score and state_rank == best_state
        ]
        return {
            "status": "resolved" if len(matches) == 1 else "ambiguous",
            "query": query,
            "matches": matches,
        }

    @staticmethod
    def _optional_search_value(value: str | None, label: str) -> str | None:
        if value is None:
            return None
        if (
            not isinstance(value, str)
            or len(value) > MAX_QUERY_CHARS
            or "\x00" in value
        ):
            raise InvalidDiscoveryRequest(
                f"{label} must be a string of at most {MAX_QUERY_CHARS} characters"
            )
        normalized = _normalize(value)
        return normalized or None

    @staticmethod
    def _validate_kind(kind: str) -> SkillFileKind:
        if kind not in {"instructions", "reference", "template"}:
            raise InvalidDiscoveryRequest(
                "kind must be one of: instructions, reference, template"
            )
        return kind  # type: ignore[return-value]

    @staticmethod
    def _query_score(record: _SkillRecord, query_norm: str | None) -> int | None:
        if query_norm is None:
            return 0
        skill_norm = _normalize(record.skill)
        if query_norm == skill_norm:
            return 0
        if skill_norm.startswith(query_norm):
            return 1
        if query_norm in {
            _normalize(record.product_id),
            _normalize(record.product_name),
        }:
            return 2
        if query_norm in {
            _normalize(record.capability_id),
            _normalize(record.capability_name),
        }:
            return 3
        haystack = " ".join(
            (
                skill_norm,
                _normalize(record.description),
                _normalize(record.product_name),
                _normalize(record.capability_name),
            )
        )
        tokens = query_norm.split()
        if tokens and all(token in haystack for token in tokens):
            return 4
        return None

    def _catalog_signature(self) -> tuple[Any, ...]:
        registry_path = self.skills_dir.joinpath(*PRODUCT_REGISTRY_PARTS)
        try:
            registry_stat = registry_path.lstat()
        except OSError as exc:
            raise DiscoveryCatalogError(
                f"product registry is unavailable: {exc}"
            ) from exc
        if not stat.S_ISREG(registry_stat.st_mode) or stat.S_ISLNK(
            registry_stat.st_mode
        ):
            raise DiscoveryCatalogError(
                "product registry must be a regular, non-symlink file"
            )
        skill_stats: list[tuple[str, int, int, int, int, int]] = []
        try:
            entries = list(os.scandir(self.skills_dir))
        except OSError as exc:
            raise DiscoveryCatalogError(
                f"skills directory is unavailable: {exc}"
            ) from exc
        for entry in entries:
            if entry.name == "shared" or _is_hidden_or_transient(entry.name):
                continue
            if not entry.is_dir(follow_symlinks=False):
                continue
            if not _SKILL_RE.fullmatch(entry.name):
                continue
            skill_md = self.skills_dir / entry.name / "SKILL.md"
            try:
                skill_stat = skill_md.lstat()
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(skill_stat.st_mode) or stat.S_ISLNK(skill_stat.st_mode):
                raise DiscoveryCatalogError(
                    f"{entry.name}/SKILL.md must be a regular file"
                )
            skill_stats.append(
                (
                    entry.name,
                    skill_stat.st_ino,
                    skill_stat.st_size,
                    skill_stat.st_mtime_ns,
                    skill_stat.st_ctime_ns,
                    skill_stat.st_dev,
                )
            )
        return (
            registry_stat.st_dev,
            registry_stat.st_ino,
            registry_stat.st_size,
            registry_stat.st_mtime_ns,
            registry_stat.st_ctime_ns,
            tuple(sorted(skill_stats)),
        )

    def _catalog(self) -> _Catalog:
        signature = self._catalog_signature()
        with self._cache_lock:
            if self._catalog_cache is not None and self._catalog_cache[0] == signature:
                return self._catalog_cache[1]
            catalog = self._build_catalog()
            if self._catalog_signature() != signature:
                raise DiscoveryCatalogError(
                    "skill catalog changed while it was being loaded"
                )
            self._catalog_cache = (signature, catalog)
            return catalog

    def _build_catalog(self) -> _Catalog:
        registry_text = self._read_complete_text(
            PRODUCT_REGISTRY_PARTS,
            max_size=MAX_CATALOG_BYTES,
        )
        payload = _load_catalog_json(registry_text, label="product registry")
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise DiscoveryCatalogError("product registry must use schema_version 1")
        products = payload.get("products")
        if not isinstance(products, list) or not products:
            raise DiscoveryCatalogError(
                "product registry must contain a non-empty products list"
            )

        digest = hashlib.sha256()
        digest.update(b"skill-product-registry-v1\0")
        digest.update(registry_text.encode("utf-8"))
        records: list[_SkillRecord] = []
        classified: set[str] = set()
        product_filters: dict[str, str] = {}
        capability_filters: dict[str, str] = {}
        for product_order, product in enumerate(products):
            location = f"products[{product_order}]"
            if not isinstance(product, dict):
                raise DiscoveryCatalogError(f"{location} must be an object")
            product_id = self._catalog_identifier(product.get("id"), f"{location}.id")
            product_name = self._catalog_text(product.get("name"), f"{location}.name")
            self._add_filter(product_filters, product_id, product_id, "product")
            self._add_filter(product_filters, product_name, product_id, "product")
            capabilities = product.get("capabilities")
            if not isinstance(capabilities, list) or not capabilities:
                raise DiscoveryCatalogError(
                    f"{location}.capabilities must be non-empty"
                )
            for capability_order, capability in enumerate(capabilities):
                cap_location = f"{location}.capabilities[{capability_order}]"
                if not isinstance(capability, dict):
                    raise DiscoveryCatalogError(f"{cap_location} must be an object")
                capability_id = self._catalog_identifier(
                    capability.get("id"), f"{cap_location}.id"
                )
                capability_name = self._catalog_text(
                    capability.get("name"), f"{cap_location}.name"
                )
                self._add_filter(
                    capability_filters,
                    capability_id,
                    capability_id,
                    "capability",
                )
                self._add_filter(
                    capability_filters,
                    capability_name,
                    capability_id,
                    "capability",
                )
                skills = capability.get("skills")
                if not isinstance(skills, list) or not skills:
                    raise DiscoveryCatalogError(
                        f"{cap_location}.skills must be non-empty"
                    )
                for skill_value in skills:
                    if not isinstance(skill_value, str):
                        raise DiscoveryCatalogError(
                            f"{cap_location}.skills must contain strings"
                        )
                    skill = _validate_skill(skill_value)
                    if skill in classified:
                        raise DiscoveryCatalogError(
                            f"skill is classified more than once: {skill}"
                        )
                    instruction_text = self._read_complete_text(
                        (skill, "SKILL.md"),
                        max_size=MAX_TEXT_FILE_BYTES,
                    )
                    metadata = self._frontmatter(instruction_text, skill)
                    description = metadata.get("description")
                    if not isinstance(description, str) or not description.strip():
                        raise DiscoveryCatalogError(
                            f"{skill}/SKILL.md is missing a frontmatter description"
                        )
                    declared_name = metadata.get("name")
                    if declared_name != skill:
                        raise DiscoveryCatalogError(
                            f"{skill}/SKILL.md frontmatter name must equal its directory"
                        )
                    classified.add(skill)
                    digest.update(f"\0{skill}\0".encode("utf-8"))
                    digest.update(instruction_text.encode("utf-8"))
                    records.append(
                        _SkillRecord(
                            skill=skill,
                            description=_compact(description),
                            product_id=product_id,
                            product_name=product_name,
                            capability_id=capability_id,
                            capability_name=capability_name,
                            product_order=product_order,
                            capability_order=capability_order,
                        )
                    )

        actual = {item[0] for item in self._catalog_signature()[-1]}
        if classified != actual:
            missing = sorted(actual - classified)
            unknown = sorted(classified - actual)
            raise DiscoveryCatalogError(
                "product registry classification mismatch; "
                f"unclassified={missing}, missing_skill_directories={unknown}"
            )
        return _Catalog(
            revision=digest.hexdigest(),
            records=tuple(records),
            by_skill={record.skill: record for record in records},
            product_filters=product_filters,
            capability_filters=capability_filters,
        )

    @staticmethod
    def _catalog_identifier(value: Any, location: str) -> str:
        if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
            raise DiscoveryCatalogError(
                f"{location} must be a lowercase hyphenated identifier"
            )
        return value

    @staticmethod
    def _catalog_text(value: Any, location: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise DiscoveryCatalogError(f"{location} must be a non-empty string")
        return _compact(value)

    @staticmethod
    def _add_filter(
        filters: dict[str, str],
        label: str,
        identifier: str,
        kind: str,
    ) -> None:
        normalized = _normalize(label)
        owner = filters.get(normalized)
        if owner is not None and owner != identifier:
            raise DiscoveryCatalogError(
                f"ambiguous normalized {kind} filter {label!r}: {owner!r}, {identifier!r}"
            )
        filters[normalized] = identifier

    @staticmethod
    def _frontmatter(text: str, skill: str) -> dict[str, Any]:
        match = _FRONTMATTER_RE.match(text)
        if not match:
            raise DiscoveryCatalogError(f"{skill}/SKILL.md has no YAML frontmatter")
        frontmatter = match.group(1)
        if len(frontmatter.encode("utf-8")) > MAX_FRONTMATTER_BYTES:
            raise DiscoveryCatalogError(
                f"{skill}/SKILL.md frontmatter exceeds {MAX_FRONTMATTER_BYTES} bytes"
            )
        try:
            metadata = yaml.load(frontmatter, Loader=_NoAliasSafeLoader)
        except yaml.YAMLError as exc:
            raise DiscoveryCatalogError(
                f"{skill}/SKILL.md has invalid YAML frontmatter: {exc}"
            ) from exc
        if not isinstance(metadata, dict):
            raise DiscoveryCatalogError(
                f"{skill}/SKILL.md frontmatter must be an object"
            )
        if len(metadata) > MAX_FRONTMATTER_KEYS:
            raise DiscoveryCatalogError(
                f"{skill}/SKILL.md frontmatter exceeds {MAX_FRONTMATTER_KEYS} keys"
            )
        return metadata

    def _entrypoints(self, skill: str) -> list[RunnableEntrypoint]:
        entrypoints: list[RunnableEntrypoint] = []
        for operation, path, risk in _CURATED_ENTRYPOINTS:
            try:
                opened = self._open_text_file(
                    (skill, *PurePosixPath(path).parts),
                    max_size=MAX_TEXT_FILE_BYTES,
                )
            except (DiscoveryNotFound, UnsafeDiscoveryPath, BinaryResourceRejected):
                continue
            try:
                mode = opened.stat_before.st_mode
                self._validate_utf8_descriptor(
                    opened.descriptor,
                    opened.stat_before.st_size,
                )
                stat_after = os.fstat(opened.descriptor)
                has_shebang = os.pread(opened.descriptor, 2, 0) == b"#!"
                if (
                    mode & 0o111
                    and has_shebang
                    and _stat_identity(stat_after) == _stat_identity(opened.stat_before)
                ):
                    entrypoints.append(
                        {"operation": operation, "path": path, "risk": risk}
                    )
            finally:
                os.close(opened.descriptor)
        return entrypoints

    def _resource_paths(
        self,
        skill: str,
        kind: SkillFileKind,
    ) -> list[SkillFileRecord]:
        candidates: list[str] = []
        if kind == "instructions":
            candidates = ["SKILL.md"]
        elif kind == "reference":
            candidates.extend(self._direct_candidate(skill, "reference.md"))
            candidates.extend(
                self._walk_candidates(skill, "references", _REFERENCE_SUFFIXES)
            )
        else:
            candidates.extend(self._direct_candidate(skill, "template.example"))
            candidates.extend(
                self._walk_candidates(skill, "templates", _TEMPLATE_SUFFIXES)
            )
        if len(candidates) > MAX_FILES_PER_SKILL:
            raise DiscoveryLimitExceeded(
                f"{skill} has more than {MAX_FILES_PER_SKILL} {kind} files"
            )
        ordered_paths = sorted(
            set(candidates), key=lambda value: (value != "SKILL.md", value)
        )
        signature_items: list[tuple[Any, ...]] = []
        aggregate_bytes = 0
        for path in ordered_paths:
            absolute = self.skills_dir / skill / path
            try:
                metadata = absolute.lstat()
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                continue
            if metadata.st_size > MAX_TEXT_FILE_BYTES:
                raise DiscoveryLimitExceeded(
                    f"{skill}/{path} exceeds the {MAX_TEXT_FILE_BYTES}-byte file limit"
                )
            aggregate_bytes += metadata.st_size
            if aggregate_bytes > MAX_RESOURCE_BYTES_PER_SKILL:
                raise DiscoveryLimitExceeded(
                    f"{skill} curated resources exceed the "
                    f"{MAX_RESOURCE_BYTES_PER_SKILL}-byte aggregate limit"
                )
            signature_items.append((path, *_stat_identity(metadata)))
        signature = tuple(signature_items)
        cache_key = (skill, kind)
        with self._resource_cache_lock:
            cached = self._resource_cache.get(cache_key)
            if cached is not None and cached[0] == signature:
                return [dict(item) for item in cached[1]]  # type: ignore[misc]

        records: list[SkillFileRecord] = []
        validated_identities: dict[
            tuple[str, str],
            tuple[int, int, int, int, int, int],
        ] = {}
        for path in ordered_paths:
            try:
                opened = self._open_text_file(
                    (skill, *PurePosixPath(path).parts),
                    max_size=MAX_TEXT_FILE_BYTES,
                )
            except (DiscoveryNotFound, UnsafeDiscoveryPath, BinaryResourceRejected):
                continue
            try:
                self._validate_utf8_descriptor(
                    opened.descriptor,
                    opened.stat_before.st_size,
                )
                stat_after = os.fstat(opened.descriptor)
                if _stat_identity(stat_after) != _stat_identity(opened.stat_before):
                    raise UnsafeDiscoveryPath("resource changed while it was inspected")
                records.append(
                    {
                        "path": path,
                        "kind": kind,
                        "size": opened.stat_before.st_size,
                        "mime_type": _mime_type(path),
                    }
                )
                validated_identities[(skill, path)] = _stat_identity(opened.stat_before)
            except BinaryResourceRejected:
                continue
            finally:
                os.close(opened.descriptor)
        with self._resource_cache_lock:
            self._resource_cache[cache_key] = (
                signature,
                tuple(records),
            )
            self._validated_resource_identities.update(validated_identities)
        return records

    def _resource_revision(
        self,
        catalog_revision: str,
        skill: str,
        kind: SkillFileKind,
    ) -> str:
        """Fingerprint the catalog plus stable identities for one resource class."""
        with self._resource_cache_lock:
            cached = self._resource_cache.get((skill, kind))
            signature = cached[0] if cached is not None else ()
        digest = hashlib.sha256()
        digest.update(catalog_revision.encode("ascii"))
        digest.update(b"\0")
        digest.update(skill.encode("utf-8"))
        digest.update(b"\0")
        digest.update(kind.encode("ascii"))
        digest.update(b"\0")
        digest.update(json.dumps(signature, separators=(",", ":")).encode("utf-8"))
        return digest.hexdigest()

    def _direct_candidate(self, skill: str, name: str) -> list[str]:
        path = self.skills_dir / skill / name
        try:
            value = path.lstat()
        except FileNotFoundError:
            return []
        if stat.S_ISREG(value.st_mode) and not stat.S_ISLNK(value.st_mode):
            return [name]
        return []

    def _walk_candidates(
        self,
        skill: str,
        directory: str,
        allowed_suffixes: set[str],
    ) -> list[str]:
        root = self.skills_dir / skill / directory
        try:
            root_stat = root.lstat()
        except FileNotFoundError:
            return []
        if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
            return []
        found: list[str] = []
        visited_files = 0
        visited_directories = 0
        visited_entries = 0
        for current, directories, files in os.walk(root, followlinks=False):
            visited_directories += 1
            visited_entries += len(directories) + len(files)
            depth = len(Path(current).relative_to(root).parts)
            if depth > MAX_RESOURCE_DEPTH:
                raise DiscoveryLimitExceeded(
                    f"{skill}/{directory} exceeds the traversal depth limit"
                )
            if visited_directories > MAX_RESOURCE_DIRECTORIES:
                raise DiscoveryLimitExceeded(
                    f"{skill}/{directory} exceeds the directory traversal limit"
                )
            if visited_entries > MAX_RESOURCE_ENTRIES:
                raise DiscoveryLimitExceeded(
                    f"{skill}/{directory} exceeds the directory entry limit"
                )
            directories[:] = sorted(
                name
                for name in directories
                if not _is_hidden_or_transient(name)
                and not (Path(current) / name).is_symlink()
            )
            for name in sorted(files):
                visited_files += 1
                if visited_files > MAX_FILES_PER_SKILL:
                    raise DiscoveryLimitExceeded(
                        f"{skill}/{directory} exceeds the file inventory limit"
                    )
                if _is_hidden_or_transient(name):
                    continue
                path = Path(current) / name
                try:
                    value = path.lstat()
                except FileNotFoundError:
                    continue
                if not stat.S_ISREG(value.st_mode) or stat.S_ISLNK(value.st_mode):
                    continue
                if path.suffix.lower() not in allowed_suffixes:
                    continue
                found.append(path.relative_to(self.skills_dir / skill).as_posix())
        return found

    def _open_text_file(
        self,
        relative_parts: tuple[str, ...],
        *,
        max_size: int,
    ) -> _OpenedTextFile:
        if not getattr(os, "O_NOFOLLOW", 0) or not hasattr(os, "pread"):
            raise UnsafeDiscoveryPath(
                "this platform cannot provide descriptor-relative, no-follow reads"
            )
        if not relative_parts:
            raise UnsafeDiscoveryPath("empty relative path")
        root_fd: int | None = None
        current_fd: int | None = None
        try:
            root_fd = os.open(self.skills_dir, _DIRECTORY_FLAGS)
            current_fd = root_fd
            for part in relative_parts[:-1]:
                if not part or part in {".", ".."} or "/" in part or "\x00" in part:
                    raise UnsafeDiscoveryPath("unsafe path component")
                next_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=current_fd)
                if current_fd != root_fd:
                    os.close(current_fd)
                current_fd = next_fd
            final = relative_parts[-1]
            if not final or final in {".", ".."} or "/" in final or "\x00" in final:
                raise UnsafeDiscoveryPath("unsafe file name")
            descriptor = os.open(final, _FILE_FLAGS, dir_fd=current_fd)
            value = os.fstat(descriptor)
            if not stat.S_ISREG(value.st_mode):
                os.close(descriptor)
                raise UnsafeDiscoveryPath("resource must be a regular file")
            if value.st_size > max_size:
                os.close(descriptor)
                raise DiscoveryLimitExceeded(
                    f"resource exceeds the {max_size}-byte limit"
                )
            return _OpenedTextFile(descriptor=descriptor, stat_before=value)
        except FileNotFoundError as exc:
            raise DiscoveryNotFound(
                f"resource not found: {'/'.join(relative_parts)}"
            ) from exc
        except OSError as exc:
            raise UnsafeDiscoveryPath(
                f"resource could not be opened safely: {'/'.join(relative_parts)}"
            ) from exc
        finally:
            if current_fd is not None and current_fd != root_fd:
                os.close(current_fd)
            if root_fd is not None:
                os.close(root_fd)

    def _read_complete_text(self, parts: tuple[str, ...], *, max_size: int) -> str:
        opened = self._open_text_file(parts, max_size=max_size)
        try:
            size = opened.stat_before.st_size
            raw = os.pread(opened.descriptor, size + 1, 0)
            if len(raw) != size:
                raise UnsafeDiscoveryPath("resource size changed while it was read")
            if b"\x00" in raw:
                raise BinaryResourceRejected("resource contains NUL bytes")
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise BinaryResourceRejected("resource is not valid UTF-8") from exc
            stat_after = os.fstat(opened.descriptor)
            if _stat_identity(stat_after) != _stat_identity(opened.stat_before):
                raise UnsafeDiscoveryPath("resource changed while it was read")
            return text
        finally:
            os.close(opened.descriptor)

    @staticmethod
    def _validate_utf8_descriptor(descriptor: int, size: int) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        position = 0
        while position < size:
            raw = os.pread(descriptor, min(64 * 1024, size - position), position)
            if not raw:
                raise UnsafeDiscoveryPath(
                    "resource became shorter while it was inspected"
                )
            if b"\x00" in raw:
                raise BinaryResourceRejected("resource contains NUL bytes")
            try:
                decoder.decode(raw, final=False)
            except UnicodeDecodeError as exc:
                raise BinaryResourceRejected("resource is not valid UTF-8") from exc
            position += len(raw)
        try:
            decoder.decode(b"", final=True)
        except UnicodeDecodeError as exc:
            raise BinaryResourceRejected("resource is not valid UTF-8") from exc

    @staticmethod
    def _decode_bounded_chunk(raw: bytes) -> tuple[str, int]:
        candidate = raw
        while candidate:
            try:
                return candidate.decode("utf-8"), len(candidate)
            except UnicodeDecodeError as exc:
                if exc.reason == "unexpected end of data" and exc.end == len(candidate):
                    candidate = candidate[: exc.start]
                    continue
                raise BinaryResourceRejected("resource is not valid UTF-8") from exc
        return "", 0

    def _cisco_products(self) -> tuple[dict[str, Any], ...]:
        path = self.skills_dir.joinpath(*CISCO_CATALOG_PARTS)
        try:
            value = path.lstat()
        except OSError as exc:
            raise DiscoveryCatalogError(
                f"Cisco product catalog is unavailable: {exc}"
            ) from exc
        signature = (
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
        with self._cache_lock:
            if self._cisco_cache is not None and self._cisco_cache[0] == signature:
                return self._cisco_cache[1]
            text = self._read_complete_text(
                CISCO_CATALOG_PARTS, max_size=MAX_CATALOG_BYTES
            )
            payload = _load_catalog_json(text, label="Cisco product catalog")
            products = payload.get("products") if isinstance(payload, dict) else None
            if not isinstance(products, list):
                raise DiscoveryCatalogError(
                    "Cisco product catalog has no products list"
                )
            validated: list[dict[str, Any]] = []
            for index, product in enumerate(products):
                if not isinstance(product, dict):
                    raise DiscoveryCatalogError(
                        f"Cisco product products[{index}] is not an object"
                    )
                validated.append(product)
            stat_after = path.lstat()
            if (
                stat_after.st_dev,
                stat_after.st_ino,
                stat_after.st_size,
                stat_after.st_mtime_ns,
                stat_after.st_ctime_ns,
            ) != signature:
                raise DiscoveryCatalogError(
                    "Cisco product catalog changed while it was loaded"
                )
            result = tuple(validated)
            self._cisco_cache = (signature, result)
            return result

    @staticmethod
    def _display_aliases(display_name: str) -> list[str]:
        aliases = [display_name]
        no_parens = re.sub(r"\s*\([^)]*\)", "", display_name).strip()
        if no_parens and no_parens != display_name:
            aliases.append(no_parens)
        for match in re.findall(r"\(([^)]+)\)", display_name):
            aliases.append(match.strip())
            for piece in re.split(r"[/,]", match):
                piece = piece.strip()
                if piece:
                    aliases.append(piece)
        return aliases

    @staticmethod
    def _product_state_rank(product: dict[str, Any]) -> int:
        return {
            "automated": 0,
            "partial": 0,
            "manual_gap": 1,
            "unsupported_roadmap": 2,
            "unsupported_legacy": 3,
        }.get(str(product.get("automation_state", "")), 4)


_DEFAULT_DISCOVERY = SkillDiscovery()


def search_skills(
    query: str | None = None,
    product: str | None = None,
    capability: str | None = None,
    limit: int = DEFAULT_PAGE_LIMIT,
    cursor: str | None = None,
) -> SearchSkillsResult:
    """Search the default repository skill catalog."""

    return _DEFAULT_DISCOVERY.search_skills(query, product, capability, limit, cursor)


def get_skill_manifest(skill: str) -> SkillManifestResult:
    """Return the default repository manifest for one skill."""

    return _DEFAULT_DISCOVERY.get_skill_manifest(skill)


def list_skill_files(
    skill: str,
    kind: SkillFileKind,
    limit: int = DEFAULT_PAGE_LIMIT,
    cursor: str | None = None,
) -> ListSkillFilesResult:
    """List curated files for a skill in the default repository."""

    return _DEFAULT_DISCOVERY.list_skill_files(skill, kind, limit, cursor)


def read_skill_file(
    skill: str,
    path: str,
    offset: int = 0,
    max_bytes: int = DEFAULT_READ_BYTES,
) -> ReadSkillFileResult:
    """Read one bounded text page from the default repository."""

    return _DEFAULT_DISCOVERY.read_skill_file(skill, path, offset, max_bytes)


def resolve_cisco_product(query: str) -> ResolveCiscoProductResult:
    """Resolve a Cisco product from the default repository without subprocesses."""

    return _DEFAULT_DISCOVERY.resolve_cisco_product(query)
