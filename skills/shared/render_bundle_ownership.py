#!/usr/bin/env python3
"""Fail-closed ownership checks for render directories shared by legacy skills."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

MARKER_NAME = ".splunk-skill-bundle.json"
MARKER_SCHEMA = 1

_PAIRS = {
    "splunk-cim-data-model": (
        "splunk-cim-data-model-setup",
        {"README.md", "metadata.json", "datamodels.conf", "apply.sh", "rebuild.sh", "status.sh", "audit.sh"},
        {"README.md", "metadata.json", "datamodels.conf", "macros.conf", "eventtypes.conf", "tags.conf", "validate-tstats.sh"},
    ),
    "splunk-dashboard-studio": (
        "splunk-dashboard-studio-setup",
        {"README.md", "metadata.json", "dashboard.json", "dashboard.xml", "apply.sh", "status.sh"},
        {"README.md", "metadata.json", "dashboard.json", "view.xml"},
    ),
    "splunk-ddaa-archive": (
        "splunk-ddaa-archive-setup",
        {"README.md", "metadata.json", "create-payload.json", "patch-payload.json", "enable-ddaa.sh", "status.sh", "restore.sh", "audit.sh"},
        {"README.md", "metadata.json", "acs-payload.json", "restore-runbook.md", "disable-runbook.md", "status.sh"},
    ),
    "splunk-ingest-actions": (
        "splunk-ingest-actions-setup",
        {"README.md", "metadata.json", "outputs.conf", "ruleset.json", "props_transforms_preview.conf", "apply.sh", "status.sh"},
        {"README.md", "metadata.json", "props.conf", "transforms.conf", "outputs.conf", "status-rulesets.sh"},
    ),
    "splunk-knowledge-objects": (
        "splunk-knowledge-objects-setup",
        {"README.md", "metadata.json", "local.meta", "savedsearches.conf", "macros.conf", "transforms.conf", "inventory.sh", "audit.sh", "apply.sh", "reassign.sh"},
        {"README.md", "metadata.json", "savedsearches.conf", "macros.conf", "transforms.conf", "props.conf", "eventtypes.conf", "tags.conf", "acl-plan.json", "lookup-stub.csv"},
    ),
    "splunk-kvstore-admin": (
        "splunk-kvstore-admin-setup",
        {"README.md", "metadata.json", "server.conf", "status.sh", "backup.sh", "restore.sh", "migrate.sh", "resync.sh"},
        {"README.md", "metadata.json", "server.conf", "collections.conf", "transforms.conf", "preflight.sh", "backup.sh", "restore.sh", "clean.sh", "migrate.sh", "upgrade.sh", "status.sh"},
    ),
    "splunk-secure-gateway": (
        "splunk-secure-gateway-setup",
        {"README.md", "metadata.json", "connectivity-preflight.sh", "enable.sh", "register.sh", "mdm-appconfig.xml", "status.sh"},
        {"README.md", "metadata.json", "instance-id-config.json", "egress-preflight.sh", "deployment-settings-runbook.md", "registration-runbook.md"},
    ),
}

for _owner, (_peer, _files, _peer_files) in tuple(_PAIRS.items()):
    _PAIRS[_peer] = (_owner, _peer_files, _files)


def bundle_contract(owner: str) -> tuple[str, frozenset[str]]:
    """Return the incompatible peer and registered generated-file set."""

    try:
        peer_owner, generated_files, _ = _PAIRS[owner]
    except KeyError as exc:
        raise KeyError(f"no render-bundle ownership contract is registered for '{owner}'") from exc
    return peer_owner, frozenset(generated_files)


def _read_marker(marker: Path) -> dict[str, object]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(marker, flags)
    except OSError as exc:
        raise SystemExit(f"ERROR: cannot safely open bundle ownership marker {marker}: {exc}") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise SystemExit(
                f"ERROR: bundle ownership marker must be a regular, single-link file: {marker}"
            )
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = -1
            try:
                payload = json.load(stream)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise SystemExit(f"ERROR: invalid bundle ownership marker {marker}: {exc}") from exc
    finally:
        if fd >= 0:
            os.close(fd)
    if not isinstance(payload, dict):
        raise SystemExit(f"ERROR: bundle ownership marker must contain a JSON object: {marker}")
    return payload


def _write_marker(marker: Path, owner: str, peer_owner: str) -> None:
    """Claim a previously unowned directory without replacing another claim."""

    payload = {
        "schema": MARKER_SCHEMA,
        "owner": owner,
        "incompatible_peer": peer_owner,
    }
    content = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = -1
    try:
        fd = os.open(marker, flags, 0o600)
        offset = 0
        while offset < len(content):
            written = os.write(fd, content[offset:])
            if written <= 0:
                raise OSError("short write while claiming render bundle")
            offset += written
        os.fsync(fd)
        os.close(fd)
        fd = -1
        directory_fd = os.open(marker.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if fd >= 0:
            os.close(fd)


def _foreign_peer_artifacts(
    render_dir: Path,
    generated_files: set[str],
    peer_generated_files: set[str],
) -> list[str]:
    peer_only = peer_generated_files - generated_files
    return sorted(
        name
        for name in peer_only
        if (render_dir / name).exists() or (render_dir / name).is_symlink()
    )


def _refuse_foreign_artifacts(
    render_dir: Path,
    *,
    owner: str,
    peer_owner: str,
    generated_files: set[str],
    peer_generated_files: set[str],
) -> None:
    foreign = _foreign_peer_artifacts(
        render_dir,
        generated_files,
        peer_generated_files,
    )
    if foreign:
        ownership = (
            f"unowned render bundle {render_dir}"
            if owner == "unowned"
            else f"render bundle {render_dir} owned by '{owner}'"
        )
        raise SystemExit(
            f"ERROR: {ownership} contains artifacts "
            f"unique to '{peer_owner}': {', '.join(foreign)}. Use a different "
            "--output-dir or remove the entire stale bundle after review."
        )


def ensure_bundle_owner(
    render_dir: Path,
    *,
    owner: str,
    write: bool,
) -> None:
    """Validate or claim a render directory without deleting peer-owned artifacts."""

    try:
        peer_owner, generated_files, peer_generated_files = _PAIRS[owner]
    except KeyError as exc:
        raise SystemExit(f"ERROR: no render-bundle ownership contract is registered for '{owner}'.") from exc

    if render_dir.is_symlink() or (render_dir.exists() and not render_dir.is_dir()):
        raise SystemExit(f"ERROR: render path must be a real directory, not a link or file: {render_dir}")

    marker = render_dir / MARKER_NAME
    if marker.exists() or marker.is_symlink():
        payload = _read_marker(marker)
        marker_owner = payload.get("owner")
        marker_schema = payload.get("schema")
        marker_peer = payload.get("incompatible_peer")
        if marker_schema != MARKER_SCHEMA or marker_owner != owner or marker_peer != peer_owner:
            shown_owner = marker_owner if isinstance(marker_owner, str) else "unknown"
            raise SystemExit(
                f"ERROR: render bundle {render_dir} is owned by '{shown_owner}', not '{owner}'. "
                "Use a different --output-dir or remove the entire stale bundle after review."
            )
        _refuse_foreign_artifacts(
            render_dir,
            owner=owner,
            peer_owner=peer_owner,
            generated_files=generated_files,
            peer_generated_files=peer_generated_files,
        )
        return

    if render_dir.is_dir():
        _refuse_foreign_artifacts(
            render_dir,
            owner="unowned",
            peer_owner=peer_owner,
            generated_files=generated_files,
            peer_generated_files=peer_generated_files,
        )

    if write:
        render_dir.mkdir(parents=True, exist_ok=True)
        try:
            _write_marker(marker, owner, peer_owner)
        except FileExistsError:
            # Another renderer won the claim race. Read its completed claim
            # without replacing it; a partial/incompatible marker fails closed.
            payload = _read_marker(marker)
            if (
                payload.get("schema") != MARKER_SCHEMA
                or payload.get("owner") != owner
                or payload.get("incompatible_peer") != peer_owner
            ):
                shown_owner = payload.get("owner")
                if not isinstance(shown_owner, str):
                    shown_owner = "unknown"
                raise SystemExit(
                    f"ERROR: render bundle {render_dir} was concurrently claimed by "
                    f"'{shown_owner}', not '{owner}'. Use a different --output-dir."
                ) from None
        _refuse_foreign_artifacts(
            render_dir,
            owner=owner,
            peer_owner=peer_owner,
            generated_files=generated_files,
            peer_generated_files=peer_generated_files,
        )
