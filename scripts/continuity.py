#!/usr/bin/env python3
"""Minimal Agent Continuity state manager for ephemeral development sessions."""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / ".agent-continuity" / "state.db"
SCHEMA = ROOT / ".agent-continuity" / "schema.sql"
PROJECT_KEY = "komamori"
REPO = "wong001110/KomaMori"


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
        conn.execute(
            """
            INSERT INTO project_state(project_key, repo, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(project_key) DO UPDATE SET repo=excluded.repo, updated_at=excluded.updated_at
            """,
            (PROJECT_KEY, REPO, now()),
        )
        conn.execute(
            """
            INSERT INTO events(kind, message, metadata_json, created_at)
            VALUES ('continuity', 'State store initialized', '{}', ?)
            """,
            (now(),),
        )


def git_state() -> dict[str, str | None]:
    def run(*args: str) -> str | None:
        try:
            return subprocess.check_output(args, cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip() or None
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None

    return {
        "branch": run("git", "branch", "--show-current"),
        "head": run("git", "rev-parse", "HEAD"),
        "dirty": run("git", "status", "--porcelain"),
    }


def bootstrap(path: Path) -> dict[str, Any]:
    with connect(path) as conn:
        project = conn.execute("SELECT * FROM project_state WHERE project_key = ?", (PROJECT_KEY,)).fetchone()
        phases = conn.execute("SELECT * FROM phases ORDER BY id").fetchall()
        tasks = conn.execute(
            "SELECT * FROM tasks WHERE status IN ('in_progress','blocked','planned') ORDER BY id LIMIT 20"
        ).fetchall()
        checkpoint_row = conn.execute("SELECT * FROM checkpoints ORDER BY id DESC LIMIT 1").fetchone()
        events = conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT 10").fetchall()

    return {
        "project": dict(project) if project else None,
        "phases": [dict(row) for row in phases],
        "active_tasks": [dict(row) for row in tasks],
        "last_checkpoint": dict(checkpoint_row) if checkpoint_row else None,
        "recent_events": [dict(row) for row in events],
        "workspace": git_state(),
    }


def set_phase(path: Path, key: str, title: str, status: str) -> None:
    timestamp = now()
    with connect(path) as conn:
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
        conn.execute(
            "UPDATE project_state SET current_phase=?, updated_at=? WHERE project_key=?",
            (key, timestamp, PROJECT_KEY),
        )
        conn.execute(
            "INSERT INTO events(kind, message, metadata_json, created_at) VALUES ('phase', ?, ?, ?)",
            (f"Phase {key} -> {status}", json.dumps({"title": title}), timestamp),
        )


def upsert_task(path: Path, key: str, phase: str, title: str, status: str, acceptance: str | None, branch: str | None) -> None:
    timestamp = now()
    with connect(path) as conn:
        conn.execute(
            """
            INSERT INTO tasks(task_key, phase_key, title, status, acceptance, branch, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_key) DO UPDATE SET
              phase_key=excluded.phase_key,
              title=excluded.title,
              status=excluded.status,
              acceptance=COALESCE(excluded.acceptance, tasks.acceptance),
              branch=COALESCE(excluded.branch, tasks.branch),
              updated_at=excluded.updated_at
            """,
            (key, phase, title, status, acceptance, branch, timestamp, timestamp),
        )
        conn.execute(
            "UPDATE project_state SET current_task=?, updated_at=? WHERE project_key=?",
            (key if status != "completed" else None, timestamp, PROJECT_KEY),
        )


def record_event(path: Path, kind: str, message: str, metadata: str) -> None:
    payload = json.loads(metadata)
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO events(kind, message, metadata_json, created_at) VALUES (?, ?, ?, ?)",
            (kind, message, json.dumps(payload), now()),
        )


def checkpoint(path: Path, phase: str, summary: str, commit: str | None) -> None:
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO checkpoints(phase_key, commit_sha, summary, created_at) VALUES (?, ?, ?, ?)",
            (phase, commit, summary, now()),
        )


def evidence(path: Path, task: str | None, kind: str, value: str) -> None:
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO evidence(task_key, kind, value, created_at) VALUES (?, ?, ?, ?)",
            (task, kind, value, now()),
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init")
    sub.add_parser("bootstrap")

    phase = sub.add_parser("phase")
    phase.add_argument("key")
    phase.add_argument("title")
    phase.add_argument("status", choices=["planned", "in_progress", "completed", "blocked"])

    task = sub.add_parser("task")
    task.add_argument("key")
    task.add_argument("phase")
    task.add_argument("title")
    task.add_argument("status", choices=["planned", "in_progress", "completed", "blocked"])
    task.add_argument("--acceptance")
    task.add_argument("--branch")

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

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "init":
        init(args.db)
    elif args.command == "bootstrap":
        print(json.dumps(bootstrap(args.db), indent=2, ensure_ascii=False))
    elif args.command == "phase":
        set_phase(args.db, args.key, args.title, args.status)
    elif args.command == "task":
        upsert_task(args.db, args.key, args.phase, args.title, args.status, args.acceptance, args.branch)
    elif args.command == "event":
        record_event(args.db, args.kind, args.message, args.metadata)
    elif args.command == "checkpoint":
        checkpoint(args.db, args.phase, args.summary, args.commit)
    elif args.command == "evidence":
        evidence(args.db, args.task, args.kind, args.value)


if __name__ == "__main__":
    main()
