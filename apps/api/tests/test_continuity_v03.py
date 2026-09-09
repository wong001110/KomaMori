from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("continuity_v03", SCRIPTS / "continuity_v03.py")
assert SPEC and SPEC.loader
continuity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(continuity)
base = continuity.base


def manifest_text(*, mapped: bool = True) -> str:
    disposition = "mapped" if mapped else "unmapped"
    source_refs = '["FND-10-001"]' if mapped else "[]"
    return f'''manifest_version = 2
id = "phase-10"
project = "komamori"
title = "Continuity v0.3"

[[sources]]
id = "FND-10-001"
kind = "reviewer"
summary = "Ready semantics must be safe"
description = "Unknown regions must not silently produce Ready"
severity = "P0"
disposition = "{disposition}"
finding_status = "mapped"

[[invariants]]
id = "INV-READY-001"
description = "Ready cannot coexist with unresolved source review"
severity = "P0"
status = "active"

[[requirements]]
id = "P10-R01"
title = "Ready safety"
disposition = "required"
source_refs = {source_refs}

[requirements.impacts]
modules = ["apps/api/src/komamori/routers/workbench.py"]
invariants = ["INV-READY-001"]
domains = ["readiness"]

[[requirements.checks]]
id = "P10-R01-C01"
description = "Unknown regions block Ready"
evidence = ["test", "review"]
'''


def write_manifest(tmp_path: Path, *, mapped: bool = True) -> Path:
    path = tmp_path / "phase-10.toml"
    path.write_text(manifest_text(mapped=mapped), encoding="utf-8")
    return path


def seed(db: Path, manifest: Path) -> None:
    continuity.sync_manifest(db, manifest, "scope")
    continuity.phase(db, "phase-10", "Continuity v0.3", "in_progress", None)
    continuity.task(db, "p10", "phase-10", "Continuity v0.3", "in_progress", None, "phase-10", None, None)
    base.set_task_pr(db, "p10", 100)


def prove(db: Path, commit: str = "commit-a") -> None:
    continuity.evidence(
        db,
        check_keys=["P10-R01-C01"],
        kind="test",
        status="passed",
        value="pytest passed",
        commit=commit,
        task="p10",
        workspace=None,
        artifact=None,
    )
    continuity.evidence(
        db,
        check_keys=["P10-R01-C01"],
        kind="review",
        status="passed",
        value="review passed",
        commit=commit,
        task="p10",
        workspace=None,
        artifact=None,
    )


def test_v03_tables_upgrade_existing_store(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    base.init(db)
    continuity.sync_manifest(db, write_manifest(tmp_path), "scope")
    with sqlite3.connect(db) as conn:
        for table in (
            "scope_sources",
            "review_findings",
            "invariants",
            "source_requirements",
            "check_impacts",
            "check_staleness",
            "scope_capture_gate_runs",
            "fresh_review_gate_runs",
        ):
            assert conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()


def test_capture_gate_rejects_unmapped_source(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    continuity.sync_manifest(db, write_manifest(tmp_path, mapped=False), "scope")
    result = continuity.capture_gate(db, "phase-10")
    assert result["status"] == "failed"
    assert any(item["id"] == "FND-10-001" for item in result["failures"])


def test_capture_gate_requires_invariant_check_mapping(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    manifest = write_manifest(tmp_path)
    continuity.sync_manifest(db, manifest, "scope")
    assert continuity.capture_gate(db, "phase-10")["status"] == "passed"


def test_impacted_change_stales_evidence_until_reverified(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    manifest = write_manifest(tmp_path)
    seed(db, manifest)
    assert continuity.capture_gate(db, "phase-10")["status"] == "passed"
    prove(db)
    assert continuity.gate(db, "phase-10", "commit-a")["status"] == "passed"

    stale = continuity.impact(
        db,
        "phase-10",
        ["apps/api/src/komamori/routers/workbench.py"],
        "commit-b",
    )
    assert stale == ["P10-R01-C01"]
    failed = continuity.gate(db, "phase-10", "commit-b")
    assert failed["status"] == "failed"
    assert any("stale" in item["reason"] for item in failed["failures"])

    prove(db, "commit-b")
    assert continuity.gate(db, "phase-10", "commit-b")["status"] == "passed"


def test_fresh_review_gate_blocks_until_finding_is_terminal(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    manifest = write_manifest(tmp_path)
    seed(db, manifest)
    continuity.capture_gate(db, "phase-10")
    prove(db)
    assert continuity.gate(db, "phase-10", "commit-a")["status"] == "passed"

    failed = continuity.review_gate(db, "phase-10", "commit-a", [])
    assert failed["status"] == "failed"
    assert failed["unresolved_findings"] == ["FND-10-001"]

    continuity.finding_state(db, "FND-10-001", "verified", None, None)
    assert continuity.review_gate(db, "phase-10", "commit-a", [])["status"] == "passed"


def test_phase_completion_requires_completion_and_fresh_review(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    manifest = write_manifest(tmp_path)
    seed(db, manifest)
    continuity.capture_gate(db, "phase-10")
    prove(db)
    assert continuity.gate(db, "phase-10", "commit-a")["status"] == "passed"
    with pytest.raises(base.ContinuityError):
        continuity.phase(db, "phase-10", "Continuity v0.3", "completed", "commit-a")

    continuity.finding_state(db, "FND-10-001", "verified", None, None)
    assert continuity.review_gate(db, "phase-10", "commit-a", [])["status"] == "passed"
    continuity.phase(db, "phase-10", "Continuity v0.3", "completed", "commit-a")
