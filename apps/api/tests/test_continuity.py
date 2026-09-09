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


def manifest_text(extra: bool = False) -> str:
    new_check = '''
[[requirements.checks]]
id = "P9-R01-C03"
description = "New promised behavior"
evidence = ["test"]
''' if extra else ""
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
evidence = ["test", "review"]
{new_check}'''


def write_manifest(tmp_path: Path, *, extra: bool = False) -> Path:
    path = tmp_path / "phase-9.toml"
    path.write_text(manifest_text(extra), encoding="utf-8")
    return path


def seed(db: Path, manifest: Path) -> None:
    continuity.sync_manifest(db, manifest, "scope-commit")
    continuity.set_phase(db, "phase-9", "Completeness", "in_progress")
    continuity.upsert_task(db, "p9", "phase-9", "Completeness task", "in_progress", None, "phase-9")
    continuity.set_task_pr(db, "p9", 99)


def evidence(db: Path, check: str, kind: str, commit: str = "commit-a") -> None:
    continuity.record_check_evidence(
        db, check_keys=[check], kind=kind, status="passed", value=f"{kind} passed",
        commit_sha=commit, task_key="p9",
    )


def satisfy_base_scope(db: Path) -> None:
    evidence(db, "P9-R01-C01", "test")
    evidence(db, "P9-R01-C02", "test")
    evidence(db, "P9-R01-C02", "review")


def test_existing_v01_database_upgrades_without_losing_history(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    legacy = """
    CREATE TABLE project_state(project_key TEXT PRIMARY KEY,repo TEXT NOT NULL,current_phase TEXT,current_task TEXT,updated_at TEXT NOT NULL);
    CREATE TABLE phases(id INTEGER PRIMARY KEY AUTOINCREMENT,phase_key TEXT NOT NULL UNIQUE,title TEXT NOT NULL,status TEXT NOT NULL,started_at TEXT,completed_at TEXT);
    CREATE TABLE tasks(id INTEGER PRIMARY KEY AUTOINCREMENT,task_key TEXT NOT NULL UNIQUE,phase_key TEXT NOT NULL,title TEXT NOT NULL,status TEXT NOT NULL,acceptance TEXT,branch TEXT,pr_number INTEGER,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
    CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT NOT NULL,message TEXT NOT NULL,metadata_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL);
    CREATE TABLE checkpoints(id INTEGER PRIMARY KEY AUTOINCREMENT,phase_key TEXT NOT NULL,commit_sha TEXT,summary TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE evidence(id INTEGER PRIMARY KEY AUTOINCREMENT,task_key TEXT,kind TEXT NOT NULL,value TEXT NOT NULL,created_at TEXT NOT NULL);
    """
    with sqlite3.connect(db) as conn:
        conn.executescript(legacy)
        conn.execute("INSERT INTO project_state VALUES('komamori','wong001110/KomaMori','phase-4',NULL,'t')")
        conn.execute("INSERT INTO phases(phase_key,title,status) VALUES('phase-4','Old','completed')")
        conn.execute("INSERT INTO tasks(task_key,phase_key,title,status,created_at,updated_at) VALUES('old','phase-4','Old','completed','t','t')")
        conn.execute("INSERT INTO checkpoints(phase_key,commit_sha,summary,created_at) VALUES('phase-4','abc','old','t')")
        conn.execute("INSERT INTO evidence(task_key,kind,value,created_at) VALUES('old','test','old','t')")
        conn.execute("INSERT INTO events(kind,message,metadata_json,created_at) VALUES('old','old','{}','t')")
    continuity.init(db)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM phases").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='acceptance_checks'").fetchone()
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gate_runs'").fetchone()


def test_manifest_sync_and_bootstrap_expose_first_unfinished_check(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    manifest = write_manifest(tmp_path)
    continuity.sync_manifest(db, manifest, "scope")
    continuity.set_phase(db, "phase-9", "Completeness", "in_progress")
    state = continuity.bootstrap(db)
    assert state["scope"]["manifest"]["content_hash"] == continuity.manifest_hash(manifest)
    assert state["scope"]["first_unfinished_check"] == "P9-R01-C01"


def test_gate_enumerates_missing_check_and_rejects_wrong_commit(tmp_path: Path) -> None:
    db = tmp_path / "state.db"; manifest = write_manifest(tmp_path); seed(db, manifest)
    evidence(db, "P9-R01-C01", "test")
    failed = continuity.run_gate(db, "phase-9", "commit-a")
    assert failed["status"] == "failed"
    assert any(x["id"] == "P9-R01-C02" for x in failed["failures"])
    evidence(db, "P9-R01-C02", "test", "commit-b")
    evidence(db, "P9-R01-C02", "review", "commit-b")
    wrong = continuity.run_gate(db, "phase-9", "commit-a")
    assert any("missing test evidence" in x["reason"] for x in wrong["failures"])


def test_gate_requires_every_declared_evidence_kind(tmp_path: Path) -> None:
    db = tmp_path / "state.db"; manifest = write_manifest(tmp_path); seed(db, manifest)
    evidence(db, "P9-R01-C01", "test")
    evidence(db, "P9-R01-C02", "test")
    gate = continuity.run_gate(db, "phase-9", "commit-a")
    assert gate["status"] == "failed"
    assert any(x["id"] == "P9-R01-C02" and "missing review evidence" in x["reason"] for x in gate["failures"])
    evidence(db, "P9-R01-C02", "review")
    assert continuity.run_gate(db, "phase-9", "commit-a")["status"] == "passed"


def test_completion_is_blocked_until_current_gate_passes(tmp_path: Path) -> None:
    db = tmp_path / "state.db"; manifest = write_manifest(tmp_path); seed(db, manifest)
    with pytest.raises(continuity.ContinuityError):
        continuity.upsert_task(db, "p9", "phase-9", "Completeness task", "completed", None, "phase-9")
    satisfy_base_scope(db)
    assert continuity.run_gate(db, "phase-9", "commit-a")["status"] == "passed"
    continuity.upsert_task(db, "p9", "phase-9", "Completeness task", "completed", None, "phase-9", 99, commit_sha="commit-a")
    continuity.set_phase(db, "phase-9", "Completeness", "completed", commit_sha="commit-a")


def test_scope_change_invalidates_prior_gate(tmp_path: Path) -> None:
    db = tmp_path / "state.db"; manifest = write_manifest(tmp_path); seed(db, manifest)
    satisfy_base_scope(db)
    assert continuity.run_gate(db, "phase-9", "commit-a")["status"] == "passed"
    manifest.write_text(manifest_text(extra=True), encoding="utf-8")
    continuity.sync_manifest(db, manifest, "scope-b")
    with pytest.raises(continuity.ContinuityError):
        continuity.set_phase(db, "phase-9", "Completeness", "completed", commit_sha="commit-a")
    gate = continuity.run_gate(db, "phase-9", "commit-a")
    assert any(x["id"] == "P9-R01-C03" for x in gate["failures"])


def test_pr_linkage_does_not_rewrite_legacy_evidence(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    continuity.init(db)
    continuity.set_phase(db, "phase-9", "Completeness", "in_progress")
    continuity.upsert_task(db, "p9", "phase-9", "Task", "in_progress", "legacy", "phase-9")
    continuity.legacy_evidence(db, "p9", "test", "historical")
    continuity.set_task_pr(db, "p9", 99)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT pr_number FROM tasks WHERE task_key='p9'").fetchone()[0] == 99
        assert conn.execute("SELECT value FROM evidence WHERE task_key='p9'").fetchone()[0] == "historical"
