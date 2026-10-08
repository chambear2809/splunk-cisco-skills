"""Focused regression tests for Galileo generated project deletion."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/galileo-platform-setup/scripts/galileo_object_lifecycle.py"
spec = importlib.util.spec_from_file_location("galileo_object_lifecycle_generated_delete", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Response:
    def __init__(self, status_code: int):
        self.status_code = status_code


def install_fake_generated_api(monkeypatch, status_code: int, calls: list[tuple[str, object]]) -> None:
    config = types.ModuleType("galileo.config")
    config.GalileoPythonConfig = types.SimpleNamespace(
        get=lambda: types.SimpleNamespace(api_client="verified-client")
    )
    generated = types.ModuleType(
        "galileo.resources.api.projects.delete_project_projects_project_id_delete"
    )
    generated.sync_detailed = lambda *, project_id, client: (
        calls.append((project_id, client)) or Response(status_code)
    )
    projects = types.ModuleType("galileo.resources.api.projects")
    projects.delete_project_projects_project_id_delete = generated
    resources_api = types.ModuleType("galileo.resources.api")
    resources_api.projects = projects
    resources = types.ModuleType("galileo.resources")
    resources.api = resources_api
    galileo = types.ModuleType("galileo")
    galileo.config = config
    galileo.resources = resources
    monkeypatch.setitem(sys.modules, "galileo", galileo)
    monkeypatch.setitem(sys.modules, "galileo.config", config)
    monkeypatch.setitem(sys.modules, "galileo.resources", resources)
    monkeypatch.setitem(sys.modules, "galileo.resources.api", resources_api)
    monkeypatch.setitem(sys.modules, "galileo.resources.api.projects", projects)
    monkeypatch.setitem(sys.modules, generated.__name__, generated)


def test_delete_project_uses_generated_api_and_exact_id(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []
    install_fake_generated_api(monkeypatch, 200, calls)
    reads = iter([{"id": "project-id"}, None])
    monkeypatch.setattr(module, "_get_project_rest", lambda **_: next(reads))

    assert module.delete_project_compat(project_id="project-id") == "generated_project_delete_api"
    assert calls == [("project-id", "verified-client")]


def test_delete_project_non_200_fails_closed(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []
    install_fake_generated_api(monkeypatch, 500, calls)
    monkeypatch.setattr(module, "_get_project_rest", lambda **_: {"id": "project-id"})

    with pytest.raises(RuntimeError, match="HTTP 500"):
        module.delete_project_compat(project_id="project-id")
    assert calls == [("project-id", "verified-client")]


def test_delete_project_absence_skips_generated_api(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []
    install_fake_generated_api(monkeypatch, 200, calls)
    monkeypatch.setattr(module, "_get_project_rest", lambda **_: None)

    assert module.delete_project_compat(project_id="project-id") == "already_absent_verified"
    assert calls == []
