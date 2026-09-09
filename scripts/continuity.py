#!/usr/bin/env python3
"""Agent Continuity v0.2: durable execution + completion traceability."""
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
        existed = conn.execute(
            "SELECT 1 FROM project_state WHERE project_key=?", (PROJECT_KEY,)
        ).fetchone()
        conn.execute(
            """INSERT INTO project_state(project_key,repo,updated_at)
               VALUES(?,?,?)
               ON CONFLICT(project_key) DO UPDATE SET repo=excluded.repo,updated_at=excluded.updated_at""",
            (PROJECT_KEY, REPO, now()),
        )
        if not existed:
            _event(conn, "continuity", "State store initialized")


def _event(conn: sqlite3.Connection, kind: str, message: str, metadata: dict[str, Any] | None = None) -> None:
    conn.execute(
        "INSERT INTO events(kind,message,metadata_json,created_at) VALUES(?,?,?,?)",
        (kind, message, json.dumps(metadata or {}, sort_keys=True), now()),
    )


def _git(*args: str) -> str | None:
    try:
        return subprocess.check_output(args, cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def git_state() -> dict[str, str | None]:
    return {
        "branch": _git("git", "branch", "--show-current"),
        "head": _git("git", "rev-parse", "HEAD"),
        "dirty": _git("git", "status", "--porcelain"),
    }


def load_manifest(path: Path) -> dict[str, Any]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if data.get("project") != PROJECT_KEY:
        raise ContinuityError(f"manifest project must be {PROJECT_KEY!r}")
    if not str(data.get("id") or "").strip():
        raise ContinuityError("manifest id is required")
    req_ids: set[str] = set()
    check_ids: set[str] = set()
    for req in data.get("requirements") or []:
        req_id = str(req.get("id") or "").strip()
        if not req_id or req_id in req_ids:
            raise ContinuityError(f"duplicate/empty requirement id: {req_id!r}")
        req_ids.add(req_id)
        if req.get("disposition", "required") not in {"required", "optional", "deferred", "waived"}:
            raise ContinuityError(f"invalid disposition for {req_id}")
        for check in req.get("checks") or []:
            check_id = str(check.get("id") or "").strip()
            if not check_id or check_id in check_ids:
                raise ContinuityError(f"duplicate/empty check id: {check_id!r}")
            check_ids.add(check_id)
    return data


def manifest_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sync_manifest(db: Path, manifest_path: Path, git_commit: str | None = None) -> dict[str, Any]:
    init(db)
    manifest = load_manifest(manifest_path)
    phase = str(manifest["id"])
    digest = manifest_hash(manifest_path)
    manifest_id = f"{PROJECT_KEY}:{phase}"
    stamp = now()
    req_ids: list[str] = []
    check_ids: list[str] = []
    with connect(db) as conn:
        previous = conn.execute(
            "SELECT content_hash FROM scope_manifests WHERE project_key=? AND phase_key=?",
            (PROJECT_KEY, phase),
        ).fetchone()
        if previous and previous["content_hash"] != digest:
            _event(conn, "SCOPE_CHANGED", f"Approved scope changed for {phase}", {
                "old_hash": previous["content_hash"], "new_hash": digest,
            })
        conn.execute(
            """INSERT INTO scope_manifests(manifest_id,project_key,phase_key,path,content_hash,git_commit,synced_at)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(manifest_id) DO UPDATE SET path=excluded.path,content_hash=excluded.content_hash,
                 git_commit=excluded.git_commit,synced_at=excluded.synced_at""",
            (manifest_id, PROJECT_KEY, phase, str(manifest_path), digest, git_commit, stamp),
        )
        conn.execute("UPDATE requirements SET active=0 WHERE phase_key=?", (phase,))
        for req in manifest.get("requirements") or []:
            req_id = str(req["id"])
            req_ids.append(req_id)
            disposition = str(req.get("disposition", "required"))
            existing = conn.execute(
                "SELECT status FROM requirements WHERE requirement_key=?", (req_id,)
            ).fetchone()
            if disposition in {"deferred", "waived"}:
                req_status = disposition
            elif existing and existing["status"] not in {"deferred", "waived"}:
                req_status = existing["status"]
            else:
                req_status = "planned"
            conn.execute(
                """INSERT INTO requirements(requirement_key,phase_key,manifest_id,title,disposition,status,reason,destination,active,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,1,?)
                   ON CONFLICT(requirement_key) DO UPDATE SET phase_key=excluded.phase_key,manifest_id=excluded.manifest_id,
                     title=excluded.title,disposition=excluded.disposition,status=excluded.status,reason=excluded.reason,
                     destination=excluded.destination,active=1,updated_at=excluded.updated_at""",
                (req_id, phase, manifest_id, str(req.get("title") or req_id), disposition, req_status,
                 req.get("reason"), req.get("destination"), stamp),
            )
            conn.execute("UPDATE acceptance_checks SET active=0 WHERE requirement_key=?", (req_id,))
            for check in req.get("checks") or []:
                check_id = str(check["id"])
                check_ids.append(check_id)
                description = str(check.get("description") or check_id)
                expected = json.dumps(check.get("evidence") or [], sort_keys=True)
                required = 0 if disposition == "optional" or check.get("required") is False else 1
                old = conn.execute(
                    "SELECT description,expected_evidence_json,status FROM acceptance_checks WHERE check_key=?",
                    (check_id,),
                ).fetchone()
                if disposition in {"deferred", "waived"}:
                    status = disposition
                elif old and old["description"] == description and old["expected_evidence_json"] == expected:
                    status = old["status"]
                else:
                    status = "pending"
                conn.execute(
                    """INSERT INTO acceptance_checks(check_key,requirement_key,description,required,status,expected_evidence_json,active,updated_at)
                       VALUES(?,?,?,?,?,?,1,?)
                       ON CONFLICT(check_key) DO UPDATE SET requirement_key=excluded.requirement_key,
                         description=excluded.description,required=excluded.required,status=excluded.status,
                         expected_evidence_json=excluded.expected_evidence_json,active=1,updated_at=excluded.updated_at""",
                    (check_id, req_id, description, required, status, expected, stamp),
                )
        _event(conn, "SCOPE_SYNCED", f"Synced approved scope for {phase}", {
            "manifest_hash": digest, "requirements": req_ids, "checks": check_ids,
        })
    return {"phase": phase, "manifest_hash": digest, "requirements": req_ids, "checks": check_ids}


def _refresh_requirement(conn: sqlite3.Connection, req_id: str) -> None:
    req = conn.execute("SELECT disposition FROM requirements WHERE requirement_key=?", (req_id,)).fetchone()
    if not req:
        return
    if req["disposition"] in {"deferred", "waived"}:
        status = req["disposition"]
    else:
        values = [r["status"] for r in conn.execute(
            "SELECT status FROM acceptance_checks WHERE requirement_key=? AND active=1 AND required=1", (req_id,)
        )]
        if any(v == "failed" for v in values): status = "failed"
        elif any(v == "blocked" for v in values): status = "blocked"
        elif values and all(v == "passed" for v in values): status = "verified"
        elif any(v == "passed" for v in values): status = "in_progress"
        else: status = "planned"
    conn.execute("UPDATE requirements SET status=?,updated_at=? WHERE requirement_key=?", (status, now(), req_id))


def record_check_evidence(
    db: Path, *, check_keys: Iterable[str], kind: str, status: str, value: str,
    commit_sha: str | None, task_key: str | None = None, workspace_id: str | None = None,
    artifact_ref: str | None = None,
) -> int:
    if status not in {"passed", "failed", "info"}:
        raise ContinuityError(f"invalid evidence status: {status}")
    keys = list(dict.fromkeys(check_keys))
    if not keys:
        raise ContinuityError("at least one check id is required")
    init(db)
    with connect(db) as conn:
        q = f"SELECT check_key,requirement_key FROM acceptance_checks WHERE active=1 AND check_key IN ({','.join('?' for _ in keys)})"
        rows = conn.execute(q, keys).fetchall()
        found = {r["check_key"]: r["requirement_key"] for r in rows}
        missing = [k for k in keys if k not in found]
        if missing:
            raise ContinuityError(f"unknown/inactive checks: {', '.join(missing)}")
        req_ids = sorted(set(found.values()))
        req_id = req_ids[0] if len(req_ids) == 1 else None
        cur = conn.execute(
            """INSERT INTO evidence_records(task_key,requirement_key,kind,status,value,commit_sha,workspace_id,artifact_ref,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (task_key, req_id, kind, status, value, commit_sha, workspace_id, artifact_ref, now()),
        )
        evidence_id = int(cur.lastrowid)
        for key in keys:
            conn.execute("INSERT INTO check_evidence(check_key,evidence_id) VALUES(?,?)", (key, evidence_id))
            if status in {"passed", "failed"}:
                conn.execute("UPDATE acceptance_checks SET status=?,updated_at=? WHERE check_key=?", (status, now(), key))
        for req in req_ids:
            _refresh_requirement(conn, req)
        _event(conn, "EVIDENCE_RECORDED", f"Recorded {status} {kind} evidence", {
            "evidence_id": evidence_id, "checks": keys, "commit": commit_sha,
        })
        return evidence_id


def set_check_state(db: Path, check_id: str, status: str) -> None:
    if status not in {"pending", "blocked", "failed"}:
        raise ContinuityError("manual check state may only be pending/blocked/failed")
    init(db)
    with connect(db) as conn:
        row = conn.execute(
            "SELECT requirement_key FROM acceptance_checks WHERE check_key=? AND active=1", (check_id,)
        ).fetchone()
        if not row:
            raise ContinuityError(f"unknown/inactive check: {check_id}")
        conn.execute("UPDATE acceptance_checks SET status=?,updated_at=? WHERE check_key=?", (status, now(), check_id))
        _refresh_requirement(conn, row["requirement_key"])


def _manifest_row(conn: sqlite3.Connection, phase: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM scope_manifests WHERE project_key=? AND phase_key=?", (PROJECT_KEY, phase)
    ).fetchone()


def run_gate(db: Path, phase: str, commit_sha: str, *, require_pr: bool = True) -> dict[str, Any]:
    init(db)
    failures: list[dict[str, str]] = []
    with connect(db) as conn:
        manifest = _manifest_row(conn, phase)
        digest = manifest["content_hash"] if manifest else "missing"
        if not manifest:
            failures.append({"id": "manifest", "reason": "no synced approved scope manifest"})
        else:
            reqs = conn.execute(
                "SELECT * FROM requirements WHERE phase_key=? AND active=1 ORDER BY requirement_key", (phase,)
            ).fetchall()
            for req in reqs:
                if req["disposition"] != "required":
                    continue
                checks = conn.execute(
                    "SELECT * FROM acceptance_checks WHERE requirement_key=? AND active=1 AND required=1 ORDER BY check_key",
                    (req["requirement_key"],),
                ).fetchall()
                if not checks:
                    failures.append({"id": req["requirement_key"], "reason": "required requirement has no required checks"})
                    continue
                for check in checks:
                    check_id = check["check_key"]
                    if check["status"] != "passed":
                        failures.append({"id": check_id, "reason": f"check status is {check['status']}"})
                        continue
                    expected_kinds = json.loads(check["expected_evidence_json"] or "[]")
                    kinds = expected_kinds or [None]
                    for expected_kind in kinds:
                        sql = """SELECT er.id FROM evidence_records er JOIN check_evidence ce ON ce.evidence_id=er.id
                                 WHERE ce.check_key=? AND er.status='passed' AND er.commit_sha=?"""
                        params: list[Any] = [check_id, commit_sha]
                        if expected_kind is not None:
                            sql += " AND er.kind=?"
                            params.append(expected_kind)
                        sql += " ORDER BY er.id DESC LIMIT 1"
                        if conn.execute(sql, params).fetchone() is None:
                            label = f"{expected_kind} evidence" if expected_kind else "passed evidence"
                            failures.append({"id": check_id, "reason": f"missing {label} bound to commit {commit_sha}"})
        tasks = conn.execute("SELECT * FROM tasks WHERE phase_key=?", (phase,)).fetchall()
        if require_pr and (not tasks or not any(t["pr_number"] is not None for t in tasks)):
            failures.append({"id": "pr", "reason": "no task in phase is linked to a PR"})
        status = "failed" if failures else "passed"
        cur = conn.execute(
            "INSERT INTO gate_runs(phase_key,manifest_hash,commit_sha,status,failures_json,created_at) VALUES(?,?,?,?,?,?)",
            (phase, digest, commit_sha, status, json.dumps(failures, sort_keys=True), now()),
        )
        gate_id = int(cur.lastrowid)
        if status == "passed":
            conn.execute("UPDATE requirements SET status='done',updated_at=? WHERE phase_key=? AND active=1 AND disposition='required'", (now(), phase))
        _event(conn, "GATE_PASSED" if status == "passed" else "GATE_FAILED", f"Completion gate {status} for {phase}", {
            "gate_id": gate_id, "commit": commit_sha, "manifest_hash": digest, "failures": failures,
        })
    return {"gate_id": gate_id, "phase": phase, "commit": commit_sha, "status": status, "failures": failures, "manifest_hash": digest}


def _require_gate(conn: sqlite3.Connection, phase: str, commit_sha: str | None) -> None:
    manifest = _manifest_row(conn, phase)
    if not manifest:
        raise ContinuityError(f"phase {phase} has no synced scope manifest")
    sql = "SELECT 1 FROM gate_runs WHERE phase_key=? AND manifest_hash=? AND status='passed'"
    params: list[Any] = [phase, manifest["content_hash"]]
    if commit_sha:
        sql += " AND commit_sha=?"
        params.append(commit_sha)
    sql += " ORDER BY id DESC LIMIT 1"
    if not conn.execute(sql, params).fetchone():
        suffix = f" for commit {commit_sha}" if commit_sha else ""
        raise ContinuityError(f"phase {phase} cannot complete: no passing gate for current scope{suffix}")


def set_phase(db: Path, key: str, title: str, status: str, *, commit_sha: str | None = None) -> None:
    init(db)
    stamp = now()
    with connect(db) as conn:
        if status == "completed" and _manifest_row(conn, key):
            _require_gate(conn, key, commit_sha)
        conn.execute(
            """INSERT INTO phases(phase_key,title,status,started_at,completed_at) VALUES(?,?,?,?,?)
               ON CONFLICT(phase_key) DO UPDATE SET title=excluded.title,status=excluded.status,
                 started_at=COALESCE(phases.started_at,excluded.started_at),completed_at=excluded.completed_at""",
            (key, title, status, stamp if status == "in_progress" else None, stamp if status == "completed" else None),
        )
        conn.execute("UPDATE project_state SET current_phase=?,updated_at=? WHERE project_key=?", (key, stamp, PROJECT_KEY))
        _event(conn, "phase", f"Phase {key} -> {status}", {"title": title, "commit": commit_sha})


def upsert_task(db: Path, key: str, phase: str, title: str, status: str, acceptance: str | None,
                branch: str | None, pr_number: int | None = None, *, commit_sha: str | None = None) -> None:
    init(db)
    stamp = now()
    with connect(db) as conn:
        if status == "completed" and _manifest_row(conn, phase):
            _require_gate(conn, phase, commit_sha)
        conn.execute(
            """INSERT INTO tasks(task_key,phase_key,title,status,acceptance,branch,pr_number,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)
               ON CONFLICT(task_key) DO UPDATE SET phase_key=excluded.phase_key,title=excluded.title,status=excluded.status,
                 acceptance=COALESCE(excluded.acceptance,tasks.acceptance),branch=COALESCE(excluded.branch,tasks.branch),
                 pr_number=COALESCE(excluded.pr_number,tasks.pr_number),updated_at=excluded.updated_at""",
            (key, phase, title, status, acceptance, branch, pr_number, stamp, stamp),
        )
        conn.execute("UPDATE project_state SET current_task=?,updated_at=? WHERE project_key=?", (key if status != "completed" else None, stamp, PROJECT_KEY))


def set_task_pr(db: Path, task: str, number: int) -> None:
    init(db)
    with connect(db) as conn:
        if not conn.execute("UPDATE tasks SET pr_number=?,updated_at=? WHERE task_key=?", (number, now(), task)).rowcount:
            raise ContinuityError(f"unknown task: {task}")
        _event(conn, "PR_LINKED", f"Linked {task} to PR #{number}", {"task": task, "pr": number})


def record_event(db: Path, kind: str, message: str, metadata: str) -> None:
    init(db)
    with connect(db) as conn:
        _event(conn, kind, message, json.loads(metadata))


def checkpoint(db: Path, phase: str, summary: str, commit: str | None) -> None:
    init(db)
    with connect(db) as conn:
        conn.execute("INSERT INTO checkpoints(phase_key,commit_sha,summary,created_at) VALUES(?,?,?,?)", (phase, commit, summary, now()))


def legacy_evidence(db: Path, task: str | None, kind: str, value: str) -> None:
    init(db)
    with connect(db) as conn:
        conn.execute("INSERT INTO evidence(task_key,kind,value,created_at) VALUES(?,?,?,?)", (task, kind, value, now()))


def _scope_snapshot(conn: sqlite3.Connection, phase: str | None) -> dict[str, Any] | None:
    if not phase:
        return None
    manifest = _manifest_row(conn, phase)
    if not manifest:
        return None
    reqs = conn.execute("SELECT * FROM requirements WHERE phase_key=? AND active=1 ORDER BY requirement_key", (phase,)).fetchall()
    rendered: list[dict[str, Any]] = []
    first: str | None = None
    for req in reqs:
        checks = conn.execute("SELECT * FROM acceptance_checks WHERE requirement_key=? AND active=1 ORDER BY check_key", (req["requirement_key"],)).fetchall()
        if first is None and req["disposition"] == "required":
            first = next((c["check_key"] for c in checks if c["required"] and c["status"] != "passed"), None)
        item = dict(req)
        item["checks"] = [dict(c) for c in checks]
        rendered.append(item)
    gate = conn.execute("SELECT * FROM gate_runs WHERE phase_key=? ORDER BY id DESC LIMIT 1", (phase,)).fetchone()
    return {"manifest": dict(manifest), "requirements": rendered, "last_gate": dict(gate) if gate else None, "first_unfinished_check": first}


def bootstrap(db: Path) -> dict[str, Any]:
    init(db)
    with connect(db) as conn:
        project = conn.execute("SELECT * FROM project_state WHERE project_key=?", (PROJECT_KEY,)).fetchone()
        phases = conn.execute("SELECT * FROM phases ORDER BY id").fetchall()
        tasks = conn.execute("SELECT * FROM tasks WHERE status IN ('in_progress','blocked','planned') ORDER BY id LIMIT 20").fetchall()
        checkpoint_row = conn.execute("SELECT * FROM checkpoints ORDER BY id DESC LIMIT 1").fetchone()
        events = conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT 10").fetchall()
        scope = _scope_snapshot(conn, project["current_phase"] if project else None)
    return {
        "project": dict(project) if project else None,
        "phases": [dict(r) for r in phases],
        "active_tasks": [dict(r) for r in tasks],
        "scope": scope,
        "last_checkpoint": dict(checkpoint_row) if checkpoint_row else None,
        "recent_events": [dict(r) for r in events],
        "workspace": git_state(),
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init"); sub.add_parser("bootstrap")
    s = sub.add_parser("manifest-sync"); s.add_argument("manifest", type=Path); s.add_argument("--commit")
    ph = sub.add_parser("phase"); ph.add_argument("key"); ph.add_argument("title"); ph.add_argument("status", choices=["planned","in_progress","completed","blocked"]); ph.add_argument("--commit")
    t = sub.add_parser("task"); t.add_argument("key"); t.add_argument("phase"); t.add_argument("title"); t.add_argument("status", choices=["planned","in_progress","completed","blocked"]); t.add_argument("--acceptance"); t.add_argument("--branch"); t.add_argument("--pr-number", type=int); t.add_argument("--commit")
    pr = sub.add_parser("pr"); pr.add_argument("task"); pr.add_argument("number", type=int)
    ch = sub.add_parser("check"); ch.add_argument("key"); ch.add_argument("status", choices=["pending","blocked","failed"])
    evn = sub.add_parser("event"); evn.add_argument("kind"); evn.add_argument("message"); evn.add_argument("--metadata", default="{}")
    cp = sub.add_parser("checkpoint"); cp.add_argument("phase"); cp.add_argument("summary"); cp.add_argument("--commit")
    e = sub.add_parser("evidence"); e.add_argument("kind"); e.add_argument("value"); e.add_argument("--task"); e.add_argument("--check", action="append", default=[]); e.add_argument("--status", choices=["passed","failed","info"], default="passed"); e.add_argument("--commit"); e.add_argument("--workspace"); e.add_argument("--artifact")
    g = sub.add_parser("gate"); g.add_argument("phase"); g.add_argument("--commit", required=True); g.add_argument("--allow-no-pr", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.command == "init": init(args.db)
        elif args.command == "bootstrap": print(json.dumps(bootstrap(args.db), indent=2, ensure_ascii=False))
        elif args.command == "manifest-sync": print(json.dumps(sync_manifest(args.db, args.manifest, args.commit), indent=2))
        elif args.command == "phase": set_phase(args.db, args.key, args.title, args.status, commit_sha=args.commit)
        elif args.command == "task": upsert_task(args.db, args.key, args.phase, args.title, args.status, args.acceptance, args.branch, args.pr_number, commit_sha=args.commit)
        elif args.command == "pr": set_task_pr(args.db, args.task, args.number)
        elif args.command == "check": set_check_state(args.db, args.key, args.status)
        elif args.command == "event": record_event(args.db, args.kind, args.message, args.metadata)
        elif args.command == "checkpoint": checkpoint(args.db, args.phase, args.summary, args.commit)
        elif args.command == "evidence":
            if args.check:
                eid = record_check_evidence(args.db, check_keys=args.check, kind=args.kind, status=args.status, value=args.value, commit_sha=args.commit, task_key=args.task, workspace_id=args.workspace, artifact_ref=args.artifact)
                print(json.dumps({"evidence_id": eid}))
            else: legacy_evidence(args.db, args.task, args.kind, args.value)
        elif args.command == "gate":
            result = run_gate(args.db, args.phase, args.commit, require_pr=not args.allow_no_pr)
            print(json.dumps(result, indent=2))
            if result["status"] != "passed": raise SystemExit(2)
    except ContinuityError as exc:
        p = argparse.ArgumentParser()
        p.error(str(exc))


if __name__ == "__main__":
    main()
