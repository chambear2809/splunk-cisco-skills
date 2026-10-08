"""Exercise version and quantity parsing in generated Kubernetes guards."""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/splunk-enterprise-kubernetes-setup/scripts"


def generated_function(assignment: str, function: str):
    tree = ast.parse((SCRIPTS / "render_assets.py").read_text())
    code = next(
        ast.literal_eval(node.value) for node in ast.walk(tree)
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == assignment
            for target in node.targets
        )
    )
    definition = next(
        node for node in ast.parse(code).body
        if isinstance(node, ast.FunctionDef) and node.name == function
    )
    namespace = {"re": re, "Decimal": Decimal, "InvalidOperation": InvalidOperation}
    exec(compile(ast.Module(body=[definition], type_ignores=[]), "generated-guard", "exec"), namespace)
    return namespace[function]


def test_upgrade_guard_compares_four_part_images_and_older_three_part_tags() -> None:
    numeric = generated_function("live_upgrade_guard_code", "numeric")
    assert numeric("splunk/splunk:10.6.0.5") == (10, 6, 0, 5)
    assert numeric("splunk/splunk:10.6.0.4@sha256:abc") < numeric("image:10.6.0.5")
    assert numeric("splunk/splunk:10.4.1") == numeric("splunk/splunk:10.4.1.0")
    assert numeric("splunk/splunk:10.6.0.5.9") is None


def test_four_part_splunk_format_does_not_certify_four_part_operator_or_kubernetes() -> None:
    spec = importlib.util.spec_from_file_location("review_k8s_compatibility", SCRIPTS / "compatibility.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        assert module.check_sok_compatibility("3.2.0", "10.6.0.5", "1.36.0").supported
        assert not module.check_sok_compatibility("3.2.0.99", "10.6.0.5", "1.36.0").supported
        assert not module.check_sok_compatibility("3.2.0", "10.6.0.5", "1.36.0.99").supported
        assert not module.check_sok_compatibility("3.2.0", "10.6.0.5", "1.31.0").supported
        for splunk_version in ("10.3.0", "10.5.0", "10.6.0.6", "9.4.14"):
            assert not module.check_sok_compatibility(
                "3.2.0", splunk_version, "1.36.0"
            ).supported
        for splunk_version in ("9.4.15", "10.0.0", "10.2.0", "10.4.0", "10.6.0.5"):
            assert module.check_sok_compatibility(
                "3.2.0", splunk_version, "1.36.0", indexing_ingestion_separation=True
            ).supported
    finally:
        sys.modules.pop(spec.name, None)


def test_operator_resources_accept_equivalent_exponent_quantities_and_reject_drift() -> None:
    normalize = generated_function("operator_contract_code", "normalized_resources")
    raw = {"requests": {"cpu": "1000m", "memory": "1e3"}}
    equivalent = {"requests": {"cpu": "1e0", "memory": "1E+3"}}
    assert normalize(raw) == normalize(equivalent)
    assert normalize(raw) != normalize({"requests": {"cpu": "1", "memory": "1001"}})
    with pytest.raises(SystemExit):
        normalize({"requests": {"cpu": "invalid"}})
