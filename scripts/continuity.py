#!/usr/bin/env python3
"""Agent Continuity state manager with completion traceability for ephemeral sessions."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / ".agent-continuity" / "state.db"
SCHEMA = ROOT / ".agent-continuity" / "schema.sql"
PROJECT_KEY = "komamori"
REPO = "wong001110/KomaMori"


class ContinuityError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init(path: Path) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        existing = conn.execute("SELECT project_key FROM project_state WHERE project_key = ?", (PROJECT_KEY,)).fetchone()
        conn.execute(
            """
            INSERT INTO project_state(project_key, repo, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(project_key) DO UPDATE SET repo=excluded.repo, updated_at=excluded.updated_at
            """,
            (PROJECT_KEY, REPO, now()),
        )
        if existing is None:
            conn.execute(
                "INSERT INTO events(kind, message, metadata_json, created_at) VALUES ('continuity', 'State store initialized', '{}', ?)",
                (now(),),
            )


def _run_git(*args: str) -> str | None:
    try:
        return subprocess.check_output(args, cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def git_state() -> dict[str, str | None]:
    return {
        "branch": _run_git("git", "branch", "--show-current"),
        "head": _run_git("git", "rev-parse", "HEAD"),
        "dirty": _run_git("git", "status", "--porcelain"),
    }


def load_manifest(path: Path) -> dict[str, Any]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if data.get("project") != PROJECT_KEY:
        raise ContinuityError(f"Manifest project must be {PROJECT_KEY!r}")
    phase_key = str(data.get("id") or "").strip()
    if not phase_key:
        raise ContinuityError("Manifest id is required")
    requirements = data.get("requirements") or []
    seen_requirements: set[str] = set()
    seen_checks: set[str] = set()
    for requirement in requirements:
        req_id = str(requirement.get("id") or "").strip()
        if not req_id or req_id in seen_requirements:
            raise ContinuityError(f"Requirement IDs must be unique and non-empty: {req_id!r}")
        seen_requirements.add(req_id)
        disposition = requirement.get("disposition", "required")
        if disposition not in {"required", "optional", "deferred", "waived"}:
            raise ContinuityError(f"Invalid disposition for {req_id}: {disposition}")
        for check in requirement.get("checks") or []:
            check_id = str(check.get("id") or "").strip()
            if not check_id or check_id in seen_checks:
                raise ContinuityError(f"Acceptance check IDs must be unique and non-empty: {check_id!r}")
            seen_checks.add(check_id)
    return data


def manifest_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record_event(conn: sqlite3.Connection, kind: str, message: str, metadata: dict[str, Any] | None = None) -> None:
    conn.execute(
        "INSERT INTO events(kind, message, metadata_json, created_at) VALUES (?, ?, ?, ?)",
        (kind, message, json.dumps(metadata or {}, sort_keys=True), now()),
    )


def sync_manifest(path: Path, manifest_path: Path, git_commit: str | None = None) -> dict[str, Any]:
    init(path)
    manifest = load_manifest(manifest_path)
    phase_key = str(manifest["id"])
    digest = manifest_hash(manifest_path)
    manifest_id = f"{PROJECT_KEY}:{phase_key}"
    timestamp = now()
    with connect(path) as conn:
        previous = conn.execute(
            "SELECT * FROM scope_manifests WHERE project_key=? AND phase_key=?",
            (PROJECT_KEY, phase_key),
        ).fetchone()
        if previous is not None and previous["content_hash"] != digest:
            _record_event(
                conn,
                "SCOPE_CHANGED",
                f"Approved scope changed for {phase_key}",
                {"old_hash": previous["content_hash"], "new_hash": digest, "path": str(manifest_path)},
            )
        conn.execute(
            """
            INSERT INTO scope_manifests(manifest_id, project_key, phase_key, path, content_hash, git_commit, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(manifest_id) DO UPDATE SET
              path=excluded.path,
              content_hash=excluded.content_hash,
              git_commit=excluded.git_commit,
              synced_at=excluded.synced_at
            """,
            (manifest_id, PROJECT_KEY, phase_key, str(manifest_path), digest, git_commit, timestamp),
        )
        conn.execute("UPDATE requirements SET active=0 WHERE phase_key=?", (phase_key,))
        active_requirement_ids: list[str] = []
        active_check_ids: list[str] = []
        for requirement in manifest.get("requirements") or []:
            req_id = str(requirement["id"])
            active_requirement_ids.append(req_id)
            disposition = str(requirement.get("disposition", "required"))
            default_status = "deferred" if disposition == "deferred" else "waived" if disposition == "waived" else "planned"
            existing = conn.execute("SELECT * FROM requirements WHERE requirement_key=?", (req_id,)).fetchone()
            existing_status = existing["status"] if existing is not None else default_status
            if disposition in {"deferred", "waived"}:
                existing_status = disposition
            elif existing_status in {"deferred", "waived"}:
                existing_status = "planned"
            conn.execute(
                """
                INSERT INTO requirements(requirement_key, phase_key, manifest_id, title, disposition, status, reason, destination, active, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(requirement_key) DO UPDATE SET
                  phase_key=excluded.phase_key,
                  manifest_id=excluded.manifest_id,
                  title=excluded.title,
                  disposition=excluded.disposition,
                  status=excluded.status,
                  reason=excluded.reason,
                  destination=excluded.destination,
                  active=1,
                  updated_at=excluded.updated_at
                """,
                (
                    req_id,
                    phase_key,
                    manifest_id,
                    str(requirement.get("title") or req_id),
                    disposition,
                    existing_status,
                    requirement.get("reason"),
                    requirement.get("destination"),
                    timestamp,
                ),
            )
            conn.execute("UPDATE acceptance_checks SET active=0 WHERE requirement_key=?", (req_id,))
            for check in requirement.get("checks") or []:
                check_id = str(check["id"])
                active_check_ids.append(check_id)
                description = str(check.get("description") or check_id)
                expected = json.dumps(check.get("evidence") or [], sort_keys=True)
                required = 0 if disposition == "optional" or check.get("required") is False else 1
                existing_check = conn.execute("SELECT * FROM acceptance_checks WHERE check_key=?", (check_id,)).fetchone()
                if disposition == "deferred":
                    check_status = "deferred"
                elif disposition == "waived":
                    check_status = "waived"
                elif existing_check is None:
                    check_status = "pending"
                else:
                    check_status = existing_check["status"]
                    if existing_check["description"] != description or existing_check["expected_evidence_json"] != expected:
                        check_status = "pending"
                conn.execute(
                    """
                    INSERT INTO acceptance_checks(check_key, requirement_key, description, required, status, expected_evidence_json, active, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                    ON CONFLICT(check_key) DO UPDATE SET
                      requirement_key=excluded.requirement_key,
                      description=excluded.description,
                      required=excluded.required,
                      status=excluded.status,
                      expected_evidence_json=excluded.expected_evidence_json,
                      active=1,
                      updated_at=excluded.updated_at
                    """,
                    (check_id, req_id, description, required, check_status, expected, timestamp),
                )
        _record_event(
            conn,
            "SCOPE_SYNCED",
            f"Synced approved scope for {phase_key}",
            {"manifest_hash": digest, "requirements": active_requirement_ids, "checks": active_check_ids},
        )
    return {"phase": phase_key, "manifest_hash": digest, "requirements": active_requirement_ids, "checks": active_check_ids}


def _update_requirement_status(conn: sqlite3.Connection, requirement_key: str) -> None:
    requirement = conn.execute("SELECT * FROM requirements WHERE requirement_key=?", (requirement_key,)).fetchone()
    if requirement is None:
        return
    disposition = requirement["disposition"]
    if disposition in {"deferred", "waived"}:
        status = disposition
    else:
        checks = conn.execute(
            "SELECT status, required FROM acceptance_checks WHERE requirement_key=? AND active=1",
            (requirement_key,),
        ).fetchall()
        required_checks = [row["status"] for row in checks if row["required"]]
        if any(value == "failed" for value in required_checks):
            status = "failed"
        elif any(value == "blocked" for value in required_checks):
            status = "blocked"
        elif required_checks and all(value == "passed" for value in required_checks):
            status = "verified"
        elif any(value == "passed" for value in required_checks):
            status = "in_progress"
        else:
            status = "planned"
    conn.execute("UPDATE requirements SET status=?, updated_at=? WHERE requirement_key=?", (status, now(), requirement_key))


def record_check_evidence(
    path: Path,
    *,
    check_keys: Iterable[str],
    kind: str,
    status: str,
    value: str,
    commit_sha: str | None,
    task_key: str | None = None,
    workspace_id: str | None = None,
    artifact_ref: str | None = None,
) -> int:
    if status not in {"passed", "failed", "info"}:
        raise ContinuityError(f"Invalid evidence status: {status}")
    keys = list(dict.fromkeys(check_keys))
    if not keys:
        raise ContinuityError("At least one acceptance check is required")
    init(path)
    with connect(path) as conn:
        rows = conn.execute(
            f"SELECT check_key, requirement_key FROM acceptance_checks WHERE active=1 AND check_key IN ({','.join('?' for _ in keys)})",
            keys,
        ).fetchall()
        found = {row["check_key"]: row["requirement_key"] for row in rows}
        missing = [key for key in keys if key not in found]
        if missing:
            raise ContinuityError(f"Unknown/inactive acceptance checks: {', '.join(missing)}")
        requirement_ids = sorted(set(found.values()))
        requirement_key = requirement_ids[0] if len(requirement_ids) == 1 else None
        cursor = conn.execute(
            """
            INSERT INTO evidence_records(task_key, requirement_key, kind, status, value, commit_sha, workspace_id, artifact_ref, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (task_key, requirement_key, kind, status, value, commit_sha, workspace_id, artifact_ref, now()),
        )
        evidence_id = int(cursor.lastrowid)
        for key in keys:
            conn.execute("INSERT INTO check_evidence(check_key, evidence_id) VALUES (?, ?)", (key, evidence_id))
            if status in {"passed", "failed"}:
                conn.execute("UPDATE acceptance_checks SET status=?, updated_at=? WHERE check_key=?", (status, now(), key))
        for req_id in requirement_ids:
            _update_requirement_status(conn, req_id)
        _record_event(
            conn,
            "EVIDENCE_RECORDED",
            f"Recorded {status} evidence for {len(keys)} acceptance check(s)",
            {"evidence_id": evidence_id, "checks": keys, "commit": commit_sha, "kind": kind},
        )
        return evidence_id


def set_check_state(path: Path, check_key: str, status: str) -> None:
    if status not in {"pending", "blocked", "failed"}:
        raise ContinuityError("Manual check state may only be pending, blocked, or failed")
    init(path)
    with connect(path) as conn:
        row = conn.execute("SELECT requirement_key FROM acceptance_checks WHERE check_key=? AND active=1", (check_key,)).fetchone()
        if row is None:
            raise ContinuityError(f"Unknown/inactive acceptance check: {check_key}")
        conn.execute("UPDATE acceptance_checks SET status=?, updated_at=? WHERE check_key=?", (status, now(), check_key))
        _update_requirement_status(conn, row["requirement_key"])


def _current_manifest(conn: sqlite3.Connection, phase_key: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM scope_manifests WHERE project_key=? AND phase_key=?",
        (PROJECT_KEY, phase_key),
    ).fetchone()


def run_gate(path: Path, phase_key: str, commit_sha: str, *, require_pr: bool = True) -> dict[str, Any]:
    init(path)
    failures: list[dict[str, str]] = []
    with connect(path) as conn:
        manifest = _current_manifest(conn, phase_key)
        if manifest is None:
            failures.append({"id": "manifest", "reason": "No synced approved scope manifest"})
            manifest_digest = "missing"
        else:
            manifest_digest = manifest["content_hash"]
            requirements = conn.execute(
                "SELECT * FROM requirements WHERE phase_key=? AND active=1 ORDER BY requirement_key",
                (phase_key,),
            ).fetchall()
            for requirement in requirements:
                if requirement["disposition"] != "required":
                    continue
                checks = conn.execute(
                    "SELECT * FROM acceptance_checks WHERE requirement_key=? AND active=1 AND required=1 ORDER BY check_key",
                    (requirement["requirement_key"],),
                ).fetchall()
                if not checks:
                    failures.append({"id": requirement["requirement_key"], "reason": "Required requirement has no required acceptance checks"})
                    continue
                for check in checks:
                    if check["status"] != "passed":
                        failures.append({"id": check["check_key"], "reason": f"check status is {check['status']}"})
                        continue
                    bound = conn.execute(
                        """
                        SELECT er.id FROM evidence_records er
                        JOIN check_evidence ce ON ce.evidence_id=er.id
                        WHERE ce.check_key=? AND er.status='passed' AND er.commit_sha=?
                        ORDER BY er.id DESC LIMIT 1
                        """,
                        (check["check_key"], commit_sha),
                    ).fetchone()
                    if bound is None:
                        failures.append({"id": check["check_key"], "reason": f"no passed evidence bound to commit {commit_sha}"})
        tasks = conn.execute("SELECT * FROM tasks WHERE phase_key=?", (phase_key,)).fetchall()
        if require_pr and (not tasks or not any(row["pr_number"] is not None for row in tasks)):
            failures.append({"id": "pr", "reason": "No task in the phase is linked to a PR"})
        status = "failed" if failures else "passed"
        cursor = conn.execute(
            "INSERT INTO gate_runs(phase_key, manifest_hash, commit_sha, status, failures_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (phase_key, manifest_digest, commit_sha, status, json.dumps(failures, sort_keys=True), now()),
        )
        gate_id = int(cursor.lastrowid)
        if not failures:
            conn.execute(
                "UPDATE requirements SET status='done', updated_at=? WHERE phase_key=? AND active=1 AND disposition='required'",
                (now(), phase_key),
            )
        _record_event(
            conn,
            "GATE_PASSED" if status == "passed" else "GATE_FAILED",
            f"Completion gate {status} for {phase_key}",
            {"gate_id": gate_id, "commit": commit_sha, "failures": failures, "manifest_hash": manifest_digest},
        )
    return {"gate_id": gate_id, "phase": phase_key, "commit": commit_sha, "status": status, "failures": failures, "manifest_hash": manifest_digest}


def _require_current_gate(conn: sqlite3.Connection, phase_key: str, commit_sha: str | None = None) -> sqlite3.Row:
    manifest = _current_manifest(conn, phase_key)
    if manifest is None:
        raise ContinuityError(f"Phase {phase_key} has no synced scope manifest")
    params: list[Any] = [phase_key, manifest["content_hash"]]
    sql = "SELECT * FROM gate_runs WHERE phase_key=? AND manifest_hash=? AND status='passed'"
    if commit_sha is not None:
        sql += " AND commit_sha=?"
        params.append(commit_sha)
    sql += " ORDER BY id DESC LIMIT 1"
    gate = conn.execute(sql, params).fetchone()
    if gate is None:
        suffix = f" for commit {commit_sha}" if commit_sha else ""
        raise ContinuityError(f"Phase {phase_key} cannot complete: no passing gate for current approved scope{suffix}")
    return gate


def set_phase(path: Path, key: str, title: str, status: str, *, commit_sha: str | None = None) -> None:
    timestamp = now()
    init(path)
    with connect(path) as conn:
        manifest = _current_manifest(conn, key)
        if status == "completed" and manifest is not None:
            _require_current_gate(conn, key, commit_sha)
        conn.execute(
            """
            INSERT INTO phases(phase_key, title, status, started_at, completed_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(phase_key) DO UPDATE SET
              title=excluded.title,
              status=excluded.status,
              started_at=COALESCE(phases.started_at, excluded.started_at),
              completed_at=excluded.completed_at
            """,
            (key, title, status, timestamp if status == "in_progress" else None, timestamp if status == "completed" else None),
        )
        conn.execute("UPDATE project_state SET current_phase=?, updated_at=? WHERE project_key=?", (key, timestamp, PROJECT_KEY))
        _record_event(conn, "phase", f"Phase {key} -> {status}", {"title": title, "commit": commit_sha})


def upsert_task(
    path: Path,
    key: str,
    phase: str,
    title: str,
    status: str,
    acceptance: str | None,
    branch: str | None,
    pr_number: int | None = None,
    *,
    commit_sha: str | None = None,
) -> None:
    timestamp = now()
    init(path)
    with connect(path) as conn:
        manifest = _current_manifest(conn, phase)
        if status == "completed" and manifest is not None:
            _require_current_gate(conn, phase, commit_sha)
        conn.execute(
            """
            INSERT INTO tasks(task_key, phase_key, title, status, acceptance, branch, pr_number, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_key) DO UPDATE SET
              phase_key=excluded.phase_key,
              title=excluded.title,
              status=excluded.status,
              acceptance=COALESCE(excluded.acceptance, tasks.acceptance),
              branch=COALESCE(excluded.branch, tasks.branch),
              pr_number=COALESCE(excluded.pr_number, tasks.pr_number),
              updated_at=excluded.updated_at
            """,
            (key, phase, title, status, acceptance, branch, pr_number, timestamp, timestamp),
        )
        conn.execute("UPDATE project_state SET current_task=?, updated_at=? WHERE project_key=?", (key if status != "completed" else None, timestamp, PROJECT_KEY))


def set_task_pr(path: Path, task_key: str, pr_number: int) -> None:
    init(path)
    with connect(path) as conn:
        changed = conn.execute("UPDATE tasks SET pr_number=?, updated_at=? WHERE task_key=?", (pr_number, now(), task_key)).rowcount
        if not changed:
            raise ContinuityError(f"Unknown task: {task_key}")
        _record_event(conn, "PR_LINKED", f"Linked {task_key} to PR #{pr_number}", {"task": task_key, "pr": pr_number})


def record_event(path: Path, kind: str, message: str, metadata: str) -> None:
    payload = json.loads(metadata)
    init(path)
    with connect(path) as conn:
        _record_event(conn, kind, message, payload)


def checkpoint(path: Path, phase: str, summary: str, commit: str | None) -> None:
    init(path)
    with connect(path) as conn:
        conn.execute("INSERT INTO checkpoints(phase_key, commit_sha, summary, created_at) VALUES (?, ?, ?, ?)", (phase, commit, summary, now()))


def legacy_evidence(path: Path, task: str | None, kind: str, value: str) -> None:
    init(path)
    with connect(path) as conn:
        conn.execute("INSERT INTO evidence(task_key, kind, value, created_at) VALUES (?, ?, ?, ?)", (task, kind, value, now()))


def _scope_snapshot(conn: sqlite3.Connection, phase_key: str | None) -> dict[str, Any] | None:
    if not phase_key:
        return None
    manifest = _current_manifest(conn, phase_key)
    if manifest is None:
        return None
    requirements = conn.execute("SELECT * FROM requirements WHERE phase_key=? AND active=1 ORDER BY requirement_key", (phase_key,)).fetchall()
    result_requirements: list[dict[str, Any]] = []
    first_unfinished: str | None = None
    for req in requirements:
        checks = conn.execute("SELECT * FROM acceptance_checks WHERE requirement_key=? AND active=1 ORDER BY check_key", (req["requirement_key"],)).fetchall()
        check_dicts = [dict(row) for row in checks]
        if first_unfinished is None and req["disposition"] == "required":
            for check in checks:
                if check["required"] and check["status"] != "passed":
                    first_unfinished = check["check_key"]
                    break
        req_dict = dict(req)
        req_dict["checks"] = check_dicts
        result_requirements.append(req_dict)
    gate = conn.execute("SELECT * FROM gate_runs WHERE phase_key=? ORDER BY id DESC LIMIT 1", (phase_key,)).fetchone()
    return {
        "manifest": dict(manifest),
        "requirements": result_requirements,
        "last_gate": dict(gate) if gate else None,
        "first_unfinished_check": first_unfinished,
    }


def bootstrap(path: Path) -> dict[str, Any]:
    init(path)
    with connect(path) as conn:
        project = conn.execute("SELECT * FROM project_state WHERE project_key = ?", (PROJECT_KEY,)).fetchone()
        phases = conn.execute("SELECT * FROM phases ORDER BY id").fetchall()
        tasks = conn.execute("SELECT * FROM tasks WHERE status IN ('in_progress','blocked','planned') ORDER BY id LIMIT 20").fetchall()
        checkpoint_row = conn.execute("SELECT * FROM checkpoints ORDER BY id DESC LIMIT 1").fetchone()
        events = conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT 10").fetchall()
        current_phase = project["current_phase"] if project else None
        scope = _scope_snapshot(conn, current_phase)
    return {
        "project": dict(project) if project else None,
        "phases": [dict(row) for row in phases],
        "active_tasks": [dict(row) for row in tasks],
        "scope": scope,
        "last_checkpoint": dict(checkpoint_row) if checkpoint_row else None,
        "recent_events": [dict(row) for row in events],
        "workspace": git_state(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("bootstrap")
    sync = sub.add_parser("manifest-sync")
    sync.add_argument("manifest", type=Path)
    sync.add_argument("--commit")
    phase = sub.add_parser("phase")
    phase.add_argument("key")
    phase.add_argument("title")
    phase.add_argument("status", choices=["planned", "in_progress", "completed", "blocked"])
    phase.add_argument("--commit")
    task = sub.add_parser("task")
    task.add_argument("key")
    task.add_argument("phase")
    task.add_argument("title")
    task.add_argument("status", choices=["planned", "in_progress", "completed", "blocked"])
    task.add_argument("--acceptance")
    task.add_argument("--branch")
    task.add_argument("--pr-number", type=int)
    task.add_argument("--commit")
    pr = sub.add_parser("pr")
    pr.add_argument("task")
    pr.add_argument("number", type=int)
    check = sub.add_parser("check")
    check.add_argument("key")
    check.add_argument("status", choices=["pending", "blocked", "failed"])
    event = sub.add_parser("event")
    event.add_argument("kind")
    event.add_argument("message")
    event.add_argument("--metadata", default="{}")
    cp = sub.add_parser("checkpoint")
    cp.add_argument("phase")
    cp.add_argument("summary")
    cp.add_argument("--commit")
    ev = sub.add_parser("evidence")
    ev.add_argument("kind")
    ev.add_argument("value")
    ev.add_argument("--task")
    ev.add_argument("--check", action="append", default=[])
    ev.add_argument("--status", choices=["passed", "failed", "info"], default="passed")
    ev.add_argument("--commit")
    ev.add_argument("--workspace")
    ev.add_argument("--artifact")
    gate = sub.add_parser("gate")
    gate.add_argument("phase")
    gate.add_argument("--commit", required=True)
    gate.add_argument("--allow-no-pr", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.command == "init":
            init(args.db)
        elif args.command == "bootstrap":
            print(json.dumps(bootstrap(args.db), indent=2, ensure_ascii=False))
        elif args.command == "manifest-sync":
            print(json.dumps(sync_manifest(args.db, args.manifest, args.commit), indent=2))
        elif args.command == "phase":
            set_phase(args.db, args.key, args.title, args.status, commit_sha=args.commit)
        elif args.command == "task":
            upsert_task(args.db, args.key, args.phase, args.title, args.status, args.acceptance, args.branch, args.pr_number, commit_sha=args.commit)
        elif args.command == "pr":
            set_task_pr(args.db, args.task, args.number)
        elif args.command == "check":
            set_check_state(args.db, args.key, args.status)
        elif args.command == "event":
            record_event(args.db, args.kind, args.message, args.metadata)
        elif args.command == "checkpoint":
            checkpoint(args.db, args.phase, args.summary, args.commit)
        elif args.command == "evidence":
            if args.check:
                evidence_id = record_check_evidence(
                    args.db,
                    check_keys=args.check,
                    kind=args.kind,
                    status=args.status,
                    value=args.value,
                    commit_sha=args.commit,
                    task_key=args.task,
                    workspace_id=args.workspace,
                    artifact_ref=args.artifact,
                )
                print(json.dumps({"evidence_id": evidence_id}))
            else:
                legacy_evidence(args.db, args.task, args.kind, args.value)
        elif args.command == "gate":
            result = run_gate(args.db, args.phase, args.commit, require_pr=not args.allow_no_pr)
            print(json.dumps(result, indent=2))
            if result["status"] != "passed":
                raise SystemExit(2)
    except ContinuityError as exc:
        parser = argparse.ArgumentParser()
        parser.error(str(exc))


if __name__ == "__main__":
    main()
