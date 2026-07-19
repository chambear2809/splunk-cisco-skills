#!/usr/bin/env python3
"""Canonical-only detection of bundles made by retired alias renderers."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from collections.abc import Mapping, Set
from dataclasses import dataclass
from pathlib import Path

try:
    from .skill_catalog import CatalogError, SkillCatalog, load_catalog
except ImportError:  # Imported as a top-level module by canonical renderers.
    from skill_catalog import CatalogError, SkillCatalog, load_catalog


MARKER_NAME = ".splunk-skill-bundle.json"
MARKER_SCHEMA = 2

# Optional compatibility data, keyed only by the active canonical renderer.
# The retired alias identity is derived from manifest replaced_by edges.
_BUNDLE_COMPATIBILITY: dict[str, dict[str, set[str]]] = {
    "splunk-cim-data-model-setup": {
        "canonical_files": {
            "README.md", "metadata.json", "datamodels.conf", "macros.conf",
            "eventtypes.conf", "tags.conf", "validate-tstats.sh",
        },
        "retired_alias_files": {
            "README.md", "metadata.json", "datamodels.conf", "apply.sh",
            "rebuild.sh", "status.sh", "audit.sh",
        },
    },
    "splunk-dashboard-studio-setup": {
        "canonical_files": {"README.md", "metadata.json", "dashboard.json", "view.xml"},
        "retired_alias_files": {
            "README.md", "metadata.json", "dashboard.json", "dashboard.xml",
            "apply.sh", "status.sh",
        },
    },
    "splunk-ddaa-archive-setup": {
        "canonical_files": {
            "README.md", "metadata.json", "acs-payload.json", "restore-runbook.md",
            "disable-runbook.md", "status.sh",
        },
        "retired_alias_files": {
            "README.md", "metadata.json", "create-payload.json", "patch-payload.json",
            "enable-ddaa.sh", "status.sh", "restore.sh", "audit.sh",
        },
    },
    "splunk-ingest-actions-setup": {
        "canonical_files": {
            "README.md", "metadata.json", "props.conf", "transforms.conf",
            "outputs.conf", "status-rulesets.sh",
        },
        "retired_alias_files": {
            "README.md", "metadata.json", "outputs.conf", "ruleset.json",
            "props_transforms_preview.conf", "apply.sh", "status.sh",
        },
    },
    "splunk-knowledge-objects-setup": {
        "canonical_files": {
            "README.md", "metadata.json", "savedsearches.conf", "macros.conf",
            "transforms.conf", "props.conf", "eventtypes.conf", "tags.conf",
            "acl-plan.json", "lookup-stub.csv",
        },
        "retired_alias_files": {
            "README.md", "metadata.json", "local.meta", "savedsearches.conf",
            "macros.conf", "transforms.conf", "inventory.sh", "audit.sh",
            "apply.sh", "reassign.sh",
        },
    },
    "splunk-kvstore-admin-setup": {
        "canonical_files": {
            "README.md", "metadata.json", "server.conf", "collections.conf",
            "transforms.conf", "preflight.sh", "backup.sh", "restore.sh", "clean.sh",
            "migrate.sh", "upgrade.sh", "status.sh",
        },
        "retired_alias_files": {
            "README.md", "metadata.json", "server.conf", "status.sh", "backup.sh",
            "restore.sh", "migrate.sh", "resync.sh",
        },
    },
    "splunk-secure-gateway-setup": {
        "canonical_files": {
            "README.md", "metadata.json", "instance-id-config.json",
            "egress-preflight.sh", "deployment-settings-runbook.md",
            "registration-runbook.md",
        },
        "retired_alias_files": {
            "README.md", "metadata.json", "connectivity-preflight.sh", "enable.sh",
            "register.sh", "mdm-appconfig.xml", "status.sh",
        },
    },
}


@dataclass(frozen=True)
class LegacyBundleCompatibility:
    canonical: str
    retired_alias: str
    canonical_files: frozenset[str]
    retired_alias_files: frozenset[str]

    @property
    def retired_only_files(self) -> frozenset[str]:
        return self.retired_alias_files - self.canonical_files


def _build_compatibility_contracts(
    catalog: SkillCatalog | None = None,
    extension: Mapping[str, Mapping[str, Set[str]]] | None = None,
) -> dict[str, LegacyBundleCompatibility]:
    """Validate only explicitly configured canonical/retired-bundle relationships."""

    manifest = catalog or load_catalog()
    configured = _BUNDLE_COMPATIBILITY if extension is None else extension
    aliases_by_canonical: dict[str, list[str]] = {}
    for legacy, canonical in manifest.aliases.items():
        aliases_by_canonical.setdefault(canonical, []).append(legacy)

    contracts: dict[str, LegacyBundleCompatibility] = {}
    for canonical, raw in configured.items():
        candidates = aliases_by_canonical.get(canonical, [])
        if len(candidates) != 1:
            raise CatalogError(
                f"legacy-bundle compatibility owner {canonical!r} must have exactly one "
                "manifest alias replaced_by edge"
            )
        if set(raw) != {"canonical_files", "retired_alias_files"}:
            raise CatalogError(
                f"legacy-bundle compatibility for {canonical} must contain exactly "
                "canonical_files and retired_alias_files"
            )
        canonical_files = frozenset(raw["canonical_files"])
        retired_files = frozenset(raw["retired_alias_files"])
        if not canonical_files or not retired_files:
            raise CatalogError(
                f"legacy-bundle compatibility for {canonical} has a half/empty contract"
            )
        if not retired_files - canonical_files:
            raise CatalogError(
                f"legacy-bundle compatibility for {canonical} has no retired-only files"
            )
        contracts[canonical] = LegacyBundleCompatibility(
            canonical=canonical,
            retired_alias=candidates[0],
            canonical_files=canonical_files,
            retired_alias_files=retired_files,
        )
    return contracts


_COMPATIBILITY = _build_compatibility_contracts()


def compatibility_contract(canonical: str) -> LegacyBundleCompatibility:
    """Return one active renderer's retired-bundle compatibility contract."""

    try:
        return _COMPATIBILITY[canonical]
    except KeyError as exc:
        raise KeyError(
            f"no legacy-bundle compatibility contract is registered for {canonical!r}"
        ) from exc


def _read_marker(path: Path) -> dict[str, object]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise SystemExit(
                f"ERROR: bundle marker must be a regular, single-link file: {path}"
            )
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            descriptor = -1
            try:
                payload = json.load(stream)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise SystemExit(f"ERROR: invalid bundle marker {path}: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(payload, dict):
        raise SystemExit(f"ERROR: bundle marker must contain an object: {path}")
    return payload


def _write_marker(path: Path, contract: LegacyBundleCompatibility) -> None:
    payload = {
        "schema": MARKER_SCHEMA,
        "canonical_owner": contract.canonical,
        "retired_alias": contract.retired_alias,
    }
    content = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    published = False
    try:
        os.fchmod(descriptor, 0o600)
        offset = 0
        while offset < len(content):
            written = os.write(descriptor, content[offset:])
            if written <= 0:
                raise OSError("short write while preparing bundle marker")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.link(temporary, path, follow_symlinks=False)
        published = True
        temporary.unlink()
        directory_descriptor = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except BaseException:
        if published:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            try:
                cleanup_directory = os.open(
                    path.parent,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
                )
                try:
                    os.fsync(cleanup_directory)
                finally:
                    os.close(cleanup_directory)
            except OSError:
                pass
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _validate_marker(
    marker: Path,
    contract: LegacyBundleCompatibility,
) -> None:
    payload = _read_marker(marker)
    # Accept markers emitted by the previous canonical renderer, but never a
    # marker claiming the retired alias as owner.
    if payload.get("schema") == 1:
        owner = payload.get("owner")
        peer = payload.get("incompatible_peer")
        if owner == contract.retired_alias:
            raise SystemExit(
                f"ERROR: bundle is owned by retired alias '{contract.retired_alias}', "
                f"not canonical '{contract.canonical}'; use a new --output-dir."
            )
        if owner == contract.canonical and peer == contract.retired_alias:
            return
    if (
        payload.get("schema") != MARKER_SCHEMA
        or payload.get("canonical_owner") != contract.canonical
        or payload.get("retired_alias") != contract.retired_alias
    ):
        raise SystemExit(
            f"ERROR: bundle marker is not owned by canonical '{contract.canonical}'; "
            "use a new --output-dir."
        )


def ensure_canonical_bundle_compatible(
    render_dir: Path,
    *,
    canonical: str,
    generated_files: Set[str],
    write: bool,
) -> None:
    """Reject retired/mixed bundles before a canonical renderer cleans files."""

    contract = compatibility_contract(canonical)
    if frozenset(generated_files) != contract.canonical_files:
        raise SystemExit(
            f"ERROR: canonical generated-file contract drift for '{canonical}'."
        )
    if render_dir.is_symlink() or (render_dir.exists() and not render_dir.is_dir()):
        raise SystemExit(
            f"ERROR: render path must be a real directory, not a link or file: {render_dir}"
        )
    marker = render_dir / MARKER_NAME
    if marker.exists() or marker.is_symlink():
        _validate_marker(marker, contract)
    retired = sorted(
        name
        for name in contract.retired_only_files
        if (render_dir / name).exists() or (render_dir / name).is_symlink()
    )
    if retired:
        raise SystemExit(
            f"ERROR: bundle contains files from retired alias '{contract.retired_alias}': "
            f"{', '.join(retired)}. Use a new --output-dir; no files were deleted."
        )
    if write and not marker.exists():
        render_dir.mkdir(parents=True, exist_ok=True)
        try:
            _write_marker(marker, contract)
        except FileExistsError:
            _validate_marker(marker, contract)
