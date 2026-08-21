"""End-to-end render tests for the splunk-oncall-setup skill."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP = REPO_ROOT / "skills/splunk-oncall-setup/scripts/setup.sh"
EXAMPLE_YAML_SPEC = REPO_ROOT / "skills/splunk-oncall-setup/templates/oncall.example.yaml"
EXAMPLE_JSON_SPEC = REPO_ROOT / "skills/splunk-oncall-setup/templates/oncall.example.json"


def run_setup(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(
        ["bash", str(SETUP), *args],
        cwd=REPO_ROOT,
        env=run_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def rendered_text(root: Path) -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(root.rglob("*")) if path.is_file())


@pytest.mark.parametrize("spec_path", [EXAMPLE_JSON_SPEC, EXAMPLE_YAML_SPEC])
def test_example_specs_render_artifacts(tmp_path: Path, spec_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    result = run_setup("--render", "--validate", "--spec", str(spec_path), "--output-dir", str(output_dir))
    assert result.returncode == 0, combined_output(result)

    for required in (
        "coverage-report.json",
        "apply-plan.json",
        "deeplinks.json",
        "handoff.md",
        "metadata.json",
    ):
        assert (output_dir / required).is_file(), f"missing {required}"

    coverage = json.loads((output_dir / "coverage-report.json").read_text(encoding="utf-8"))
    assert coverage["api_version"] == "splunk-oncall-setup/v1"
    summary = coverage["summary"]
    # Both example specs exercise the api_apply tag.
    assert summary["api_apply"] >= 1
    # The full YAML spec exercises every other tag too.
    if spec_path == EXAMPLE_YAML_SPEC:
        assert summary["api_validate"] >= 1
        assert summary["deeplink"] >= 1
        assert summary["handoff"] >= 1
        assert summary["install_apply"] >= 1

    apply_plan = json.loads((output_dir / "apply-plan.json").read_text(encoding="utf-8"))
    assert apply_plan["mode"] == "splunk-oncall"
    for action in apply_plan["actions"]:
        # Renderer must never emit on_call apply actions with unresolved
        # path placeholders or non-`on_call` services.
        assert action["service"] == "on_call"
        assert action["path"].startswith("/")
        assert "{" not in action["path"]
        assert "}" not in action["path"]


def test_full_yaml_spec_emits_all_documented_resource_types(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    result = run_setup("--render", "--spec", str(EXAMPLE_YAML_SPEC), "--output-dir", str(output_dir))
    assert result.returncode == 0, combined_output(result)
    coverage = json.loads((output_dir / "coverage-report.json").read_text(encoding="utf-8"))
    object_types = {item["object_type"] for item in coverage["objects"]}
    expected = {
        "user",
        "team",
        "rotation",
        "escalation_policy",
        "routing_key",
        "personal_paging_policy",
        "scheduled_override",
        "alert_rule",
        "incident",
        "incident_note",
        "chat_message",
        "stakeholder_message",
        "rest_alert",
        "email_alert",
        "splunk_side_alert_action",
        "splunk_side_add_on",
        "splunk_side_soar_connector",
        "recovery_polling",
    }
    missing = expected - object_types
    assert not missing, f"missing object types: {missing}"


def test_apply_plan_lists_documented_rate_buckets(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    result = run_setup("--render", "--spec", str(EXAMPLE_YAML_SPEC), "--output-dir", str(output_dir))
    assert result.returncode == 0, combined_output(result)
    plan = json.loads((output_dir / "apply-plan.json").read_text(encoding="utf-8"))
    buckets = {action.get("rate_bucket") for action in plan["actions"]}
    # Renderer must mark alert_rules and reporting v2 incidents in their
    # dedicated buckets so the API client's token-bucket governor honors
    # the documented per-endpoint limits.
    assert "alert_rules" in buckets
    assert "reporting_v2_incidents" in buckets


def test_payload_files_referenced_by_apply_plan_exist(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    result = run_setup("--render", "--spec", str(EXAMPLE_YAML_SPEC), "--output-dir", str(output_dir))
    assert result.returncode == 0, combined_output(result)
    plan = json.loads((output_dir / "apply-plan.json").read_text(encoding="utf-8"))
    for action in plan["actions"]:
        payload_file = action.get("payload_file")
        if payload_file:
            assert (output_dir / payload_file).is_file(), payload_file


def test_team_membership_handoff_when_slug_missing(tmp_path: Path) -> None:
    """If the team has no `slug:`, member-add must NOT appear in apply-plan.

    The Splunk On-Call API addresses teams by their system-generated slug
    (e.g. ``team-AbCd1234``); a slugified name will not work. The renderer
    falls back to a handoff coverage entry instead of emitting a 404-bound
    action.
    """
    spec = {
        "api_version": "splunk-oncall-setup/v1",
        "users": [{"kind": "create", "username": "alice", "role": "user"}],
        "teams": [
            {
                "kind": "create",
                "name": "Team Without Slug",
                "members": ["alice"],
                "admins": ["alice"],
            }
        ],
    }
    spec_path = tmp_path / "no-slug.json"
    spec_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    output_dir = tmp_path / "rendered"
    result = run_setup("--render", "--validate", "--spec", str(spec_path), "--output-dir", str(output_dir))
    assert result.returncode == 0, combined_output(result)

    plan = json.loads((output_dir / "apply-plan.json").read_text(encoding="utf-8"))
    coverage = json.loads((output_dir / "coverage-report.json").read_text(encoding="utf-8"))

    # Apply-plan must contain the team create but NOT a member-add action
    # against a slug-derived URL.
    member_actions = [
        action for action in plan["actions"] if action["object_type"] == "team_member"
    ]
    assert not member_actions, "team_member actions must not be emitted without a real slug"

    handoffs = [
        item for item in coverage["objects"] if item["object_type"] == "team_membership_handoff"
    ]
    assert handoffs, "missing team_membership_handoff entry"
    assert "two-pass" in handoffs[0]["notes"].lower() or "re-render" in handoffs[0]["notes"].lower()


def test_team_membership_emits_isAdmin_when_slug_present(tmp_path: Path) -> None:
    """Once the operator supplies the team's slug, members get added with
    `isAdmin: true` for those listed in the team's `admins:` field.
    """
    spec = {
        "api_version": "splunk-oncall-setup/v1",
        "users": [
            {"kind": "create", "username": "alice", "role": "team_admin"},
            {"kind": "create", "username": "bob", "role": "user"},
        ],
        "teams": [
            {
                "kind": "create",
                "name": "Checkout",
                "slug": "team-AbCd1234",
                "members": ["alice", "bob"],
                "admins": ["alice"],
            }
        ],
    }
    spec_path = tmp_path / "with-slug.json"
    spec_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    output_dir = tmp_path / "rendered"
    result = run_setup("--render", "--validate", "--spec", str(spec_path), "--output-dir", str(output_dir))
    assert result.returncode == 0, combined_output(result)

    plan = json.loads((output_dir / "apply-plan.json").read_text(encoding="utf-8"))
    member_actions = [
        action for action in plan["actions"] if action["object_type"] == "team_member"
    ]
    assert len(member_actions) == 2
    assert all("/team/team-AbCd1234/members" in action["path"] for action in member_actions)

    payloads = {}
    for action in member_actions:
        payloads[action["name"]] = json.loads(
            (output_dir / action["payload_file"]).read_text(encoding="utf-8")
        )
    assert payloads["Checkout/alice"].get("isAdmin") is True
    assert "isAdmin" not in payloads["Checkout/bob"]


def test_rotation_and_escalation_policy_handoff_when_team_slug_missing(tmp_path: Path) -> None:
    spec = {
        "api_version": "splunk-oncall-setup/v1",
        "users": [{"kind": "create", "username": "alice", "role": "user"}],
        "teams": [{"kind": "create", "name": "T", "members": []}],
        "rotations": [
            {
                "kind": "create",
                "team": "T",
                "name": "Primary",
                "shifts": [{"name": "all-day", "members": ["alice"]}],
            }
        ],
        "escalation_policies": [
            {
                "kind": "create",
                "team": "T",
                "name": "Default",
                "steps": [{"timeout_minutes": 0, "targets": [{"type": "user", "slug": "alice"}]}],
            }
        ],
    }
    spec_path = tmp_path / "missing-team-slug.json"
    spec_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    output_dir = tmp_path / "rendered"
    result = run_setup("--render", "--validate", "--spec", str(spec_path), "--output-dir", str(output_dir))
    assert result.returncode == 0, combined_output(result)

    plan = json.loads((output_dir / "apply-plan.json").read_text(encoding="utf-8"))
    object_types_in_plan = {action["object_type"] for action in plan["actions"]}
    assert "rotation" not in object_types_in_plan
    assert "escalation_policy" not in object_types_in_plan

    coverage = json.loads((output_dir / "coverage-report.json").read_text(encoding="utf-8"))
    rotation_items = [item for item in coverage["objects"] if item["object_type"] == "rotation"]
    policy_items = [item for item in coverage["objects"] if item["object_type"] == "escalation_policy"]
    assert rotation_items and rotation_items[0]["coverage"] == "handoff"
    assert policy_items and policy_items[0]["coverage"] == "handoff"


def test_reset_output_dir_refuses_to_wipe_non_rendered_directory(tmp_path: Path) -> None:
    """The renderer must refuse to wipe a directory that doesn't carry
    a splunk-oncall metadata.json marker. This prevents an operator who
    accidentally points --output-dir at /home/user from losing data.
    """
    output_dir = tmp_path / "looks-important"
    output_dir.mkdir()
    (output_dir / "important.txt").write_text("do not wipe me", encoding="utf-8")
    result = run_setup(
        "--render",
        "--spec",
        str(EXAMPLE_JSON_SPEC),
        "--output-dir",
        str(output_dir),
    )
    assert result.returncode == 1
    assert "Refusing to wipe" in combined_output(result)
    assert (output_dir / "important.txt").read_text(encoding="utf-8") == "do not wipe me"


def test_reset_output_dir_replays_into_previous_render(tmp_path: Path) -> None:
    """A second render into an existing splunk-oncall output dir succeeds."""
    output_dir = tmp_path / "rendered"
    first = run_setup("--render", "--spec", str(EXAMPLE_JSON_SPEC), "--output-dir", str(output_dir))
    assert first.returncode == 0, combined_output(first)
    second = run_setup("--render", "--spec", str(EXAMPLE_JSON_SPEC), "--output-dir", str(output_dir))
    assert second.returncode == 0, combined_output(second)


def test_splunk_side_install_never_passes_api_key_value_on_argv() -> None:
    """Defense-in-depth audit: the splunk_side_install.sh apply path must
    never substitute the api_key VALUE into a python -c command line. The
    SECURITY note in that file pins that behavior; this test guards it."""
    install_path = REPO_ROOT / "skills/splunk-oncall-setup/scripts/splunk_side_install.sh"
    text = install_path.read_text(encoding="utf-8")
    # The api_key value is read from the file inside Python via the
    # API_KEY_FILE environment variable, never via argv.
    assert "API_KEY_FILE=" in text
    assert 'os.environ["API_KEY_FILE"]' in text
    # No line may pass `${api_key}` or similar to a python command.
    forbidden_patterns = (
        '"${api_key}"',
        "${api_key} ",
        '" ${api_key}',
        '"$api_key"',
    )
    for pattern in forbidden_patterns:
        assert pattern not in text, f"forbidden api_key argv pattern found: {pattern!r}"


def test_no_secret_values_appear_in_rendered_output(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    api_key_file = tmp_path / "api-key"
    api_key_file.write_text("ONCALL_SECRET_SHOULD_NOT_RENDER", encoding="utf-8")
    api_key_file.chmod(0o600)
    result = run_setup(
        "--render",
        "--apply",
        "--dry-run",
        "--spec",
        str(EXAMPLE_JSON_SPEC),
        "--output-dir",
        str(output_dir),
        "--api-id",
        "AB12",
        "--api-key-file",
        str(api_key_file),
    )
    assert result.returncode == 0, combined_output(result)
    rendered = rendered_text(output_dir)
    assert "ONCALL_SECRET_SHOULD_NOT_RENDER" not in rendered
    assert "ONCALL_SECRET_SHOULD_NOT_RENDER" not in combined_output(result)


def render_deeplinks(tmp_path: Path, spec_path: Path) -> list[dict[str, str]]:
    output_dir = tmp_path / "rendered"
    result = run_setup("--render", "--validate", "--spec", str(spec_path), "--output-dir", str(output_dir))
    assert result.returncode == 0, combined_output(result)
    return json.loads((output_dir / "deeplinks.json").read_text(encoding="utf-8"))["deeplinks"]


def test_sso_deeplink_uses_the_org_slug(tmp_path: Path) -> None:
    """The SP-initiated SSO URL takes the org slug.

    Splunk's per-IdP guides (Okta, Google Apps, OneLogin, Azure AD, AWS IAM
    Identity Center) all put the org slug in this path. There is no
    Support-provisioned "companyId" identifier, so rendering a placeholder for
    one told operators to open a ticket and wait for a value that never comes.
    """
    deeplinks = render_deeplinks(tmp_path, EXAMPLE_YAML_SPEC)
    sso = [item for item in deeplinks if item["object_type"] == "sso"]
    assert sso, "example spec no longer renders an sso deeplink"
    for item in sso:
        assert item["url"] == "https://portal.victorops.com/auth/sso/acme-corp"
        assert "companyId" not in item["url"]


def test_no_rendered_deeplink_carries_an_unsubstituted_placeholder(tmp_path: Path) -> None:
    """No deeplink may ship angle-bracket placeholder text to an operator.

    Rendered artifacts are handed straight to an operator, so an unsubstituted
    `<...>` token is a defect regardless of which branch produced it.
    """
    for spec_path in (EXAMPLE_JSON_SPEC, EXAMPLE_YAML_SPEC):
        for item in render_deeplinks(tmp_path / spec_path.stem, spec_path):
            url = item["url"]
            assert "<" not in url and ">" not in url, f"{item['object_type']} renders a placeholder: {url}"


def test_org_scoped_deeplinks_percent_encode_the_slug_consistently(tmp_path: Path) -> None:
    """Every org-scoped portal deeplink quotes the slug the same way.

    This is what keeps the sso branch from drifting away from its siblings
    again: it has to agree with them on the encoded slug, not merely contain
    the raw value.
    """
    spec = yaml.safe_load(EXAMPLE_YAML_SPEC.read_text(encoding="utf-8"))
    spec["org_slug"] = "acme corp"
    spec_path = tmp_path / "escaping-spec.yaml"
    spec_path.write_text(yaml.safe_dump(spec), encoding="utf-8")

    org_scoped = [
        item for item in render_deeplinks(tmp_path, spec_path)
        if item["url"].startswith("https://portal.victorops.com/") and "acme" in item["url"]
    ]
    assert {item["object_type"] for item in org_scoped} >= {"sso", "webhook", "email_alert"}
    for item in org_scoped:
        assert "acme%20corp" in item["url"], f"{item['object_type']} does not quote the slug: {item['url']}"
        assert "acme corp" not in item["url"]


# Every realm Splunk Observability currently publishes. The example spec pins
# us1, so any *other* token appearing in rendered output is a hardcoded literal.
O11Y_REALMS = ("us0", "us1", "us2", "eu0", "eu1", "eu2", "au0", "jp0", "sg0")


def render_with_realm(tmp_path: Path, realm: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    spec = yaml.safe_load(EXAMPLE_YAML_SPEC.read_text(encoding="utf-8"))
    if realm is None:
        spec.pop("realm", None)
    else:
        spec["realm"] = realm
    spec_path = tmp_path / "realm-spec.yaml"
    spec_path.write_text(yaml.safe_dump(spec), encoding="utf-8")
    output_dir = tmp_path / "rendered"
    result = run_setup("--render", "--spec", str(spec_path), "--output-dir", str(output_dir))
    return result, output_dir


def test_observability_deeplink_follows_the_spec_realm(tmp_path: Path) -> None:
    result, output_dir = render_with_realm(tmp_path, "eu0")
    assert result.returncode == 0, combined_output(result)
    deeplinks = json.loads((output_dir / "deeplinks.json").read_text(encoding="utf-8"))["deeplinks"]
    handoff = [item for item in deeplinks if item["object_type"] == "splunk_side_observability_handoff"]
    assert handoff, "example spec no longer renders the observability handoff"
    for item in handoff:
        assert item["url"] == "https://app.eu0.observability.splunkcloud.com/#/me"


def test_observability_handoff_refuses_to_render_without_a_realm(tmp_path: Path) -> None:
    """An absent realm must fail, not fall back to a default.

    A deeplink into the wrong realm loads a real UI in which the operator's org
    does not exist, so a silent default hides the error instead of surfacing it.
    """
    result, _ = render_with_realm(tmp_path, None)
    assert result.returncode != 0
    output = combined_output(result)
    assert "realm" in output
    assert "observability_handoff" in output


@pytest.mark.parametrize(
    "bad_realm",
    ["US0", "https://app.us0.signalfx.com", "us0/../eu0", "uso", "not-a-realm", "us2"],
)
def test_malformed_realms_are_rejected(tmp_path: Path, bad_realm: str) -> None:
    result, _ = render_with_realm(tmp_path, bad_realm)
    assert result.returncode != 0, f"accepted malformed realm {bad_realm!r}"


def test_us2_gcp_realm_uses_the_published_us2_hostname(tmp_path: Path) -> None:
    result, output_dir = render_with_realm(tmp_path, "us2-gcp")
    assert result.returncode == 0, combined_output(result)
    deeplinks = json.loads((output_dir / "deeplinks.json").read_text(encoding="utf-8"))[
        "deeplinks"
    ]
    handoff = [
        item
        for item in deeplinks
        if item["object_type"] == "splunk_side_observability_handoff"
    ]
    assert handoff
    assert {item["url"] for item in handoff} == {
        "https://app.us2.observability.splunkcloud.com/#/me"
    }


def test_no_rendered_url_pins_a_realm_other_than_the_spec_realm(tmp_path: Path) -> None:
    """No rendered artifact may name a realm the spec did not ask for.

    This catches the class rather than the instance: a newly hardcoded realm
    literal anywhere in the renderer shows up as a foreign realm token.
    """
    result, output_dir = render_with_realm(tmp_path, "jp0")
    assert result.returncode == 0, combined_output(result)
    rendered = rendered_text(output_dir)
    for realm in O11Y_REALMS:
        if realm == "jp0":
            continue
        assert f"app.{realm}." not in rendered, f"rendered output hardcodes realm {realm}"
        assert f"{realm}.signalfx.com" not in rendered, f"rendered output hardcodes realm {realm}"
