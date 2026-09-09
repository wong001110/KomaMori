from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("continuity", ROOT / "scripts" / "continuity.py")
assert SPEC and SPEC.loader
continuity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(continuity)


def manifest_text(extra_check: bool = False) -> str:
    extra = """
[[requirements.checks]]
id = "P9-R01-C03"
description = "New promised behavior"
evidence = ["test"]
""" if extra_check else ""
    return f'''manifest_version = 1
id = "phase-9"
project = "komamori"
title = "Completeness"

[[requirements]]
id = "P9-R01"
title = "Traceability"
disposition = "required"

[[requirements.checks]]
id = "P9-R01-C01"
description = "Scope sync works"
evidence = ["test"]

[[requirements.checks]]
id = "P9-R01-C02"
description = "Gate is fail closed"
evidence = ["test"]
{extra}
'''


def write_manifest(tmp_path: Path, *, extra_check: bool = False) -> Path:
    manifest = tmp_path / "phase-9.toml"
    manifest.write_text(manifest_text(extra_check), encoding="utf-8")
    return manifest


def seed_phase_and_task(db: Path) -> None:
    continuity.set_phase(db, "phase-9", "Completeness", "in_progress")
    continuity.upsert_task(db, "p9", "phase-9", "Completeness task", "in_progress", None, "phase-9")


def test_existing_v01_database_upgrades_without_losing_history(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    legacy_schema = """
    CREATE TABLE project_state(project_key TEXT PRIMARY KEY, repo TEXT NOT NULL, current_phase TEXT, current_task TEXT, updated_at TEXT NOT NULL);
    CREATE TABLE phases(id INTEGER PRIMARY KEY AUTOINCREMENT, phase_key TEXT NOT NULL UNIQUE, title TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT, completed_at TEXT);
    CREATE TABLE tasks(id INTEGER PRIMARY KEY AUTOINCREMENT, task_key TEXT NOT NULL UNIQUE, phase_key TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL, acceptance TEXT, branch TEXT, pr_number INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, message TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
    CREATE TABLE checkpoints(id INTEGER PRIMARY KEY AUTOINCREMENT, phase_key TEXT NOT NULL, commit_sha TEXT, summary TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE evidence(id INTEGER PRIMARY KEY AUTOINCREMENT, task_key TEXT, kind TEXT NOT NULL, value TEXT NOT NULL, created_at TEXT NOT NULL);
    """
    with sqlite3.connect(db) as conn:
        conn.executescript(legacy_schema)
        conn.execute("INSERT INTO project_state VALUES ('komamori','wong001110/KomaMori','phase-4',NULL,'t')")
        conn.execute("INSERT INTO phases(phase_key,title,status) VALUES ('phase-4','Old','completed')")
        conn.execute("INSERT INTO tasks(task_key,phase_key,title,status,created_at,updated_at) VALUES ('old','phase-4','Old task','completed','t','t')")
        conn.execute("INSERT INTO checkpoints(phase_key,commit_sha,summary,created_at) VALUES ('phase-4','abc','old checkpoint','t')")
        conn.execute("INSERT INTO evidence(task_key,kind,value,created_at) VALUES ('old','test','old evidence','t')")
        conn.execute("INSERT INTO events(kind,message,metadata_json,created_at) VALUES ('old','old event','{}','t')")
    continuity.init(db)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM phases").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='acceptance_checks'").fetchone()
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gate_runs'").fetchone()


def test_manifest_sync_and_bootstrap_expose_unfinished_scope(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    manifest = write_manifest(tmp_path)
    continuity.sync_manifest(db, manifest, "scope-commit")
    continuity.set_phase(db, "phase-9", "Completeness", "in_progress")
    state = continuity.bootstrap(db)
    assert state["scope"]["manifest"]["content_hash"] == continuity.manifest_hash(manifest)
    assert state["scope"]["first_unfinished_check"] == "P9-R01-C01"
    assert [item["check_key"] for item in state["scope"]["requirements"][0]["checks"]] == ["P9-R01-C01", "P9-R01-C02"]


def test_check_evidence_is_commit_bound_and_gate_enumerates_missing_items(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    manifest = write_manifest(tmp_path)
    continuity.sync_manifest(db, manifest, "scope-commit")
    seed_phase_and_task(db)
    continuity.set_task_pr(db, "p9", 99)
    continuity.record_check_evidence(db, check_keys=["P9-R01-C01"], kind="test", status="passed", value="first check passed", commit_sha="commit-a", task_key="p9")
    failed = continuity.run_gate(db, "phase-9", "commit-a")
    assert failed["status"] == "failed"
    assert any(item["id"] == "P9-R01-C02" for item in failed["failures"])
    continuity.record_check_evidence(db, check_keys=["P9-R01-C02"], kind="test", status="passed", value="wrong commit", commit_sha="commit-b", task_key="p9")
    wrong_commit = continuity.run_gate(db, "phase-9", "commit-a")
    assert wrong_commit["status"] == "failed"
    assert any("no passed evidence bound" in item["reason"] for item in wrong_commit["failures"])
    continuity.record_check_evidence(db, check_keys=["P9-R01-C02"], kind="test", status="passed", value="second check passed", commit_sha="commit-a", task_key="p9")
    passed = continuity.run_gate(db, "phase-9", "commit-a")
    assert passed["status"] == "passed"
    continuity.upsert_task(db, "p9", "phase-9", "Completeness task", "completed", None, "phase-9", 99, commit_sha="commit-a")
    continuity.set_phase(db, "phase-9", "Completeness", "completed", commit_sha="commit-a")


def test_task_and_phase_completion_are_blocked_without_current_gate(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    manifest = write_manifest(tmp_path)
    continuity.sync_manifest(db, manifest, "scope-commit")
    seed_phase_and_task(db)
    with pytest.raises(continuity.ContinuityError):
        continuity.upsert_task(db, "p9", "phase-9", "Completeness task", "completed", None, "phase-9")
    with pytest.raises(continuity.ContinuityError):
        continuity.set_phase(db, "phase-9", "Completeness", "completed")


def test_scope_change_invalidates_prior_gate_success(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    manifest = write_manifest(tmp_path)
    continuity.sync_manifest(db, manifest, "scope-a")
    seed_phase_and_task(db)
    continuity.set_task_pr(db, "p9", 99)
    for check in ["P9-R01-C01", "P9-R01-C02"]:
        continuity.record_check_evidence(db, check_keys=[check], kind="test", status="passed", value="passed", commit_sha="commit-a", task_key="p9")
    assert continuity.run_gate(db, "phase-9", "commit-a")["status"] == "passed"
    manifest.write_text(manifest_text(extra_check=True), encoding="utf-8")
    continuity.sync_manifest(db, manifest, "scope-b")
    with pytest.raises(continuity.ContinuityError):
        continuity.set_phase(db, "phase-9", "Completeness", "completed", commit_sha="commit-a")
    gate = continuity.run_gate(db, "phase-9", "commit-a")
    assert gate["status"] == "failed"
    assert any(item["id"] == "P9-R01-C03" for item in gate["failures"])


def test_pr_linkage_and_gate_history_do_not_rewrite_legacy_evidence(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    continuity.init(db)
    continuity.set_phase(db, "phase-9", "Completeness", "in_progress")
    continuity.upsert_task(db, "p9", "phase-9", "Completeness task", "in_progress", "legacy note", "phase-9")
    continuity.legacy_evidence(db, "p9", "test", "historical")
    continuity.set_task_pr(db, "p9", 99)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT pr_number FROM tasks WHERE task_key='p9'").fetchone()[0] == 99
        assert conn.execute("SELECT value FROM evidence WHERE task_key='p9'").fetchone()[0] == "historical"
