"""Regression coverage for shared WideField setup helpers."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
WIDEFIELD_PARENT = REPO_ROOT / "skills/widefield-security-setup/scripts/setup.sh"
WIDEFIELD_OKTA = REPO_ROOT / "skills/widefield-okta-integration-setup/scripts/setup.sh"
WIDEFIELD_SAVIYNT = REPO_ROOT / "skills/widefield-saviynt-integration-setup/scripts/setup.sh"
WIDEFIELD_GOOGLE = REPO_ROOT / "skills/widefield-google-secops-setup/scripts/setup.sh"


def run_cmd(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


def test_widefield_setup_spec_values_override_render_defaults(tmp_path: Path) -> None:
    spec = tmp_path / "widefield.yaml"
    output_dir = tmp_path / "rendered"
    spec.write_text(
        """
splunk:
  index: custom_widefield
  sourcetype: custom:widefield
  hec_source: custom_source
  hec_token_name: custom_hec
okta:
  org_url: https://example.okta.com
  receiver_url: https://widefield.example.com/okta/events
google_secops:
  project: customer-project
  region: eu
  feed_name: custom-feed
evidence_file: ./widefield-evidence.local.json
children: okta,splunk
""".strip()
        + "\n",
        encoding="utf-8",
    )

    run_cmd(
        "bash",
        str(WIDEFIELD_PARENT),
        "--render",
        "--spec",
        str(spec),
        "--output-dir",
        str(output_dir),
        "--json",
    )

    rendered = output_dir / "widefield-security-setup"
    metadata = json.loads((rendered / "metadata.json").read_text(encoding="utf-8"))
    searches = (rendered / "validation-searches.spl").read_text(encoding="utf-8")
    feed = json.loads((rendered / "google-secops-feed.json").read_text(encoding="utf-8"))

    assert metadata["defaults"]["index"] == "custom_widefield"
    assert metadata["defaults"]["sourcetype"] == "custom:widefield"
    assert metadata["defaults"]["hec_source"] == "custom_source"
    assert metadata["defaults"]["hec_token_name"] == "custom_hec"
    assert metadata["inputs"]["okta_org_url"] == "https://example.okta.com"
    assert metadata["inputs"]["receiver_url"] == "https://widefield.example.com/okta/events"
    assert metadata["inputs"]["children"] == ["okta", "splunk"]
    assert "index=custom_widefield sourcetype=custom:widefield" in searches
    assert feed["project"] == "customer-project"
    assert feed["location"] == "eu"
    assert feed["displayName"] == "custom-feed"


def test_widefield_setup_rejects_inline_secret_values_without_echoing_value() -> None:
    result = run_cmd(
        "bash",
        str(WIDEFIELD_OKTA),
        "--render",
        "--okta-token=INLINE_SECRET_SHOULD_NOT_ECHO",
        check=False,
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "--okta-token is not allowed" in combined
    assert "INLINE_SECRET_SHOULD_NOT_ECHO" not in combined


# Saviynt and Google SecOps have no documented mutation API, so the shared
# dispatch routes them to widefield_apply_unsupported. Neither skill has any
# other behavioral coverage, and the extra flags below are the plausible
# escalation attempts, so assert the refusal rather than trusting the prose.
@pytest.mark.parametrize(
    ("setup_script", "extra_args"),
    [
        (WIDEFIELD_SAVIYNT, ()),
        (WIDEFIELD_SAVIYNT, ("--accept-saviynt-remediation",)),
        (WIDEFIELD_SAVIYNT, ("--dry-run",)),
        (WIDEFIELD_GOOGLE, ()),
        (WIDEFIELD_GOOGLE, ("--dry-run",)),
    ],
)
def test_widefield_apply_is_refused_without_documented_mutation_api(
    tmp_path: Path,
    setup_script: Path,
    extra_args: tuple[str, ...],
) -> None:
    result = run_cmd(
        "bash",
        str(setup_script),
        "--apply",
        "--accept-apply",
        "--output-dir",
        str(tmp_path / "rendered"),
        *extra_args,
        check=False,
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "no documented live mutation path" in combined
    # --dry-run must not soften the refusal into a "would apply" claim.
    assert "would apply" not in combined.lower()
