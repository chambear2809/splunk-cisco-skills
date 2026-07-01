#!/usr/bin/env python3
"""Shared host apply helpers for AppDynamics production host skills."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import shlex
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SECRET_MARKERS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_key",
    "client_secret",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def redacted(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower().replace("-", "_")
            if item is None:
                result[key] = None
            elif lowered.endswith("_file") or lowered.endswith("_path"):
                result[key] = str(item)
            elif any(marker in lowered for marker in SECRET_MARKERS):
                result[key] = "<redacted>"
            else:
                result[key] = redacted(item)
        return result
    if isinstance(value, list):
        return [redacted(item) for item in value]
    if isinstance(value, str):
        if "Bearer " in value or "x-api-key" in value.lower():
            return "<redacted>"
    return value


def json_dumps(payload: Any) -> str:
    return json.dumps(redacted(payload), indent=2, sort_keys=True) + "\n"


def sanitize_path(path: str) -> str:
    safe = path.strip().replace("\\", "_").replace("/", "_").replace(":", "_")
    return safe.strip("_") or "root"


def shell_join(command: str | list[str]) -> str:
    if isinstance(command, str):
        return command
    return shlex.join(str(item) for item in command)


def target_display(target: dict[str, Any]) -> str:
    return str(target.get("name") or target.get("host") or "local")


def execution_mode(target: dict[str, Any]) -> str:
    return str(target.get("execution") or "local").strip().lower()


def target_sudo(target: dict[str, Any], sudo: bool | None = None) -> bool:
    if sudo is not None:
        return sudo
    value = target.get("sudo", False)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def build_ssh_command(target: dict[str, Any], remote_command: str | list[str], sudo: bool = False) -> list[str]:
    host = str(target.get("host") or "")
    if not host:
        raise ValueError("SSH target requires host")
    user = str(target.get("ssh_user") or target.get("user") or "")
    destination = f"{user}@{host}" if user else host
    command = shell_join(remote_command)
    wrapped = f"bash -lc {shlex.quote(command)}"
    if sudo:
        wrapped = f"sudo -n bash -lc {shlex.quote(command)}"
    argv = ["ssh", "-o", "BatchMode=yes"]
    key_file = target.get("ssh_key_file")
    if key_file:
        argv.extend(["-i", str(key_file)])
    known_hosts = target.get("ssh_known_hosts_file")
    if known_hosts:
        argv.extend(["-o", f"UserKnownHostsFile={known_hosts}", "-o", "StrictHostKeyChecking=yes"])
    else:
        argv.extend(["-o", "StrictHostKeyChecking=accept-new"])
    argv.extend([destination, wrapped])
    return argv


def build_scp_command(target: dict[str, Any], local_path: Path, remote_path: str) -> list[str]:
    host = str(target.get("host") or "")
    if not host:
        raise ValueError("SSH target requires host")
    user = str(target.get("ssh_user") or target.get("user") or "")
    destination = f"{user}@{host}:{remote_path}" if user else f"{host}:{remote_path}"
    argv = ["scp", "-q"]
    key_file = target.get("ssh_key_file")
    if key_file:
        argv.extend(["-i", str(key_file)])
    known_hosts = target.get("ssh_known_hosts_file")
    if known_hosts:
        argv.extend(["-o", f"UserKnownHostsFile={known_hosts}", "-o", "StrictHostKeyChecking=yes"])
    else:
        argv.extend(["-o", "StrictHostKeyChecking=accept-new"])
    argv.extend([str(local_path), destination])
    return argv


@dataclass
class CommandResult:
    target: str
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    started_at: str
    finished_at: str
    label: str = ""

    def to_report(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "label": self.label,
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class HostExecutor:
    def __init__(self, target: dict[str, Any], output_dir: Path):
        self.target = target
        self.output_dir = output_dir

    def run(self, command: str | list[str], *, sudo: bool | None = None, label: str = "") -> CommandResult:
        started = utc_now()
        if execution_mode(self.target) == "ssh":
            argv = build_ssh_command(self.target, command, sudo=target_sudo(self.target, sudo))
        else:
            local_command = shell_join(command)
            argv = ["bash", "-lc", local_command]
            if target_sudo(self.target, sudo):
                argv = ["sudo", "-n", *argv]
        proc = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=300)
        return CommandResult(
            target=target_display(self.target),
            command=argv,
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            started_at=started,
            finished_at=utc_now(),
            label=label,
        )

    def read_secret_file(self, path: str, *, sudo: bool | None = None, label: str = "secret file") -> str:
        """Read a one-line target-side secret without adding its value to an apply report."""
        quoted = shlex.quote(path)
        mode_command = (
            f"mode=$(stat -c '%a' {quoted} 2>/dev/null || stat -f '%Lp' {quoted} 2>/dev/null) && "
            'test "$mode" = 600'
        )
        mode_result = self.run(mode_command, sudo=sudo, label=f"validate {label} permissions")
        if mode_result.exit_code != 0:
            raise RuntimeError(f"{target_display(self.target)}: {label} must exist and be chmod 600: {path}")

        if execution_mode(self.target) == "ssh":
            argv = build_ssh_command(self.target, f"cat {quoted}", sudo=target_sudo(self.target, sudo))
        else:
            argv = ["bash", "-lc", f"cat {quoted}"]
            if target_sudo(self.target, sudo):
                argv = ["sudo", "-n", *argv]
        proc = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=30)
        if proc.returncode != 0:
            raise RuntimeError(f"{target_display(self.target)}: could not read {label}: {path}")
        value = proc.stdout.rstrip("\r\n")
        if not value or "\n" in value or "\r" in value or "\x00" in value:
            raise RuntimeError(f"{target_display(self.target)}: {label} must contain exactly one non-empty line")
        return value

    def atomic_write(
        self,
        destination: str,
        content: str | bytes,
        *,
        backup_dir: Path,
        mode: int = 0o644,
        sudo: bool | None = None,
        label: str = "",
    ) -> dict[str, Any]:
        payload = content.encode("utf-8") if isinstance(content, str) else content
        if execution_mode(self.target) == "ssh":
            return self._atomic_write_ssh(destination, payload, backup_dir=backup_dir, mode=mode, sudo=target_sudo(self.target, sudo), label=label)
        return self._atomic_write_local(destination, payload, backup_dir=backup_dir, mode=mode, sudo=target_sudo(self.target, sudo), label=label)

    def _atomic_write_local(
        self,
        destination: str,
        payload: bytes,
        *,
        backup_dir: Path,
        mode: int,
        sudo: bool,
        label: str,
    ) -> dict[str, Any]:
        path = Path(destination)
        backup_dir.mkdir(parents=True, exist_ok=True)
        new_sha = sha256_bytes(payload)
        if sudo:
            probe = self.run(
                f"test -f {shlex.quote(str(path))} && sha256sum {shlex.quote(str(path))} | awk '{{print $1}}' || true",
                sudo=True,
                label=f"probe {label}".strip(),
            )
            if probe.exit_code != 0:
                raise RuntimeError(f"checksum probe failed for {path}: {probe.stderr}")
            before_sha = probe.stdout.strip() or None
            existed = before_sha is not None
        else:
            existed = path.exists()
            before_sha = sha256_file(path) if existed else None
        backup_path: Path | None = None
        sudo_verified_sha: str | None = None
        if existed and before_sha == new_sha:
            return {
                "target": target_display(self.target),
                "label": label,
                "path": str(path),
                "backup_path": None,
                "before_sha256": before_sha,
                "after_sha256": new_sha,
                "changed": False,
                "action": "noop",
            }
        if sudo:
            backup_path = backup_dir / f"{sanitize_path(str(path))}.{uuid.uuid4().hex}.bak"
            if existed:
                result = self.run(f"cp -p {shlex.quote(str(path))} {shlex.quote(str(backup_path))}", sudo=True, label=f"backup {label}".strip())
                if result.exit_code != 0:
                    raise RuntimeError(f"backup failed for {path}: {result.stderr}")
            stage = f"{path}.codex-stage-{uuid.uuid4().hex}"
            with tempfile.NamedTemporaryFile(dir=str(backup_dir), delete=False) as local_stage:
                local_stage.write(payload)
                local_stage_path = Path(local_stage.name)
            try:
                install = self.run(
                    f"install -D -m {mode:o} {shlex.quote(str(local_stage_path))} {shlex.quote(stage)} && mv {shlex.quote(stage)} {shlex.quote(str(path))}",
                    sudo=True,
                    label=f"write {label}".strip(),
                )
                if install.exit_code != 0:
                    raise RuntimeError(f"atomic write failed for {path}: {install.stderr}")
                verify = self.run(f"sha256sum {shlex.quote(str(path))} | awk '{{print $1}}'", sudo=True, label=f"verify {label}".strip())
                if verify.exit_code != 0 or verify.stdout.strip() != new_sha:
                    raise RuntimeError(f"checksum mismatch after writing {path}")
                sudo_verified_sha = verify.stdout.strip()
            finally:
                local_stage_path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            if existed:
                backup_path = backup_dir / f"{sanitize_path(str(path))}.{uuid.uuid4().hex}.bak"
                shutil.copy2(path, backup_path)
            fd, stage_name = tempfile.mkstemp(prefix=f".{path.name}.codex-stage-", dir=str(path.parent))
            stage = Path(stage_name)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(payload)
                os.chmod(stage, mode)
                os.replace(stage, path)
            finally:
                stage.unlink(missing_ok=True)
        after_sha = sudo_verified_sha if sudo else sha256_file(path)
        if after_sha != new_sha:
            raise RuntimeError(f"checksum mismatch after writing {path}")
        return {
            "target": target_display(self.target),
            "label": label,
            "path": str(path),
            "backup_path": str(backup_path) if backup_path else None,
            "before_sha256": before_sha,
            "after_sha256": after_sha,
            "changed": True,
            "action": "write",
        }

    def _atomic_write_ssh(
        self,
        destination: str,
        payload: bytes,
        *,
        backup_dir: Path,
        mode: int,
        sudo: bool,
        label: str,
    ) -> dict[str, Any]:
        backup_dir.mkdir(parents=True, exist_ok=True)
        new_sha = sha256_bytes(payload)
        remote_stage = f"/tmp/appd-codex-stage-{uuid.uuid4().hex}"
        remote_backup = f"{destination}.codex-backup-{uuid.uuid4().hex}"
        local_stage = backup_dir / f"ssh-stage-{uuid.uuid4().hex}"
        local_stage.write_bytes(payload)
        try:
            scp = subprocess.run(
                build_scp_command(self.target, local_stage, remote_stage),
                capture_output=True,
                text=True,
                check=False,
                timeout=300,
            )
            if scp.returncode != 0:
                raise RuntimeError(f"scp failed for {destination}: {scp.stderr}")
            checksum = self.run(f"sha256sum {shlex.quote(remote_stage)} | awk '{{print $1}}'", label=f"stage checksum {label}".strip())
            if checksum.exit_code != 0 or checksum.stdout.strip() != new_sha:
                raise RuntimeError(f"remote staging checksum mismatch for {destination}")
            probe = self.run(f"test -f {shlex.quote(destination)} && sha256sum {shlex.quote(destination)} | awk '{{print $1}}' || true", sudo=sudo, label=f"probe {label}".strip())
            before_sha = probe.stdout.strip() or None
            if before_sha == new_sha:
                self.run(f"rm -f {shlex.quote(remote_stage)}", sudo=False, label=f"cleanup {label}".strip())
                return {
                    "target": target_display(self.target),
                    "label": label,
                    "path": destination,
                    "backup_path": None,
                    "before_sha256": before_sha,
                    "after_sha256": new_sha,
                    "changed": False,
                    "action": "noop",
                }
            if before_sha:
                backup = self.run(f"cp -p {shlex.quote(destination)} {shlex.quote(remote_backup)}", sudo=sudo, label=f"backup {label}".strip())
                if backup.exit_code != 0:
                    raise RuntimeError(f"remote backup failed for {destination}: {backup.stderr}")
            install = self.run(
                f"install -D -m {mode:o} {shlex.quote(remote_stage)} {shlex.quote(destination)} && rm -f {shlex.quote(remote_stage)}",
                sudo=sudo,
                label=f"write {label}".strip(),
            )
            if install.exit_code != 0:
                raise RuntimeError(f"remote write failed for {destination}: {install.stderr}")
            verify = self.run(f"sha256sum {shlex.quote(destination)} | awk '{{print $1}}'", sudo=sudo, label=f"verify {label}".strip())
            if verify.exit_code != 0 or verify.stdout.strip() != new_sha:
                raise RuntimeError(f"remote checksum mismatch after writing {destination}")
        finally:
            local_stage.unlink(missing_ok=True)
        return {
            "target": target_display(self.target),
            "label": label,
            "path": destination,
            "backup_path": remote_backup if before_sha else None,
            "before_sha256": before_sha,
            "after_sha256": new_sha,
            "changed": True,
            "action": "write",
        }


class ApplyRecorder:
    def __init__(self, output_dir: Path, skill: str, phase: str):
        self.output_dir = output_dir
        self.skill = skill
        self.phase = phase
        self.backup_dir = output_dir / "backups"
        self.commands: list[dict[str, Any]] = []
        self.files: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self.secret_values: set[str] = set()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def executor(self, target: dict[str, Any]) -> HostExecutor:
        return HostExecutor(target, self.output_dir)

    def record_command(self, result: CommandResult) -> None:
        for secret in self.secret_values:
            if secret:
                result.stdout = result.stdout.replace(secret, "<redacted>")
                result.stderr = result.stderr.replace(secret, "<redacted>")
                result.command = [part.replace(secret, "<redacted>") for part in result.command]
        self.commands.append(result.to_report())
        if result.exit_code != 0:
            self.errors.append(f"{result.target}: command failed ({result.label or shell_join(result.command)}): exit {result.exit_code}")

    def run(self, target: dict[str, Any], command: str | list[str], *, sudo: bool | None = None, label: str = "") -> CommandResult:
        result = self.executor(target).run(command, sudo=sudo, label=label)
        self.record_command(result)
        return result

    def write_text(self, target: dict[str, Any], path: str, content: str, *, mode: int = 0o644, sudo: bool | None = None, label: str = "") -> dict[str, Any]:
        entry = self.executor(target).atomic_write(path, content, backup_dir=self.backup_dir, mode=mode, sudo=sudo, label=label)
        self.files.append(entry)
        return entry

    def read_secret_file(self, target: dict[str, Any], path: str, *, sudo: bool | None = None, label: str = "secret file") -> str:
        value = self.executor(target).read_secret_file(path, sudo=sudo, label=label)
        self.secret_values.add(value)
        return value

    def manifest(self) -> dict[str, Any]:
        return {
            "version": 1,
            "skill": self.skill,
            "phase": self.phase,
            "created_at": utc_now(),
            "files": self.files,
        }

    def report(self, status: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "version": 1,
            "status": status,
            "skill": self.skill,
            "phase": self.phase,
            "created_at": utc_now(),
            "files": self.files,
            "commands": self.commands,
            "errors": self.errors,
        }
        if extra:
            payload.update(extra)
        return payload

    def write_outputs(self, status: str, rollback_plan: str, extra: dict[str, Any] | None = None) -> None:
        (self.output_dir / "backup-manifest.json").write_text(json_dumps(self.manifest()), encoding="utf-8")
        (self.output_dir / "apply-report.json").write_text(json_dumps(self.report(status, extra)), encoding="utf-8")
        rollback_path = self.output_dir / "rollback-plan.sh"
        rollback_path.write_text(rollback_plan, encoding="utf-8")
        os.chmod(rollback_path, os.stat(rollback_path).st_mode | 0o100)


def restore_entry(entry: dict[str, Any], target: dict[str, Any], output_dir: Path) -> CommandResult | None:
    backup_path = entry.get("backup_path")
    path = entry.get("path")
    if not path:
        return None
    if entry.get("changed") is False or entry.get("action") == "noop":
        return None
    executor = HostExecutor(target, output_dir)
    if not backup_path:
        return executor.run(f"rm -f {shlex.quote(str(path))}", sudo=target_sudo(target), label=f"rollback remove {entry.get('label', '')}".strip())
    if execution_mode(target) == "ssh":
        return executor.run(f"cp -p {shlex.quote(str(backup_path))} {shlex.quote(str(path))}", sudo=target_sudo(target), label=f"rollback restore {entry.get('label', '')}".strip())
    source = Path(str(backup_path))
    if target_sudo(target):
        return executor.run(f"cp -p {shlex.quote(str(source))} {shlex.quote(str(path))}", sudo=True, label=f"rollback restore {entry.get('label', '')}".strip())
    shutil.copy2(source, Path(str(path)))
    return CommandResult(
        target=target_display(target),
        command=["cp", "-p", str(source), str(path)],
        exit_code=0,
        stdout="",
        stderr="",
        started_at=utc_now(),
        finished_at=utc_now(),
        label=f"rollback restore {entry.get('label', '')}".strip(),
    )
