#!/usr/bin/env python3
"""Agent Continuity v0.3 runtime extension for source capture, invariants, impact staleness, and fresh review."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

import continuity as base

SOURCE_KINDS = {"user", "spec", "reviewer", "defect", "policy", "scope_change"}
SOURCE_DISPOSITIONS = {"unmapped", "mapped", "deferred", "waived", "superseded", "rejected"}
FINDING_STATUSES = {"open", "mapped", "fixed", "verified", "deferred", "waived", "rejected", "superseded"}
TERMINAL_FINDINGS = {"verified", "deferred", "waived", "rejected", "superseded"}


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise base.ContinuityError("expected a list")
    return [str(item).strip() for item in value if str(item).strip()]


def _replace_impacts(conn, table: str, key_col: str, key: str, item: dict[str, Any]) -> None:
    conn.execute(f"DELETE FROM {table} WHERE {key_col}=?", (key,))
    impacts = item.get("impacts") or {}
    if not isinstance(impacts, dict):
        raise base.ContinuityError(f"impacts for {key} must be an object/table")
    for kind, field in (("domain", "domains"), ("module", "modules"), ("invariant", "invariants")):
        for value in _as_list(impacts.get(field)):
            conn.execute(f"INSERT INTO {table}({key_col},kind,value) VALUES(?,?,?)", (key, kind, value))


def sync_manifest(db: Path, manifest_path: Path, commit: str | None = None) -> dict[str, Any]:
    manifest = base.load_manifest(manifest_path)
    result = base.sync_manifest(db, manifest_path, commit)
    phase = str(manifest["id"])
    stamp = base.now()
    source_ids: list[str] = []
    invariant_ids: list[str] = []
    with base.connect(db) as conn:
        conn.execute("UPDATE scope_sources SET active=0 WHERE phase_key=?", (phase,))
        conn.execute("UPDATE invariants SET active=0 WHERE phase_key=?", (phase,))
        for source in manifest.get("sources") or []:
            key = str(source.get("id") or "").strip()
            if not key or key in source_ids:
                raise base.ContinuityError(f"duplicate/empty source id: {key!r}")
            kind = str(source.get("kind") or "user")
            disposition = str(source.get("disposition") or "unmapped")
            if kind not in SOURCE_KINDS or disposition not in SOURCE_DISPOSITIONS:
                raise base.ContinuityError(f"invalid source {key}")
            source_ids.append(key)
            summary = str(source.get("summary") or source.get("title") or key)
            conn.execute(
                """INSERT INTO scope_sources(source_key,phase_key,kind,summary,disposition,reason,destination,authority_ref,origin_ref,active,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,1,?,?)
                   ON CONFLICT(source_key) DO UPDATE SET phase_key=excluded.phase_key,kind=excluded.kind,summary=excluded.summary,
                     disposition=excluded.disposition,reason=excluded.reason,destination=excluded.destination,
                     authority_ref=excluded.authority_ref,origin_ref=excluded.origin_ref,active=1,updated_at=excluded.updated_at""",
                (key, phase, kind, summary, disposition, source.get("reason"), source.get("destination"),
                 source.get("authority_ref"), source.get("origin_ref"), stamp, stamp),
            )
            if kind in {"reviewer", "defect"} or key.startswith("FND-"):
                status = str(source.get("finding_status") or ("mapped" if disposition == "mapped" else "open"))
                if status not in FINDING_STATUSES:
                    raise base.ContinuityError(f"invalid finding status for {key}")
                conn.execute(
                    """INSERT INTO review_findings(finding_key,phase_key,severity,title,description,status,discovered_commit,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(finding_key) DO UPDATE SET phase_key=excluded.phase_key,severity=excluded.severity,title=excluded.title,
                         description=excluded.description,status=excluded.status,discovered_commit=COALESCE(excluded.discovered_commit,review_findings.discovered_commit),updated_at=excluded.updated_at""",
                    (key, phase, str(source.get("severity") or "P1"), summary,
                     str(source.get("description") or summary), status, source.get("discovered_commit"), stamp, stamp),
                )
        for inv in manifest.get("invariants") or []:
            key = str(inv.get("id") or "").strip()
            if not key or key in invariant_ids:
                raise base.ContinuityError(f"duplicate/empty invariant id: {key!r}")
            invariant_ids.append(key)
            status = str(inv.get("status") or "active")
            if status not in {"active", "deferred", "retired"}:
                raise base.ContinuityError(f"invalid invariant status for {key}")
            conn.execute(
                """INSERT INTO invariants(invariant_key,phase_key,description,severity,status,last_verified_commit,active,created_at,updated_at)
                   VALUES(?,?,?,?,?,NULL,1,?,?)
                   ON CONFLICT(invariant_key) DO UPDATE SET phase_key=excluded.phase_key,description=excluded.description,
                     severity=excluded.severity,status=excluded.status,active=1,updated_at=excluded.updated_at""",
                (key, phase, str(inv.get("description") or inv.get("title") or key), str(inv.get("severity") or "P1"), status, stamp, stamp),
            )
        for req in manifest.get("requirements") or []:
            req_id = str(req["id"])
            conn.execute("DELETE FROM source_requirements WHERE requirement_key=?", (req_id,))
            for ref in _as_list(req.get("source_refs")):
                if source_ids and ref not in source_ids:
                    raise base.ContinuityError(f"requirement {req_id} references unknown source {ref}")
                conn.execute("INSERT INTO source_requirements(source_key,requirement_key) VALUES(?,?)", (ref, req_id))
                conn.execute("UPDATE scope_sources SET disposition='mapped',updated_at=? WHERE source_key=? AND disposition='unmapped'", (stamp, ref))
                conn.execute("UPDATE review_findings SET status='mapped',updated_at=? WHERE finding_key=? AND status='open'", (stamp, ref))
            _replace_impacts(conn, "requirement_impacts", "requirement_key", req_id, req)
            for check in req.get("checks") or []:
                check_id = str(check["id"])
                check_obj = dict(check)
                if "impacts" not in check_obj:
                    check_obj["impacts"] = req.get("impacts") or {}
                _replace_impacts(conn, "check_impacts", "check_key", check_id, check_obj)
        base._event(conn, "SCOPE_SOURCES_SYNCED", f"Synced v0.3 source/invariant mappings for {phase}", {
            "sources": source_ids, "invariants": invariant_ids,
        })
    return {**result, "sources": source_ids, "invariants": invariant_ids}


def capture_gate(db: Path, phase: str) -> dict[str, Any]:
    base.init(db)
    failures: list[dict[str, str]] = []
    with base.connect(db) as conn:
        manifest = base._manifest_row(conn, phase)
        digest = manifest["content_hash"] if manifest else "missing"
        if not manifest:
            failures.append({"id": "manifest", "reason": "no synced scope manifest"})
        for source in conn.execute("SELECT * FROM scope_sources WHERE phase_key=? AND active=1 ORDER BY source_key", (phase,)):
            disposition = source["disposition"]
            if disposition == "unmapped":
                failures.append({"id": source["source_key"], "reason": "source is unmapped"})
            elif disposition == "mapped" and not conn.execute("SELECT 1 FROM source_requirements WHERE source_key=?", (source["source_key"],)).fetchone():
                failures.append({"id": source["source_key"], "reason": "mapped source has no requirement mapping"})
            elif disposition in {"deferred", "waived", "rejected"} and not source["reason"]:
                failures.append({"id": source["source_key"], "reason": f"{disposition} source requires a reason"})
        for req in conn.execute("SELECT * FROM requirements WHERE phase_key=? AND active=1 AND disposition='required'", (phase,)):
            if not conn.execute("SELECT 1 FROM acceptance_checks WHERE requirement_key=? AND active=1 AND required=1", (req["requirement_key"],)).fetchone():
                failures.append({"id": req["requirement_key"], "reason": "required requirement has no required check"})
        for inv in conn.execute("SELECT * FROM invariants WHERE phase_key=? AND active=1 AND status='active'", (phase,)):
            if not conn.execute(
                """SELECT 1 FROM check_impacts ci JOIN acceptance_checks ac ON ac.check_key=ci.check_key
                   JOIN requirements r ON r.requirement_key=ac.requirement_key
                   WHERE ci.kind='invariant' AND ci.value=? AND ac.active=1 AND ac.required=1 AND r.active=1 AND r.disposition='required'""",
                (inv["invariant_key"],),
            ).fetchone():
                failures.append({"id": inv["invariant_key"], "reason": "active invariant has no required mapped check"})
        status = "failed" if failures else "passed"
        cur = conn.execute(
            "INSERT INTO scope_capture_gate_runs(phase_key,manifest_hash,status,failures_json,created_at) VALUES(?,?,?,?,?)",
            (phase, digest, status, json.dumps(failures, sort_keys=True), base.now()),
        )
        gate_id = int(cur.lastrowid)
        base._event(conn, "CAPTURE_GATE_PASSED" if status == "passed" else "CAPTURE_GATE_FAILED", f"Scope capture gate {status} for {phase}", {"gate_id": gate_id, "failures": failures})
    return {"gate_id": gate_id, "phase": phase, "manifest_hash": digest, "status": status, "failures": failures}


def _require_capture(conn, phase: str, digest: str) -> None:
    if not conn.execute(
        "SELECT 1 FROM scope_capture_gate_runs WHERE phase_key=? AND manifest_hash=? AND status='passed' ORDER BY id DESC LIMIT 1",
        (phase, digest),
    ).fetchone():
        raise base.ContinuityError(f"phase {phase} has no passing scope capture gate for current manifest")


def evidence(db: Path, *, check_keys: list[str], kind: str, status: str, value: str, commit: str | None, task: str | None, workspace: str | None, artifact: str | None) -> int:
    eid = base.record_check_evidence(db, check_keys=check_keys, kind=kind, status=status, value=value, commit_sha=commit, task_key=task, workspace_id=workspace, artifact_ref=artifact)
    if status == "passed":
        with base.connect(db) as conn:
            for key in check_keys:
                conn.execute("DELETE FROM check_staleness WHERE check_key=?", (key,))
    return eid


def impact(db: Path, phase: str, modules: Iterable[str], changed_ref: str | None) -> list[str]:
    modules = list(dict.fromkeys(m.strip() for m in modules if m.strip()))
    stale: set[str] = set()
    with base.connect(db) as conn:
        for row in conn.execute(
            """SELECT DISTINCT ci.check_key,ci.value FROM check_impacts ci
               JOIN acceptance_checks ac ON ac.check_key=ci.check_key JOIN requirements r ON r.requirement_key=ac.requirement_key
               WHERE ci.kind='module' AND ac.active=1 AND r.active=1 AND r.phase_key=?""", (phase,)
        ):
            mapped = row["value"].rstrip("/")
            if any(path == mapped or path.startswith(mapped + "/") or mapped.startswith(path.rstrip("/") + "/") for path in modules):
                stale.add(row["check_key"])
        for key in stale:
            conn.execute(
                """INSERT INTO check_staleness(check_key,stale,reason,changed_ref,updated_at) VALUES(?,1,?,?,?)
                   ON CONFLICT(check_key) DO UPDATE SET stale=1,reason=excluded.reason,changed_ref=excluded.changed_ref,updated_at=excluded.updated_at""",
                (key, f"impacted by module change: {', '.join(modules)}", changed_ref, base.now()),
            )
        if stale:
            base._event(conn, "EVIDENCE_STALE", f"Marked {len(stale)} checks stale", {"checks": sorted(stale), "modules": modules, "changed_ref": changed_ref})
    return sorted(stale)


def gate(db: Path, phase: str, commit: str, require_pr: bool = True) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    with base.connect(db) as conn:
        manifest = base._manifest_row(conn, phase)
        digest = manifest["content_hash"] if manifest else "missing"
        if not manifest:
            failures.append({"id": "manifest", "reason": "no synced scope manifest"})
        else:
            try:
                _require_capture(conn, phase, digest)
            except base.ContinuityError as exc:
                failures.append({"id": "capture-gate", "reason": str(exc)})
            for row in conn.execute(
                """SELECT cs.check_key FROM check_staleness cs JOIN acceptance_checks ac ON ac.check_key=cs.check_key
                   JOIN requirements r ON r.requirement_key=ac.requirement_key
                   WHERE cs.stale=1 AND ac.active=1 AND ac.required=1 AND r.active=1 AND r.disposition='required' AND r.phase_key=?""", (phase,)
            ):
                failures.append({"id": row["check_key"], "reason": "check evidence is stale after impacted change"})
    if failures:
        with base.connect(db) as conn:
            cur = conn.execute("INSERT INTO gate_runs(phase_key,manifest_hash,commit_sha,status,failures_json,created_at) VALUES(?,?,?,'failed',?,?)", (phase, digest, commit, json.dumps(failures), base.now()))
            base._event(conn, "GATE_FAILED", f"v0.3 completion gate failed for {phase}", {"gate_id": int(cur.lastrowid), "failures": failures})
        return {"phase": phase, "commit": commit, "status": "failed", "failures": failures, "manifest_hash": digest}
    result = base.run_gate(db, phase, commit, require_pr=require_pr)
    if result["status"] == "passed":
        with base.connect(db) as conn:
            conn.execute("UPDATE invariants SET last_verified_commit=?,updated_at=? WHERE phase_key=? AND active=1 AND status='active'", (commit, base.now(), phase))
    return result


def register_finding(db: Path, key: str, phase: str, severity: str, title: str, description: str, commit: str | None) -> None:
    base.init(db)
    stamp = base.now()
    with base.connect(db) as conn:
        conn.execute(
            """INSERT INTO scope_sources(source_key,phase_key,kind,summary,disposition,active,created_at,updated_at)
               VALUES(?,?,?,?, 'unmapped',1,?,?)
               ON CONFLICT(source_key) DO UPDATE SET phase_key=excluded.phase_key,kind='reviewer',summary=excluded.summary,disposition='unmapped',active=1,updated_at=excluded.updated_at""",
            (key, phase, "reviewer", title, stamp, stamp),
        )
        conn.execute(
            """INSERT INTO review_findings(finding_key,phase_key,severity,title,description,status,discovered_commit,created_at,updated_at)
               VALUES(?,?,?,?,?,'open',?,?,?)
               ON CONFLICT(finding_key) DO UPDATE SET severity=excluded.severity,title=excluded.title,description=excluded.description,status='open',discovered_commit=excluded.discovered_commit,updated_at=excluded.updated_at""",
            (key, phase, severity, title, description, commit, stamp, stamp),
        )
        base._event(conn, "REVIEW_FINDING", f"Registered {key}: {title}", {"severity": severity, "commit": commit})


def finding_state(db: Path, key: str, status: str, reason: str | None, destination: str | None) -> None:
    if status not in FINDING_STATUSES:
        raise base.ContinuityError(f"invalid finding status: {status}")
    with base.connect(db) as conn:
        if not conn.execute("SELECT 1 FROM review_findings WHERE finding_key=?", (key,)).fetchone():
            raise base.ContinuityError(f"unknown finding: {key}")
        conn.execute("UPDATE review_findings SET status=?,updated_at=? WHERE finding_key=?", (status, base.now(), key))
        disposition = "mapped" if status in {"mapped", "fixed", "verified"} else status
        if disposition in SOURCE_DISPOSITIONS:
            conn.execute("UPDATE scope_sources SET disposition=?,reason=COALESCE(?,reason),destination=COALESCE(?,destination),updated_at=? WHERE source_key=?", (disposition, reason, destination, base.now(), key))
        base._event(conn, "FINDING_STATE", f"Finding {key} -> {status}", {"reason": reason, "destination": destination})


def review_gate(db: Path, phase: str, commit: str, new_findings: Iterable[str]) -> dict[str, Any]:
    keys = list(dict.fromkeys(new_findings))
    with base.connect(db) as conn:
        unresolved = [r["finding_key"] for r in conn.execute("SELECT finding_key,status FROM review_findings WHERE phase_key=?", (phase,)) if r["status"] not in TERMINAL_FINDINGS]
        unresolved.extend(k for k in keys if not conn.execute("SELECT 1 FROM review_findings WHERE finding_key=?", (k,)).fetchone())
        unresolved = sorted(set(unresolved))
        status = "failed" if unresolved else "passed"
        cur = conn.execute(
            "INSERT INTO fresh_review_gate_runs(phase_key,commit_sha,status,new_findings_json,unresolved_findings_json,created_at) VALUES(?,?,?,?,?,?)",
            (phase, commit, status, json.dumps(keys), json.dumps(unresolved), base.now()),
        )
        gate_id = int(cur.lastrowid)
        base._event(conn, "FRESH_REVIEW_PASSED" if status == "passed" else "FRESH_REVIEW_FAILED", f"Fresh reviewer gate {status} for {phase}", {"gate_id": gate_id, "unresolved": unresolved})
    return {"gate_id": gate_id, "phase": phase, "commit": commit, "status": status, "new_findings": keys, "unresolved_findings": unresolved}


def _require_final_gates(db: Path, phase: str, commit: str | None) -> None:
    if not commit:
        raise base.ContinuityError("v0.3 completion requires --commit")
    with base.connect(db) as conn:
        manifest = base._manifest_row(conn, phase)
        if not manifest:
            return
        _require_capture(conn, phase, manifest["content_hash"])
        if not conn.execute("SELECT 1 FROM gate_runs WHERE phase_key=? AND manifest_hash=? AND commit_sha=? AND status='passed' ORDER BY id DESC LIMIT 1", (phase, manifest["content_hash"], commit)).fetchone():
            raise base.ContinuityError("no passing completion gate for current manifest/commit")
        if not conn.execute("SELECT 1 FROM fresh_review_gate_runs WHERE phase_key=? AND commit_sha=? AND status='passed' ORDER BY id DESC LIMIT 1", (phase, commit)).fetchone():
            raise base.ContinuityError("no passing fresh reviewer gate for current commit")


def phase(db: Path, key: str, title: str, status: str, commit: str | None) -> None:
    if status == "completed":
        _require_final_gates(db, key, commit)
    base.set_phase(db, key, title, status, commit_sha=commit)


def task(db: Path, key: str, phase_key: str, title: str, status: str, acceptance: str | None, branch: str | None, pr_number: int | None, commit: str | None) -> None:
    if status == "completed":
        _require_final_gates(db, phase_key, commit)
    base.upsert_task(db, key, phase_key, title, status, acceptance, branch, pr_number, commit_sha=commit)


def bootstrap(db: Path) -> dict[str, Any]:
    result = base.bootstrap(db)
    phase_key = result.get("project", {}).get("current_phase") if result.get("project") else None
    if not phase_key:
        return result
    with base.connect(db) as conn:
        result["scope_v03"] = {
            "sources": [dict(r) for r in conn.execute("SELECT * FROM scope_sources WHERE phase_key=? AND active=1 ORDER BY source_key", (phase_key,))],
            "findings": [dict(r) for r in conn.execute("SELECT * FROM review_findings WHERE phase_key=? ORDER BY finding_key", (phase_key,))],
            "invariants": [dict(r) for r in conn.execute("SELECT * FROM invariants WHERE phase_key=? AND active=1 ORDER BY invariant_key", (phase_key,))],
            "stale_checks": [dict(r) for r in conn.execute("SELECT cs.* FROM check_staleness cs JOIN acceptance_checks ac ON ac.check_key=cs.check_key JOIN requirements r ON r.requirement_key=ac.requirement_key WHERE cs.stale=1 AND r.phase_key=?", (phase_key,))],
            "last_capture_gate": (lambda r: dict(r) if r else None)(conn.execute("SELECT * FROM scope_capture_gate_runs WHERE phase_key=? ORDER BY id DESC LIMIT 1", (phase_key,)).fetchone()),
            "last_review_gate": (lambda r: dict(r) if r else None)(conn.execute("SELECT * FROM fresh_review_gate_runs WHERE phase_key=? ORDER BY id DESC LIMIT 1", (phase_key,)).fetchone()),
        }
    return result


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=base.DEFAULT_DB)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init"); sub.add_parser("bootstrap")
    m = sub.add_parser("manifest-sync"); m.add_argument("manifest", type=Path); m.add_argument("--commit")
    c = sub.add_parser("capture-gate"); c.add_argument("phase")
    ph = sub.add_parser("phase"); ph.add_argument("key"); ph.add_argument("title"); ph.add_argument("status", choices=["planned","in_progress","completed","blocked"]); ph.add_argument("--commit")
    t = sub.add_parser("task"); t.add_argument("key"); t.add_argument("phase"); t.add_argument("title"); t.add_argument("status", choices=["planned","in_progress","completed","blocked"]); t.add_argument("--acceptance"); t.add_argument("--branch"); t.add_argument("--pr-number", type=int); t.add_argument("--commit")
    pr = sub.add_parser("pr"); pr.add_argument("task"); pr.add_argument("number", type=int)
    e = sub.add_parser("evidence"); e.add_argument("kind"); e.add_argument("value"); e.add_argument("--task"); e.add_argument("--check", action="append", default=[]); e.add_argument("--status", choices=["passed","failed","info"], default="passed"); e.add_argument("--commit"); e.add_argument("--workspace"); e.add_argument("--artifact")
    i = sub.add_parser("impact"); i.add_argument("phase"); i.add_argument("--module", action="append", required=True); i.add_argument("--changed-ref")
    f = sub.add_parser("finding"); f.add_argument("key"); f.add_argument("phase"); f.add_argument("severity"); f.add_argument("title"); f.add_argument("description"); f.add_argument("--commit")
    fs = sub.add_parser("finding-state"); fs.add_argument("key"); fs.add_argument("status", choices=sorted(FINDING_STATUSES)); fs.add_argument("--reason"); fs.add_argument("--destination")
    g = sub.add_parser("gate"); g.add_argument("phase"); g.add_argument("--commit", required=True); g.add_argument("--allow-no-pr", action="store_true")
    r = sub.add_parser("review-gate"); r.add_argument("phase"); r.add_argument("--commit", required=True); r.add_argument("--finding", action="append", default=[])
    cp = sub.add_parser("checkpoint"); cp.add_argument("phase"); cp.add_argument("summary"); cp.add_argument("--commit")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.command == "init": base.init(args.db)
        elif args.command == "bootstrap": print(json.dumps(bootstrap(args.db), indent=2, ensure_ascii=False))
        elif args.command == "manifest-sync": print(json.dumps(sync_manifest(args.db, args.manifest, args.commit), indent=2))
        elif args.command == "capture-gate":
            result = capture_gate(args.db, args.phase); print(json.dumps(result, indent=2));
            if result["status"] != "passed": raise SystemExit(2)
        elif args.command == "phase": phase(args.db, args.key, args.title, args.status, args.commit)
        elif args.command == "task": task(args.db, args.key, args.phase, args.title, args.status, args.acceptance, args.branch, args.pr_number, args.commit)
        elif args.command == "pr": base.set_task_pr(args.db, args.task, args.number)
        elif args.command == "evidence":
            if not args.check: raise base.ContinuityError("v0.3 evidence requires at least one --check")
            print(json.dumps({"evidence_id": evidence(args.db, check_keys=args.check, kind=args.kind, status=args.status, value=args.value, commit=args.commit, task=args.task, workspace=args.workspace, artifact=args.artifact)}))
        elif args.command == "impact": print(json.dumps({"stale_checks": impact(args.db, args.phase, args.module, args.changed_ref)}, indent=2))
        elif args.command == "finding": register_finding(args.db, args.key, args.phase, args.severity, args.title, args.description, args.commit)
        elif args.command == "finding-state": finding_state(args.db, args.key, args.status, args.reason, args.destination)
        elif args.command == "gate":
            result = gate(args.db, args.phase, args.commit, require_pr=not args.allow_no_pr); print(json.dumps(result, indent=2));
            if result["status"] != "passed": raise SystemExit(2)
        elif args.command == "review-gate":
            result = review_gate(args.db, args.phase, args.commit, args.finding); print(json.dumps(result, indent=2));
            if result["status"] != "passed": raise SystemExit(2)
        elif args.command == "checkpoint": base.checkpoint(args.db, args.phase, args.summary, args.commit)
    except base.ContinuityError as exc:
        p.error(str(exc))


if __name__ == "__main__":
    main()
