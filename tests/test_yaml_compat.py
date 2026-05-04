"""Regression coverage for skills/shared/lib/yaml_compat.py.

The compat helper is exercised by the cisco-isovalent-platform-setup and
splunk-observability-isovalent-integration render scripts. PyYAML is preferred
when available, but the fallback parser must accept the conservative subset
those skills emit and also handle the common spec inputs operators write by
hand. These tests round-trip both paths so regressions in either are caught.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = REPO_ROOT / "skills/shared/lib"


@pytest.fixture(scope="module")
def yaml_compat():
    sys.path.insert(0, str(LIB_DIR))
    try:
        module = importlib.import_module("yaml_compat")
        yield module
    finally:
        sys.path.remove(str(LIB_DIR))


@pytest.fixture
def force_no_pyyaml(monkeypatch: pytest.MonkeyPatch):
    """Pretend PyYAML is not importable so the fallback path runs."""

    real_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
        if name == "yaml":
            raise ModuleNotFoundError("yaml stubbed out for fallback test")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)


# ---------------------------------------------------------------------------
# load_yaml_or_json: JSON
# ---------------------------------------------------------------------------


def test_load_yaml_or_json_parses_json(yaml_compat) -> None:
    payload = yaml_compat.load_yaml_or_json('{"a": 1, "nested": {"b": [1, 2]}}')
    assert payload == {"a": 1, "nested": {"b": [1, 2]}}


def test_load_yaml_or_json_pyyaml_path(yaml_compat) -> None:
    pytest.importorskip("yaml")
    text = "edition: oss\ntetragon:\n  export:\n    mode: file\n"
    payload = yaml_compat.load_yaml_or_json(text)
    assert payload == {"edition": "oss", "tetragon": {"export": {"mode": "file"}}}


def test_load_yaml_or_json_invalid_yaml_raises(yaml_compat) -> None:
    with pytest.raises(yaml_compat.YamlCompatError):
        yaml_compat.load_yaml_or_json("a:\n  - x\n - y\n")  # bad indent in list


# ---------------------------------------------------------------------------
# Fallback parser
# ---------------------------------------------------------------------------


def test_fallback_parses_isovalent_style_spec(yaml_compat, force_no_pyyaml) -> None:
    text = (
        "edition: oss\n"
        "namespace: kube-system\n"
        "tetragon:\n"
        "  export:\n"
        "    mode: file\n"
        "    directory: /var/run/cilium/tetragon\n"
        "metrics:\n"
        "  - cilium_dnsproxy\n"
        "  - tetragon\n"
        "scrape_jobs:\n"
        "  - name: cilium\n"
        "    port: 9962\n"
    )
    parsed = yaml_compat.load_yaml_or_json(text)
    assert parsed["edition"] == "oss"
    assert parsed["namespace"] == "kube-system"
    assert parsed["tetragon"]["export"]["mode"] == "file"
    assert parsed["tetragon"]["export"]["directory"] == "/var/run/cilium/tetragon"
    assert parsed["metrics"] == ["cilium_dnsproxy", "tetragon"]
    assert parsed["scrape_jobs"] == [{"name": "cilium", "port": 9962}]


def test_fallback_inline_lists_and_scalars(yaml_compat, force_no_pyyaml) -> None:
    text = (
        "empty_list: []\n"
        "empty_map: {}\n"
        "ints: [1, 2, 3]\n"
        "strings: [foo, 'b a r']\n"
        "yes_no: [yes, no, on, off]\n"
        "null_value: null\n"
        "tilde_null: ~\n"
        'literal: "1.0"\n'
    )
    parsed = yaml_compat.load_yaml_or_json(text)
    assert parsed["empty_list"] == []
    assert parsed["empty_map"] == {}
    assert parsed["ints"] == [1, 2, 3]
    assert parsed["strings"] == ["foo", "b a r"]
    # YAML 1.1 booleans must round-trip as bools (matching PyYAML safe_load).
    assert parsed["yes_no"] == [True, False, True, False]
    assert parsed["null_value"] is None
    assert parsed["tilde_null"] is None
    # Quoted "1.0" stays as a string.
    assert parsed["literal"] == "1.0"


def test_fallback_rejects_tabs_in_indent(yaml_compat, force_no_pyyaml) -> None:
    with pytest.raises(yaml_compat.YamlCompatError):
        yaml_compat.load_yaml_or_json("a:\n\t- x\n")


# ---------------------------------------------------------------------------
# Round-trip: dump_yaml + parse
# ---------------------------------------------------------------------------


def test_round_trip_dump_then_load(yaml_compat) -> None:
    payload = {
        "edition": "enterprise",
        "namespace": "kube-system",
        "metrics": ["cilium", "hubble", "tetragon"],
        "scrape_jobs": [
            {"name": "cilium", "port": 9962},
            {"name": "hubble", "port": 9965},
        ],
        "empty": [],
        "blank_value": "",
        "boolean": True,
    }
    text = yaml_compat.dump_yaml(payload)
    reparsed = yaml_compat.load_yaml_or_json(text)
    assert reparsed == payload


def test_round_trip_via_fallback(yaml_compat, force_no_pyyaml) -> None:
    payload = {
        "edition": "oss",
        "tetragon": {
            "export": {"mode": "file", "directory": "/var/run/cilium/tetragon"},
            "metrics": ["dropped", "policy", "process"],
        },
        "feature_flags": {"hubble_enterprise": False, "obi": True},
    }
    text = yaml_compat.dump_yaml(payload)
    reparsed = yaml_compat.load_yaml_or_json(text)
    assert reparsed == payload


# ---------------------------------------------------------------------------
# Real templates render through the fallback intact
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rel_path",
    [
        "skills/cisco-isovalent-platform-setup/template.example",
        "skills/splunk-observability-isovalent-integration/template.example",
    ],
)
def test_real_templates_round_trip_via_fallback(
    yaml_compat, rel_path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fallback parser must capture the same top-level keys as PyYAML."""

    pytest.importorskip("yaml")
    import yaml as _yaml  # type: ignore[import-not-found]

    template_path = REPO_ROOT / rel_path
    text = template_path.read_text(encoding="utf-8")
    parsed_pyyaml = _yaml.safe_load(text)

    # Apply the no-PyYAML monkeypatch only after we have the reference parse,
    # so the fallback parser runs but we can still compare against the real
    # PyYAML output captured above.
    real_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
        if name == "yaml":
            raise ModuleNotFoundError("yaml stubbed out for fallback test")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)

    parsed_fallback = yaml_compat.load_yaml_or_json(text)
    assert isinstance(parsed_fallback, dict)
    assert isinstance(parsed_pyyaml, dict)
    assert set(parsed_fallback.keys()) == set(parsed_pyyaml.keys())
