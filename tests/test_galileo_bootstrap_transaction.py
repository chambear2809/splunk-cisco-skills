from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "skills"
    / "galileo-lemonade-instrumentation-setup"
    / "scripts"
    / "galileo_bootstrap_transaction.py"
)
SPEC = importlib.util.spec_from_file_location("galileo_bootstrap_transaction", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


USER_ID = "11111111-1111-4111-8111-111111111111"
REVOKER_USER_ID = "77777777-7777-4777-8777-777777777777"
OLD_KEY_ID = "22222222-2222-4222-8222-222222222222"
PROJECT_ID = "33333333-3333-4333-8333-333333333333"
STREAM_ID = "44444444-4444-4444-8444-444444444444"
RUNTIME_ID = "55555555-5555-4555-8555-555555555555"
REVOKER_KEY_ID = "88888888-8888-4888-8888-888888888888"
SECOND_PROJECT_ID = "66666666-6666-4666-8666-666666666666"
BOOTSTRAP_SECRET = "bootstrap-secret-value-0123456789"
RUNTIME_SECRET = "runtime-secret-value-0123456789"
REVOKER_SECRET = "revoker-secret-value-0123456789"


class Crash(BaseException):
    pass


class FakeApi:
    def __init__(self, world: dict[str, Any], kind: str = "bootstrap"):
        self.world = world
        self.kind = kind
        self.api_base = str(world.get("api_base", "https://api.example.invalid"))

    def current_user(self) -> dict[str, object]:
        self.world["current_user_calls"] = self.world.get("current_user_calls", 0) + 1
        if self.kind == "revoker":
            return {"id": REVOKER_USER_ID}
        if self.kind == "bootstrap" and self.world.get("bootstrap_forbidden"):
            raise MODULE.ApiFailure(403, "current-user check", uncertain=False)
        if self.kind == "bootstrap" and not any(
            item["id"] == OLD_KEY_ID for item in self.world["keys"]
        ):
            statuses = self.world.get("post_delete_current_user_statuses")
            if isinstance(statuses, list) and statuses:
                status = statuses.pop(0)
            else:
                status = self.world.get("post_delete_current_user_default_status", 401)
            if status != 200:
                raise MODULE.ApiFailure(
                    int(status), "current-user check", uncertain=False
                )
        return {"id": USER_ID}

    def token_authorization(self) -> None:
        self.world["token_authorization_calls"] = (
            self.world.get("token_authorization_calls", 0) + 1
        )
        if self.kind != "bootstrap":
            return
        statuses = self.world.get("post_delete_token_statuses")
        if isinstance(statuses, list) and statuses:
            status = statuses.pop(0)
        elif any(item["id"] == OLD_KEY_ID for item in self.world["keys"]):
            status = self.world.get("pre_delete_token_status", 200)
        else:
            status = self.world.get("post_delete_token_default_status", 401)
        if status != 200:
            raise MODULE.ApiFailure(
                int(status), "token authorization check", uncertain=False
            )

    def list_keys(self, user_id: str) -> list[dict[str, object]]:
        self.world["list_keys_calls"] = self.world.get("list_keys_calls", 0) + 1
        self.world.setdefault("list_keys_calls_by_actor", []).append(
            (self.kind, user_id)
        )
        if self.kind == "revoker" and user_id == REVOKER_USER_ID:
            return [
                {
                    "id": REVOKER_KEY_ID,
                    "description": "distinct-revoker",
                    "truncated": self.world.get(
                        "revoker_truncated",
                        REVOKER_SECRET[:8] + "..." + REVOKER_SECRET[-4:],
                    ),
                    "project_id": self.world.get("revoker_project_id"),
                    "project_role": None,
                }
            ]
        assert user_id == USER_ID
        return [dict(item) for item in self.world["keys"]]

    def list_projects(self, actions: tuple[str, ...] = ()) -> list[dict[str, object]]:
        values = [dict(item) for item in self.world["projects"]]
        if self.kind == "bootstrap" and self.world.get(
            "hide_project_inventory_count", 0
        ):
            self.world["hide_project_inventory_count"] -= 1
            values = [item for item in values if item["id"] != PROJECT_ID]
        if self.kind == "runtime":
            values = [
                item
                for item in values
                if item["id"] == self.world["runtime_project_id"]
            ]
            if self.world.get("runtime_extra_project"):
                values.append(
                    {
                        "id": SECOND_PROJECT_ID,
                        "name": "unexpected",
                        "type": "gen_ai",
                        "permissions": [{"action": "log_data", "allowed": True}],
                    }
                )
            for item in values:
                item["permissions"] = [
                    {
                        "action": "log_data",
                        "allowed": self.world.get("runtime_log_data", True),
                    }
                ]
        elif actions:
            for item in values:
                item["permissions"] = [{"action": "log_data", "allowed": True}]
        return values

    def list_log_streams(self, project_id: str) -> list[dict[str, object]]:
        return [
            dict(item)
            for item in self.world["streams"]
            if item["project_id"] == project_id
        ]

    def get_project(self, project_id: str) -> dict[str, object] | None:
        return next(
            (dict(item) for item in self.world["projects"] if item["id"] == project_id),
            None,
        )

    def get_log_stream(
        self, project_id: str, log_stream_id: str
    ) -> dict[str, object] | None:
        return next(
            (
                dict(item)
                for item in self.world["streams"]
                if item["project_id"] == project_id and item["id"] == log_stream_id
            ),
            None,
        )

    def create_project(self, name: str) -> dict[str, object]:
        record = {
            "id": PROJECT_ID,
            "name": (
                "wrong-project" if self.world.get("project_identity_mismatch") else name
            ),
            "type": "gen_ai",
            "created_by": USER_ID,
        }
        if self.world.get("project_uncertain_before_commit"):
            self.world["project_uncertain_before_commit"] = False
            raise MODULE.ApiFailure(None, "create project", uncertain=True)
        self.world["projects"].append(record)
        if self.world.get("delay_project_visibility_after_commit"):
            self.world["delay_project_visibility_after_commit"] = False
            self.world["hide_project_inventory_count"] = 1
        if self.world.get("project_uncertain_after_commit"):
            self.world["project_uncertain_after_commit"] = False
            raise MODULE.ApiFailure(None, "create project", uncertain=True)
        return dict(record)

    def create_log_stream(self, project_id: str, name: str) -> dict[str, object]:
        record = {
            "id": STREAM_ID,
            "name": name,
            "project_id": project_id,
            "created_by": USER_ID,
        }
        if self.world.get("log_stream_uncertain_before_commit"):
            self.world["log_stream_uncertain_before_commit"] = False
            raise MODULE.ApiFailure(None, "create Log stream", uncertain=True)
        self.world["streams"].append(record)
        if self.world.get("log_stream_uncertain_after_commit"):
            self.world["log_stream_uncertain_after_commit"] = False
            raise MODULE.ApiFailure(None, "create Log stream", uncertain=True)
        return dict(record)

    def create_key(
        self,
        description: str,
        expires_at: str,
        project_id: str,
        project_role: str,
    ) -> dict[str, object]:
        del expires_at
        attempt = self.world["runtime_create_count"]
        self.world["runtime_create_count"] += 1
        key_id = (
            RUNTIME_ID
            if attempt == 0
            else str(MODULE.uuid.UUID(int=MODULE.uuid.UUID(RUNTIME_ID).int + attempt))
        )
        record = {
            "id": key_id,
            "description": description,
            "truncated": RUNTIME_SECRET[:8] + "..." + RUNTIME_SECRET[-4:],
            "project_id": (
                SECOND_PROJECT_ID
                if self.world.get("runtime_scope_mismatch")
                else project_id
            ),
            "project_role": project_role,
        }
        if self.world.get("runtime_uncertain_before_commit"):
            self.world["runtime_uncertain_before_commit"] = False
            raise MODULE.ApiFailure(None, "create runtime API key", uncertain=True)
        self.world["keys"].append(record)
        self.world["runtime_project_id"] = project_id
        if self.world.get("runtime_uncertain_after_commit"):
            self.world["runtime_uncertain_after_commit"] = False
            raise MODULE.ApiFailure(None, "create runtime API key", uncertain=True)
        return {**record, "api_key": RUNTIME_SECRET}

    def delete_key(self, key_id: str) -> None:
        self.world.setdefault("delete_key_ids", []).append(key_id)
        self.world.setdefault("delete_key_actors", []).append(self.kind)
        existed = any(item["id"] == key_id for item in self.world["keys"])
        if (
            key_id == OLD_KEY_ID
            and not existed
            and self.world.get("repeat_old_delete_status") is not None
        ):
            raise MODULE.ApiFailure(
                int(self.world["repeat_old_delete_status"]),
                "delete API key",
                uncertain=False,
            )
        self.world["keys"] = [
            item for item in self.world["keys"] if item["id"] != key_id
        ]
        if key_id == OLD_KEY_ID and self.world.get("old_revoke_uncertain_after_commit"):
            self.world["old_revoke_uncertain_after_commit"] = False
            raise MODULE.ApiFailure(None, "delete API key", uncertain=True)

    def delete_log_stream(self, project_id: str, log_stream_id: str) -> None:
        self.world["streams"] = [
            item
            for item in self.world["streams"]
            if not (item["project_id"] == project_id and item["id"] == log_stream_id)
        ]

    def delete_project(self, project_id: str) -> None:
        self.world["projects"] = [
            item for item in self.world["projects"] if item["id"] != project_id
        ]


def world() -> dict[str, Any]:
    return {
        "keys": [
            {
                "id": OLD_KEY_ID,
                "description": "old",
                "truncated": BOOTSTRAP_SECRET[:8] + "..." + BOOTSTRAP_SECRET[-4:],
                "project_id": None,
                "project_role": None,
            }
        ],
        "projects": [],
        "streams": [],
        "runtime_create_count": 0,
        "runtime_project_id": PROJECT_ID,
        "runtime_log_data": True,
    }


def protected_file(path: Path, value: str) -> Path:
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    return path


def config(
    tmp_path: Path, *, role: str = "annotator", **overrides: object
) -> dict[str, object]:
    document: dict[str, object] = {
        "api_base": "https://api.example.invalid",
        "old_key_id": OLD_KEY_ID,
        "project_name": "lemonade-production",
        "project_id": None,
        "adopt_project": False,
        "log_stream_name": "ryzen-agent",
        "log_stream_id": None,
        "adopt_log_stream": False,
        "runtime_description": "lemonade-runtime",
        "runtime_key_expires_at": (dt.datetime.now(dt.UTC) + dt.timedelta(days=30))
        .isoformat()
        .replace("+00:00", "Z"),
        "runtime_key_output": str(tmp_path / "runtime.key"),
        "runtime_role": role,
    }
    document.update(overrides)
    return document


def transaction(
    store: Any,
    state: dict[str, Any],
    *,
    failpoint: Any = None,
) -> Any:
    bootstrap = FakeApi(state, "bootstrap")
    return MODULE.GalileoBootstrapTransaction(
        store,
        bootstrap,
        runtime_api_factory=lambda _: FakeApi(state, "runtime"),
        bootstrap_secret=BOOTSTRAP_SECRET,
        failpoint=failpoint,
        revoke_sleep=lambda _: None,
        revoker_api=FakeApi(state, "revoker"),
        revoker_secret=REVOKER_SECRET,
        revoker_key_id=REVOKER_KEY_ID,
    )


def test_happy_bootstrap_stops_before_cutover_and_revocation(tmp_path: Path) -> None:
    state = world()
    with MODULE.StateStore(tmp_path / "state") as store:
        result = transaction(store, state).bootstrap(config(tmp_path))
        journal = store.load()
    assert result["phase"] == "RUNTIME_KEY_CREATED"
    assert journal["phase"] == "RUNTIME_KEY_CREATED"
    assert any(item["id"] == OLD_KEY_ID for item in state["keys"])
    assert (tmp_path / "runtime.key").stat().st_mode & 0o777 == 0o600
    serialized = json.dumps(journal)
    assert BOOTSTRAP_SECRET not in serialized
    assert RUNTIME_SECRET not in serialized


@pytest.mark.parametrize(
    "boundary",
    (
        "after_project_post",
        "after_log_stream_post",
        "after_runtime_key_post",
        "after_runtime_key_output",
    ),
)
def test_crash_boundaries_resume_idempotently(tmp_path: Path, boundary: str) -> None:
    state = world()
    cfg = config(tmp_path)
    triggered = False

    def failpoint(name: str) -> None:
        nonlocal triggered
        if name == boundary and not triggered:
            triggered = True
            raise Crash(name)

    with MODULE.StateStore(tmp_path / "state") as store:
        with pytest.raises(Crash):
            transaction(store, state, failpoint=failpoint).bootstrap(cfg)
    with MODULE.StateStore(tmp_path / "state") as store:
        result = transaction(store, state).bootstrap(cfg)
    assert result["phase"] == "RUNTIME_KEY_CREATED"
    assert len(state["projects"]) == 1
    assert len(state["streams"]) == 1
    assert len([item for item in state["keys"] if item["id"] != OLD_KEY_ID]) == 1


@pytest.mark.parametrize(
    "boundary",
    (
        "after_project_post",
        "after_log_stream_post",
        "after_runtime_key_post",
        "after_runtime_key_output",
    ),
)
def test_crash_boundaries_rollback_exact_owned_objects(
    tmp_path: Path, boundary: str
) -> None:
    state = world()
    triggered = False

    def failpoint(name: str) -> None:
        nonlocal triggered
        if name == boundary and not triggered:
            triggered = True
            raise Crash(name)

    with MODULE.StateStore(tmp_path / "state") as store:
        with pytest.raises(Crash):
            transaction(store, state, failpoint=failpoint).bootstrap(config(tmp_path))
        result = transaction(store, state).rollback()
    assert result["phase"] == "ROLLED_BACK"
    assert [item["id"] for item in state["keys"]] == [OLD_KEY_ID]
    assert state["projects"] == []
    assert state["streams"] == []
    assert not (tmp_path / "runtime.key").exists()


def test_uncertain_committed_post_reconciles_without_duplicate(tmp_path: Path) -> None:
    state = world()
    cfg = config(tmp_path)
    state["project_uncertain_after_commit"] = True
    with MODULE.StateStore(tmp_path / "state") as store:
        with pytest.raises(MODULE.ApiFailure):
            transaction(store, state).bootstrap(cfg)
    with MODULE.StateStore(tmp_path / "state") as store:
        result = transaction(store, state).bootstrap(cfg)
    assert result["phase"] == "RUNTIME_KEY_CREATED"
    assert len(state["projects"]) == 1


def test_delayed_visibility_after_uncertain_commit_requires_retry_authority(
    tmp_path: Path,
) -> None:
    state = world()
    cfg = config(tmp_path)
    state["project_uncertain_after_commit"] = True
    state["delay_project_visibility_after_commit"] = True
    with MODULE.StateStore(tmp_path / "state") as store:
        with pytest.raises(MODULE.ApiFailure):
            transaction(store, state).bootstrap(cfg)
    with MODULE.StateStore(tmp_path / "state") as store:
        with pytest.raises(MODULE.ReconciliationRequired):
            transaction(store, state).bootstrap(cfg)
    assert len(state["projects"]) == 1
    with MODULE.StateStore(tmp_path / "state") as store:
        result = transaction(store, state).bootstrap(cfg)
    assert result["phase"] == "RUNTIME_KEY_CREATED"
    assert len(state["projects"]) == 1


def test_delayed_visibility_after_success_response_crash_never_auto_duplicates(
    tmp_path: Path,
) -> None:
    state = world()
    cfg = config(tmp_path)
    state["delay_project_visibility_after_commit"] = True

    def failpoint(name: str) -> None:
        if name == "after_project_post":
            raise Crash(name)

    with MODULE.StateStore(tmp_path / "state") as store:
        with pytest.raises(Crash):
            transaction(store, state, failpoint=failpoint).bootstrap(cfg)
    with MODULE.StateStore(tmp_path / "state") as store:
        with pytest.raises(MODULE.ReconciliationRequired):
            transaction(store, state).bootstrap(cfg)
    assert len(state["projects"]) == 1
    with MODULE.StateStore(tmp_path / "state") as store:
        result = transaction(store, state).bootstrap(cfg)
    assert result["phase"] == "RUNTIME_KEY_CREATED"
    assert len(state["projects"]) == 1


def test_uncertain_committed_log_stream_post_reconciles_without_duplicate(
    tmp_path: Path,
) -> None:
    state = world()
    cfg = config(tmp_path)
    state["log_stream_uncertain_after_commit"] = True
    with MODULE.StateStore(tmp_path / "state") as store:
        with pytest.raises(MODULE.ApiFailure):
            transaction(store, state).bootstrap(cfg)
    with MODULE.StateStore(tmp_path / "state") as store:
        result = transaction(store, state).bootstrap(cfg)
    assert result["phase"] == "RUNTIME_KEY_CREATED"
    assert len(state["streams"]) == 1


def test_uncertain_uncommitted_post_requires_explicit_retry(tmp_path: Path) -> None:
    state = world()
    cfg = config(tmp_path)
    state["project_uncertain_before_commit"] = True
    with MODULE.StateStore(tmp_path / "state") as store:
        with pytest.raises(MODULE.ApiFailure):
            transaction(store, state).bootstrap(cfg)
    with MODULE.StateStore(tmp_path / "state") as store:
        with pytest.raises(MODULE.ReconciliationRequired):
            transaction(store, state).bootstrap(cfg)
    with MODULE.StateStore(tmp_path / "state") as store:
        result = transaction(store, state).bootstrap(cfg, retry_uncertain=True)
    assert result["phase"] == "RUNTIME_KEY_CREATED"


def test_runtime_lost_secret_key_is_exactly_cleaned_then_reissued(
    tmp_path: Path,
) -> None:
    state = world()
    cfg = config(tmp_path)
    state["runtime_uncertain_after_commit"] = True
    with MODULE.StateStore(tmp_path / "state") as store:
        with pytest.raises(MODULE.ApiFailure):
            transaction(store, state).bootstrap(cfg)
    assert len([item for item in state["keys"] if item["id"] != OLD_KEY_ID]) == 1
    with MODULE.StateStore(tmp_path / "state") as store:
        result = transaction(store, state).bootstrap(cfg)
        journal = store.load()
    assert result["phase"] == "RUNTIME_KEY_CREATED"
    assert journal["intents"]["runtime_key"]["lost_secret_key_cleaned"] == RUNTIME_ID
    assert len([item for item in state["keys"] if item["id"] != OLD_KEY_ID]) == 1


def test_uncertain_uncommitted_runtime_key_requires_explicit_retry(
    tmp_path: Path,
) -> None:
    state = world()
    cfg = config(tmp_path)
    state["runtime_uncertain_before_commit"] = True
    with MODULE.StateStore(tmp_path / "state") as store:
        with pytest.raises(MODULE.ApiFailure):
            transaction(store, state).bootstrap(cfg)
    with MODULE.StateStore(tmp_path / "state") as store:
        with pytest.raises(MODULE.ReconciliationRequired):
            transaction(store, state).bootstrap(cfg)
    with MODULE.StateStore(tmp_path / "state") as store:
        result = transaction(store, state).bootstrap(cfg, retry_uncertain=True)
    assert result["phase"] == "RUNTIME_KEY_CREATED"


@pytest.mark.parametrize(
    "uncertain_flag",
    (
        "project_uncertain_after_commit",
        "log_stream_uncertain_after_commit",
        "runtime_uncertain_after_commit",
    ),
)
def test_rollback_reconciles_and_deletes_committed_uncertain_post(
    tmp_path: Path, uncertain_flag: str
) -> None:
    state = world()
    state[uncertain_flag] = True
    with MODULE.StateStore(tmp_path / "state") as store:
        with pytest.raises(MODULE.ApiFailure):
            transaction(store, state).bootstrap(config(tmp_path))
        result = transaction(store, state).rollback()
    assert result["phase"] == "ROLLED_BACK"
    assert [item["id"] for item in state["keys"]] == [OLD_KEY_ID]
    assert state["projects"] == []
    assert state["streams"] == []


def test_preexisting_runtime_description_collision_is_never_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = world()
    transaction_id = "88888888-8888-4888-8888-888888888888"
    colliding_id = "99999999-9999-4999-8999-999999999999"
    monkeypatch.setattr(MODULE.uuid, "uuid4", lambda: MODULE.uuid.UUID(transaction_id))
    state["keys"].append(
        {
            "id": colliding_id,
            "description": f"lemonade-runtime-{transaction_id}-attempt-1",
            "truncated": "unrelated...mask",
            "project_id": PROJECT_ID,
            "project_role": "annotator",
        }
    )
    with MODULE.StateStore(tmp_path / "state") as store:
        with pytest.raises(MODULE.TransactionError, match="already existed"):
            transaction(store, state).bootstrap(config(tmp_path))
        transaction(store, state).rollback()
    assert any(item["id"] == colliding_id for item in state["keys"])


def test_identity_mismatch_fails_before_child_mutations(tmp_path: Path) -> None:
    state = world()
    state["project_identity_mismatch"] = True
    with MODULE.StateStore(tmp_path / "state") as store:
        with pytest.raises(MODULE.TransactionError, match="project identity"):
            transaction(store, state).bootstrap(config(tmp_path))
        transaction(store, state).rollback()
    assert state["projects"] == []
    assert state["streams"] == []
    assert len(state["keys"]) == 1


@pytest.mark.parametrize(
    "failure",
    ("runtime_extra_project", "runtime_log_data", "runtime_scope_mismatch"),
)
def test_scope_or_permission_failure_is_owned_and_rollbackable(
    tmp_path: Path, failure: str
) -> None:
    state = world()
    state[failure] = failure != "runtime_log_data"
    with MODULE.StateStore(tmp_path / "state") as store:
        with pytest.raises(MODULE.TransactionError):
            transaction(store, state).bootstrap(config(tmp_path))
        journal = store.load()
        assert journal["runtime_key"]["owned"] is True
        result = transaction(store, state).rollback()
    assert result["phase"] == "ROLLED_BACK"
    assert [item["id"] for item in state["keys"]] == [OLD_KEY_ID]
    assert not (tmp_path / "runtime.key").exists()
    assert state["projects"] == []
    assert state["streams"] == []


def evidence_document(journal: dict[str, Any]) -> dict[str, object]:
    return {
        "schema_version": 2,
        "transaction_id": journal["transaction_id"],
        "api_base": journal["api_base"],
        "project_id": journal["target"]["project_id"],
        "log_stream_id": journal["target"]["log_stream_id"],
        "runtime_key_id": journal["runtime_key"]["id"],
        "observed_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "host_proof": {
            "runtime_key_installed": True,
            "collector_config_validated": True,
            "collector_service_active": True,
            "rollback_tested": True,
        },
        "galileo_proof": {
            "otlp_write": True,
            "api_trace_readback": True,
            "api_hierarchy": True,
            "privacy_assertions": True,
        },
        "console_review": {"status": "not_observed"},
        "splunk_proof": {"backend_readback_unchanged": True},
    }


def prepare_legacy_self_delete(
    store: Any, state: dict[str, Any], tmp_path: Path
) -> Path:
    transaction(store, state).bootstrap(config(tmp_path))
    journal = store.load()
    evidence = protected_file(
        tmp_path / "evidence.json", json.dumps(evidence_document(journal))
    )
    transaction(store, state).record_cutover_evidence(evidence, maximum_age_seconds=900)
    journal = store.load()
    started_at = MODULE.iso_now()
    journal["intents"]["old_key_revoke"] = {
        "delete_started": True,
        "delete_started_at": started_at,
        "evidence_sha256": journal["cutover_evidence"]["sha256"],
        "id": OLD_KEY_ID,
        "started_at": started_at,
        "status": "pending",
    }
    store.save(journal)
    state["keys"] = [item for item in state["keys"] if item["id"] != OLD_KEY_ID]
    return evidence


def legacy_recovery_transaction(
    store: Any,
    state: dict[str, Any],
    credential_file: Path,
    *,
    failpoint: Any = None,
) -> Any:
    secret, info = MODULE.read_secret_with_info(credential_file, "bootstrap credential")
    return MODULE.GalileoBootstrapTransaction(
        store,
        FakeApi(state, "bootstrap"),
        runtime_api_factory=lambda _: FakeApi(state, "runtime"),
        bootstrap_secret=secret,
        bootstrap_credential_info=info,
        failpoint=failpoint,
        revoke_sleep=lambda _: None,
    )


def test_finalize_is_separate_and_requires_fresh_bound_evidence(tmp_path: Path) -> None:
    state = world()
    state_dir = tmp_path / "state"
    with MODULE.StateStore(state_dir) as store:
        tx = transaction(store, state)
        tx.bootstrap(config(tmp_path))
        journal = store.load()
        evidence = protected_file(
            tmp_path / "evidence.json", json.dumps(evidence_document(journal))
        )
        with pytest.raises(MODULE.TransactionError, match="HOST_CUTOVER_VALIDATED"):
            tx.finalize(evidence, maximum_age_seconds=900)
        tx.record_cutover_evidence(evidence, maximum_age_seconds=900)
        result = tx.finalize(evidence, maximum_age_seconds=900)
    assert result["phase"] == "FINALIZED"
    assert not any(item["id"] == OLD_KEY_ID for item in state["keys"])
    assert any(item["id"] == result["runtime_key_id"] for item in state["keys"])


def test_finalize_rejects_changed_evidence_inode(tmp_path: Path) -> None:
    state = world()
    with MODULE.StateStore(tmp_path / "state") as store:
        tx = transaction(store, state)
        tx.bootstrap(config(tmp_path))
        journal = store.load()
        evidence = protected_file(
            tmp_path / "evidence.json", json.dumps(evidence_document(journal))
        )
        tx.record_cutover_evidence(evidence, maximum_age_seconds=900)
        replacement = protected_file(
            tmp_path / "replacement.json", json.dumps(evidence_document(journal))
        )
        os.replace(replacement, evidence)
        with pytest.raises(MODULE.TransactionError, match="changed"):
            tx.finalize(evidence, maximum_age_seconds=900)


def test_cutover_evidence_age_cannot_be_weakened_beyond_one_hour(
    tmp_path: Path,
) -> None:
    state = world()
    with MODULE.StateStore(tmp_path / "state") as store:
        tx = transaction(store, state)
        tx.bootstrap(config(tmp_path))
        journal = store.load()
        evidence = protected_file(
            tmp_path / "evidence.json", json.dumps(evidence_document(journal))
        )
        with pytest.raises(MODULE.TransactionError, match="1..3600"):
            tx.record_cutover_evidence(evidence, maximum_age_seconds=3601)
        assert store.load()["phase"] == "RUNTIME_KEY_CREATED"


def test_cutover_evidence_rejects_unattested_console_claim(tmp_path: Path) -> None:
    state = world()
    with MODULE.StateStore(tmp_path / "state") as store:
        tx = transaction(store, state)
        tx.bootstrap(config(tmp_path))
        journal = store.load()
        document = evidence_document(journal)
        document["console_review"] = {"status": "observed"}
        evidence = protected_file(tmp_path / "evidence.json", json.dumps(document))
        with pytest.raises(MODULE.TransactionError, match="browser-attested"):
            tx.record_cutover_evidence(evidence, maximum_age_seconds=900)


def test_finalize_resumes_after_crash_immediately_after_old_key_delete(
    tmp_path: Path,
) -> None:
    state = world()
    state_dir = tmp_path / "state"
    cfg = config(tmp_path)
    triggered = False

    def failpoint(name: str) -> None:
        nonlocal triggered
        if name == "after_old_key_revoke" and not triggered:
            triggered = True
            raise Crash(name)

    with MODULE.StateStore(state_dir) as store:
        transaction(store, state).bootstrap(cfg)
        journal = store.load()
        evidence = protected_file(
            tmp_path / "evidence.json", json.dumps(evidence_document(journal))
        )
        transaction(store, state).record_cutover_evidence(
            evidence, maximum_age_seconds=900
        )
        with pytest.raises(Crash):
            transaction(store, state, failpoint=failpoint).finalize(
                evidence, maximum_age_seconds=900
            )
        assert store.load()["phase"] == "HOST_CUTOVER_VALIDATED"
    assert not any(item["id"] == OLD_KEY_ID for item in state["keys"])

    with MODULE.StateStore(state_dir) as store:
        result = transaction(store, state).finalize(evidence, maximum_age_seconds=900)
    assert result["phase"] == "FINALIZED"


def test_finalize_resume_after_started_revoke_allows_stale_immutable_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = world()
    base_time = dt.datetime.now(dt.UTC)
    monkeypatch.setattr(MODULE, "utc_now", lambda: base_time)
    triggered = False

    def failpoint(name: str) -> None:
        nonlocal triggered
        if name == "after_old_key_revoke" and not triggered:
            triggered = True
            raise Crash(name)

    with MODULE.StateStore(tmp_path / "state") as store:
        transaction(store, state).bootstrap(config(tmp_path))
        journal = store.load()
        evidence = protected_file(
            tmp_path / "evidence.json", json.dumps(evidence_document(journal))
        )
        transaction(store, state).record_cutover_evidence(
            evidence, maximum_age_seconds=900
        )
        with pytest.raises(Crash):
            transaction(store, state, failpoint=failpoint).finalize(
                evidence, maximum_age_seconds=900
            )
        assert store.load()["intents"]["old_key_revoke"]["delete_started"] is True

    monkeypatch.setattr(MODULE, "utc_now", lambda: base_time + dt.timedelta(hours=2))
    with MODULE.StateStore(tmp_path / "state") as store:
        result = transaction(store, state).finalize(evidence, maximum_age_seconds=900)
    assert result["phase"] == "FINALIZED"


def test_stale_evidence_never_starts_old_key_revoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = world()
    base_time = dt.datetime.now(dt.UTC)
    monkeypatch.setattr(MODULE, "utc_now", lambda: base_time)
    with MODULE.StateStore(tmp_path / "state") as store:
        transaction(store, state).bootstrap(config(tmp_path))
        journal = store.load()
        evidence = protected_file(
            tmp_path / "evidence.json", json.dumps(evidence_document(journal))
        )
        transaction(store, state).record_cutover_evidence(
            evidence, maximum_age_seconds=900
        )
        monkeypatch.setattr(
            MODULE, "utc_now", lambda: base_time + dt.timedelta(hours=2)
        )
        with pytest.raises(MODULE.TransactionError, match="stale"):
            transaction(store, state).finalize(evidence, maximum_age_seconds=900)
    assert any(item["id"] == OLD_KEY_ID for item in state["keys"])


def test_finalize_does_not_treat_forbidden_as_revocation(tmp_path: Path) -> None:
    state = world()
    with MODULE.StateStore(tmp_path / "state") as store:
        transaction(store, state).bootstrap(config(tmp_path))
        journal = store.load()
        evidence = protected_file(
            tmp_path / "evidence.json", json.dumps(evidence_document(journal))
        )
        transaction(store, state).record_cutover_evidence(
            evidence, maximum_age_seconds=900
        )
        state["bootstrap_forbidden"] = True
        with pytest.raises(MODULE.ApiFailure) as exc_info:
            transaction(store, state).finalize(evidence, maximum_age_seconds=900)
    assert exc_info.value.status == 403
    assert any(item["id"] == OLD_KEY_ID for item in state["keys"])


def test_uncertain_old_key_delete_forbids_rollback_and_finalize_reconciles(
    tmp_path: Path,
) -> None:
    state = world()
    state["old_revoke_uncertain_after_commit"] = True
    with MODULE.StateStore(tmp_path / "state") as store:
        transaction(store, state).bootstrap(config(tmp_path))
        journal = store.load()
        evidence = protected_file(
            tmp_path / "evidence.json", json.dumps(evidence_document(journal))
        )
        transaction(store, state).record_cutover_evidence(
            evidence, maximum_age_seconds=900
        )
        with pytest.raises(MODULE.ApiFailure):
            transaction(store, state).finalize(evidence, maximum_age_seconds=900)
        pending = store.load()
        assert pending["phase"] == "HOST_CUTOVER_VALIDATED"
        assert pending["intents"]["old_key_revoke"]["delete_started"] is True
        with pytest.raises(MODULE.TransactionError, match="revocation started"):
            transaction(store, state).rollback()
        result = transaction(store, state).finalize(evidence, maximum_age_seconds=900)
    assert result["phase"] == "FINALIZED"


def test_successful_delete_then_repeat_401_requires_direct_current_user_401(
    tmp_path: Path,
) -> None:
    state = world()
    # First finalize: five post-DELETE probes remain authorized. Resume:
    # three prechecks remain authorized, repeat DELETE returns 401, then one
    # more authorized probe precedes the only admissible revocation proof.
    state["post_delete_current_user_statuses"] = [200] * 9 + [401]
    state["repeat_old_delete_status"] = 401
    with MODULE.StateStore(tmp_path / "state") as store:
        transaction(store, state).bootstrap(config(tmp_path))
        journal = store.load()
        evidence = protected_file(
            tmp_path / "evidence.json", json.dumps(evidence_document(journal))
        )
        transaction(store, state).record_cutover_evidence(
            evidence, maximum_age_seconds=900
        )
        with pytest.raises(MODULE.ReconciliationRequired, match="bounded"):
            transaction(store, state).finalize(evidence, maximum_age_seconds=900)
        pending = store.load()
        intent = pending["intents"]["old_key_revoke"]
        assert pending["phase"] == "HOST_CUTOVER_VALIDATED"
        assert pending["old_key"]["revoked"] is False
        assert intent["delete_attempts"] == 1
        assert intent["authorization_checks"] == 6
        assert "revocation_proof" not in intent
        old_selection_calls = sum(
            actor == "bootstrap"
            for actor, _user_id in state["list_keys_calls_by_actor"]
        )

        result = transaction(store, state).finalize(evidence, maximum_age_seconds=900)
        completed = store.load()["intents"]["old_key_revoke"]

    assert result["phase"] == "FINALIZED"
    assert completed["delete_attempts"] == 2
    assert completed["last_delete_outcome"] == "http_401"
    assert completed["revocation_proof"] == "current_user_401_and_token_401"
    assert state["delete_key_ids"] == [OLD_KEY_ID, OLD_KEY_ID]
    assert state["delete_key_actors"] == ["revoker", "revoker"]
    assert (
        sum(
            actor == "bootstrap"
            for actor, _user_id in state["list_keys_calls_by_actor"]
        )
        == old_selection_calls
    )


def test_repeat_delete_401_never_itself_proves_revocation_and_resume_polls(
    tmp_path: Path,
) -> None:
    state = world()
    state["post_delete_current_user_default_status"] = 200
    state["repeat_old_delete_status"] = 401
    with MODULE.StateStore(tmp_path / "state") as store:
        transaction(store, state).bootstrap(config(tmp_path))
        journal = store.load()
        evidence = protected_file(
            tmp_path / "evidence.json", json.dumps(evidence_document(journal))
        )
        transaction(store, state).record_cutover_evidence(
            evidence, maximum_age_seconds=900
        )
        for _ in range(2):
            with pytest.raises(MODULE.ReconciliationRequired):
                transaction(store, state).finalize(evidence, maximum_age_seconds=900)
        pending = store.load()
        intent = pending["intents"]["old_key_revoke"]
        assert pending["phase"] == "HOST_CUTOVER_VALIDATED"
        assert pending["old_key"]["revoked"] is False
        assert intent["delete_attempts"] == 2
        assert intent["last_delete_outcome"] == "http_401"
        assert intent["reconciliation_pending"] is True
        assert "revocation_proof" not in intent
        assert state["delete_key_ids"] == [OLD_KEY_ID, OLD_KEY_ID]

        state["post_delete_current_user_default_status"] = 401
        result = transaction(store, state).finalize(evidence, maximum_age_seconds=900)

    assert result["phase"] == "FINALIZED"
    assert state["delete_key_ids"] == [OLD_KEY_ID, OLD_KEY_ID]


def test_old_key_delete_retries_are_bounded_and_never_select_another_key(
    tmp_path: Path,
) -> None:
    state = world()
    state["post_delete_current_user_default_status"] = 200
    state["repeat_old_delete_status"] = 401
    with MODULE.StateStore(tmp_path / "state") as store:
        transaction(store, state).bootstrap(config(tmp_path))
        journal = store.load()
        evidence = protected_file(
            tmp_path / "evidence.json", json.dumps(evidence_document(journal))
        )
        transaction(store, state).record_cutover_evidence(
            evidence, maximum_age_seconds=900
        )
        for _ in range(MODULE.MAX_REVOKE_DELETE_ATTEMPTS + 1):
            with pytest.raises(MODULE.ReconciliationRequired):
                transaction(store, state).finalize(evidence, maximum_age_seconds=900)
        pending = store.load()
        intent = pending["intents"]["old_key_revoke"]
        assert intent["delete_attempts"] == MODULE.MAX_REVOKE_DELETE_ATTEMPTS
        assert (
            state["delete_key_ids"] == [OLD_KEY_ID] * MODULE.MAX_REVOKE_DELETE_ATTEMPTS
        )
        assert pending["phase"] == "HOST_CUTOVER_VALIDATED"

        state["post_delete_current_user_default_status"] = 401
        result = transaction(store, state).finalize(evidence, maximum_age_seconds=900)

    assert result["phase"] == "FINALIZED"
    assert state["delete_key_ids"] == [OLD_KEY_ID] * MODULE.MAX_REVOKE_DELETE_ATTEMPTS


def test_fresh_finalize_rejects_legacy_self_delete_intent(tmp_path: Path) -> None:
    state = world()
    with MODULE.StateStore(tmp_path / "state") as store:
        evidence = prepare_legacy_self_delete(store, state, tmp_path)
        with pytest.raises(MODULE.TransactionError, match="legacy self-delete"):
            transaction(store, state).finalize(evidence, maximum_age_seconds=900)
        journal = store.load()
    assert journal["phase"] == "HOST_CUTOVER_VALIDATED"
    assert journal["old_key"]["revoked"] is False
    assert state.get("delete_key_ids", []) == []


def test_finalize_requires_distinct_exact_unscoped_revoker(tmp_path: Path) -> None:
    state = world()
    with MODULE.StateStore(tmp_path / "state") as store:
        tx = transaction(store, state)
        tx.bootstrap(config(tmp_path))
        journal = store.load()
        evidence = protected_file(
            tmp_path / "evidence.json", json.dumps(evidence_document(journal))
        )
        tx.record_cutover_evidence(evidence, maximum_age_seconds=900)

        tx.revoker_api = None
        tx.revoker_secret = None
        tx.revoker_key_id = None
        with pytest.raises(MODULE.TransactionError, match="distinct revoker"):
            tx.finalize(evidence, maximum_age_seconds=900)

        tx = transaction(store, state)
        tx.revoker_key_id = OLD_KEY_ID
        with pytest.raises(MODULE.TransactionError, match="differ"):
            tx.finalize(evidence, maximum_age_seconds=900)

        state["revoker_truncated"] = "wrong...mask"
        with pytest.raises(MODULE.TransactionError, match="reviewed key ID"):
            transaction(store, state).finalize(evidence, maximum_age_seconds=900)
        state.pop("revoker_truncated")

        state["revoker_project_id"] = PROJECT_ID
        with pytest.raises(MODULE.TransactionError, match="must not be project-scoped"):
            transaction(store, state).finalize(evidence, maximum_age_seconds=900)
    assert state.get("delete_key_ids", []) == []


def test_finalize_requires_token_401_in_addition_to_current_user_401(
    tmp_path: Path,
) -> None:
    state = world()
    state["post_delete_token_default_status"] = 200
    with MODULE.StateStore(tmp_path / "state") as store:
        transaction(store, state).bootstrap(config(tmp_path))
        journal = store.load()
        evidence = protected_file(
            tmp_path / "evidence.json", json.dumps(evidence_document(journal))
        )
        transaction(store, state).record_cutover_evidence(
            evidence, maximum_age_seconds=900
        )
        with pytest.raises(MODULE.ReconciliationRequired):
            transaction(store, state).finalize(evidence, maximum_age_seconds=900)
        pending = store.load()
    intent = pending["intents"]["old_key_revoke"]
    assert pending["phase"] == "HOST_CUTOVER_VALIDATED"
    assert intent["last_inventory_absent"] is True
    assert intent["token_authorization_checks"] > 0
    assert "revocation_proof" not in intent
    assert state["delete_key_actors"] == ["revoker"]


def test_legacy_recovery_dual_401_closes_without_delete(tmp_path: Path) -> None:
    state = world()
    credential = protected_file(tmp_path / "bootstrap.key", BOOTSTRAP_SECRET + "\n")
    with MODULE.StateStore(tmp_path / "state") as store:
        evidence = prepare_legacy_self_delete(store, state, tmp_path)
        result = legacy_recovery_transaction(
            store, state, credential
        ).reconcile_legacy_revocation(
            evidence,
            maximum_age_seconds=900,
            confirmed_old_key_id=OLD_KEY_ID,
        )
        journal = store.load()
    assert result["phase"] == "FINALIZED"
    assert journal["old_key"]["revoked"] is True
    proof = journal["intents"]["old_key_revoke"]["legacy_reconciliation"]
    assert proof["method"] == "dual_endpoint_401_no_delete"
    assert state["token_authorization_calls"] >= 1
    assert state.get("delete_key_ids", []) == []


def test_legacy_recovery_rejects_token_200_without_mutation(tmp_path: Path) -> None:
    state = world()
    state["post_delete_token_default_status"] = 200
    credential = protected_file(tmp_path / "bootstrap.key", BOOTSTRAP_SECRET + "\n")
    with MODULE.StateStore(tmp_path / "state") as store:
        evidence = prepare_legacy_self_delete(store, state, tmp_path)
        with pytest.raises(MODULE.TransactionError, match="token probe"):
            legacy_recovery_transaction(
                store, state, credential
            ).reconcile_legacy_revocation(
                evidence,
                maximum_age_seconds=900,
                confirmed_old_key_id=OLD_KEY_ID,
            )
        journal = store.load()
    assert journal["phase"] == "HOST_CUTOVER_VALIDATED"
    assert journal["old_key"]["revoked"] is False
    assert state.get("delete_key_ids", []) == []


def test_legacy_recovery_rejects_unbound_or_changed_credential(
    tmp_path: Path,
) -> None:
    state = world()
    with MODULE.StateStore(tmp_path / "state") as store:
        evidence = prepare_legacy_self_delete(store, state, tmp_path)
        credential = protected_file(
            tmp_path / "late-bootstrap.key", BOOTSTRAP_SECRET + "\n"
        )
        with pytest.raises(MODULE.TransactionError, match="changed after PRECHECKED"):
            legacy_recovery_transaction(
                store, state, credential
            ).reconcile_legacy_revocation(
                evidence,
                maximum_age_seconds=900,
                confirmed_old_key_id=OLD_KEY_ID,
            )
        with pytest.raises(MODULE.TransactionError, match="does not match journal"):
            legacy_recovery_transaction(
                store, state, credential
            ).reconcile_legacy_revocation(
                evidence,
                maximum_age_seconds=900,
                confirmed_old_key_id=RUNTIME_ID,
            )
    assert state.get("delete_key_ids", []) == []


def test_rollback_rejects_transport_origin_different_from_journal(
    tmp_path: Path,
) -> None:
    state = world()
    with MODULE.StateStore(tmp_path / "state") as store:
        transaction(store, state).bootstrap(config(tmp_path))
        state["api_base"] = "https://other.example.invalid"
        with pytest.raises(MODULE.TransactionError, match="transport origin"):
            transaction(store, state).rollback()
    assert any(item["id"] == OLD_KEY_ID for item in state["keys"])
    assert any(item["id"] == RUNTIME_ID for item in state["keys"])


def test_rollback_resumes_after_secret_file_unlink_crash(tmp_path: Path) -> None:
    state = world()

    def failpoint(name: str) -> None:
        if name == "after_runtime_output_unlink":
            raise Crash(name)

    with MODULE.StateStore(tmp_path / "state") as store:
        transaction(store, state).bootstrap(config(tmp_path))
        with pytest.raises(Crash):
            transaction(store, state, failpoint=failpoint).rollback()
    assert not (tmp_path / "runtime.key").exists()
    with MODULE.StateStore(tmp_path / "state") as store:
        result = transaction(store, state).rollback()
    assert result["phase"] == "ROLLED_BACK"


def test_rollback_never_unlinks_replacement_after_unlink_crash(
    tmp_path: Path,
) -> None:
    state = world()

    def failpoint(name: str) -> None:
        if name == "after_runtime_output_unlink":
            raise Crash(name)

    with MODULE.StateStore(tmp_path / "state") as store:
        transaction(store, state).bootstrap(config(tmp_path))
        with pytest.raises(Crash):
            transaction(store, state, failpoint=failpoint).rollback()
    replacement = protected_file(tmp_path / "runtime.key", "replacement\n")
    with MODULE.StateStore(tmp_path / "state") as store:
        with pytest.raises(MODULE.TransactionError, match="inode changed"):
            transaction(store, state).rollback()
    assert replacement.read_text(encoding="utf-8") == "replacement\n"


def test_rollback_preserves_adopted_target(tmp_path: Path) -> None:
    state = world()
    state["projects"].append(
        {"id": PROJECT_ID, "name": "lemonade-production", "type": "gen_ai"}
    )
    state["streams"].append(
        {"id": STREAM_ID, "project_id": PROJECT_ID, "name": "ryzen-agent"}
    )
    adopted = config(
        tmp_path,
        project_id=PROJECT_ID,
        adopt_project=True,
        log_stream_id=STREAM_ID,
        adopt_log_stream=True,
    )
    with MODULE.StateStore(tmp_path / "state") as store:
        transaction(store, state).bootstrap(adopted)
        transaction(store, state).rollback()
    assert [item["id"] for item in state["projects"]] == [PROJECT_ID]
    assert [item["id"] for item in state["streams"]] == [STREAM_ID]


@pytest.mark.parametrize("attack", ("symlink", "hardlink", "mode"))
def test_protected_credential_rejects_file_attacks(tmp_path: Path, attack: str) -> None:
    original = protected_file(tmp_path / "original", BOOTSTRAP_SECRET + "\n")
    candidate = tmp_path / "candidate"
    if attack == "symlink":
        candidate.symlink_to(original)
    elif attack == "hardlink":
        os.link(original, candidate)
    else:
        candidate.write_text(BOOTSTRAP_SECRET + "\n", encoding="utf-8")
        candidate.chmod(0o644)
    with pytest.raises(MODULE.TransactionError):
        MODULE.read_secret(candidate, "bootstrap credential")


def test_state_directory_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    linked = tmp_path / "linked"
    linked.symlink_to(target, target_is_directory=True)
    with pytest.raises((MODULE.TransactionError, OSError)):
        with MODULE.StateStore(linked):
            pass


@pytest.mark.parametrize("attack", ("symlink", "hardlink", "mode"))
def test_state_lock_rejects_file_attacks(tmp_path: Path, attack: str) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)
    target = protected_file(tmp_path / "lock-target", "")
    lock = state_dir / "transaction.lock"
    if attack == "symlink":
        lock.symlink_to(target)
    elif attack == "hardlink":
        os.link(target, lock)
    else:
        lock.write_text("", encoding="utf-8")
        lock.chmod(0o644)
    with pytest.raises((MODULE.TransactionError, OSError)):
        with MODULE.StateStore(state_dir):
            pass


def test_state_lock_is_exclusive(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    with MODULE.StateStore(state_dir):
        with pytest.raises(MODULE.TransactionError, match="holds the lock"):
            with MODULE.StateStore(state_dir):
                pass


def test_failed_state_write_removes_private_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / "state"
    with MODULE.StateStore(state_dir) as store:
        monkeypatch.setattr(
            MODULE,
            "_write_all",
            lambda _descriptor, _value: (_ for _ in ()).throw(RuntimeError("fail")),
        )
        with pytest.raises(RuntimeError, match="fail"):
            store.save({"schema_version": MODULE.STATE_SCHEMA})
    assert list(state_dir.glob(".transaction.*.tmp")) == []


def test_secret_output_collision_preserves_existing_file(tmp_path: Path) -> None:
    output = protected_file(tmp_path / "runtime.key", "do-not-delete\n")
    before = output.stat()
    with pytest.raises(MODULE.TransactionError, match="already exists"):
        MODULE.create_secret_file(output, RUNTIME_SECRET)
    after = output.stat()
    assert output.read_text(encoding="utf-8") == "do-not-delete\n"
    assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)


class FakeResponse:
    def __init__(self, document: dict[str, object]):
        self.status = 200
        self.raw = json.dumps(document).encode()

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def read(self, maximum: int) -> bytes:
        assert maximum > len(self.raw)
        return self.raw


class PagingOpener:
    def __init__(self, pages: dict[tuple[str, int], dict[str, object]]):
        self.pages = pages
        self.calls: list[tuple[str, int]] = []

    def open(self, request: Any, timeout: int) -> FakeResponse:
        assert timeout == 30
        parsed = MODULE.urllib.parse.urlsplit(request.full_url)
        query = MODULE.urllib.parse.parse_qs(parsed.query)
        token = int(query.get("starting_token", [0])[0])
        key = (parsed.path, token)
        self.calls.append(key)
        return FakeResponse(self.pages[key])


def test_http_api_follows_every_pagination_token() -> None:
    api = MODULE.HttpGalileoApi("https://api.example.invalid", "secret")
    pages = {
        (f"/v2/users/{USER_ID}/api_keys", 0): {
            "api_keys": [{"id": OLD_KEY_ID}],
            "next_starting_token": 100,
        },
        (f"/v2/users/{USER_ID}/api_keys", 100): {
            "api_keys": [{"id": RUNTIME_ID}],
            "next_starting_token": None,
        },
        ("/v2/projects/paginated", 0): {
            "projects": [{"id": PROJECT_ID}],
            "next_starting_token": 100,
        },
        ("/v2/projects/paginated", 100): {
            "projects": [{"id": SECOND_PROJECT_ID}],
            "next_starting_token": None,
        },
        (f"/v2/projects/{PROJECT_ID}/log_streams/paginated", 0): {
            "log_streams": [{"id": STREAM_ID}],
            "next_starting_token": 100,
        },
        (f"/v2/projects/{PROJECT_ID}/log_streams/paginated", 100): {
            "log_streams": [{"id": "77777777-7777-4777-8777-777777777777"}],
            "next_starting_token": None,
        },
    }
    opener = PagingOpener(pages)
    api._opener = opener
    assert len(api.list_keys(USER_ID)) == 2
    assert len(api.list_projects(("log_data",))) == 2
    assert len(api.list_log_streams(PROJECT_ID)) == 2
    assert len(opener.calls) == 6


def test_http_api_rejects_repeated_pagination_token() -> None:
    api = MODULE.HttpGalileoApi("https://api.example.invalid", "secret")
    api._opener = PagingOpener(
        {
            (f"/v2/users/{USER_ID}/api_keys", 0): {
                "api_keys": [{"id": OLD_KEY_ID}],
                "next_starting_token": 0,
            }
        }
    )
    with pytest.raises(MODULE.TransactionError, match="pagination token"):
        api.list_keys(USER_ID)
