PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS project_state (
  project_key TEXT PRIMARY KEY,
  repo TEXT NOT NULL,
  current_phase TEXT,
  current_task TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS phases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  phase_key TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('planned','in_progress','completed','blocked')),
  started_at TEXT,
  completed_at TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_key TEXT NOT NULL UNIQUE,
  phase_key TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('planned','in_progress','completed','blocked')),
  acceptance TEXT,
  branch TEXT,
  pr_number INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(phase_key) REFERENCES phases(phase_key)
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  message TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checkpoints (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  phase_key TEXT NOT NULL,
  commit_sha TEXT,
  summary TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_key TEXT,
  kind TEXT NOT NULL,
  value TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(task_key) REFERENCES tasks(task_key)
);

CREATE TABLE IF NOT EXISTS scope_manifests (
  manifest_id TEXT PRIMARY KEY,
  project_key TEXT NOT NULL,
  phase_key TEXT NOT NULL,
  path TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  git_commit TEXT,
  synced_at TEXT NOT NULL,
  UNIQUE(project_key, phase_key)
);

CREATE TABLE IF NOT EXISTS requirements (
  requirement_key TEXT PRIMARY KEY,
  phase_key TEXT NOT NULL,
  manifest_id TEXT NOT NULL,
  title TEXT NOT NULL,
  disposition TEXT NOT NULL CHECK(disposition IN ('required','optional','deferred','waived')),
  status TEXT NOT NULL CHECK(status IN ('planned','in_progress','verified','done','blocked','failed','deferred','waived')),
  reason TEXT,
  destination TEXT,
  active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
  updated_at TEXT NOT NULL,
  FOREIGN KEY(manifest_id) REFERENCES scope_manifests(manifest_id)
);

CREATE TABLE IF NOT EXISTS acceptance_checks (
  check_key TEXT PRIMARY KEY,
  requirement_key TEXT NOT NULL,
  description TEXT NOT NULL,
  required INTEGER NOT NULL DEFAULT 1 CHECK(required IN (0,1)),
  status TEXT NOT NULL CHECK(status IN ('pending','passed','failed','blocked','deferred','waived')),
  expected_evidence_json TEXT NOT NULL DEFAULT '[]',
  active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
  updated_at TEXT NOT NULL,
  FOREIGN KEY(requirement_key) REFERENCES requirements(requirement_key)
);

CREATE TABLE IF NOT EXISTS evidence_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_key TEXT,
  requirement_key TEXT,
  kind TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('passed','failed','info')),
  value TEXT NOT NULL,
  commit_sha TEXT,
  workspace_id TEXT,
  artifact_ref TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(task_key) REFERENCES tasks(task_key),
  FOREIGN KEY(requirement_key) REFERENCES requirements(requirement_key)
);

CREATE TABLE IF NOT EXISTS check_evidence (
  check_key TEXT NOT NULL,
  evidence_id INTEGER NOT NULL,
  PRIMARY KEY(check_key, evidence_id),
  FOREIGN KEY(check_key) REFERENCES acceptance_checks(check_key),
  FOREIGN KEY(evidence_id) REFERENCES evidence_records(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS gate_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  phase_key TEXT NOT NULL,
  manifest_hash TEXT NOT NULL,
  commit_sha TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('passed','failed')),
  failures_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scope_sources (
  source_key TEXT PRIMARY KEY,
  phase_key TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('user','spec','reviewer','defect','policy','scope_change')),
  summary TEXT NOT NULL,
  disposition TEXT NOT NULL CHECK(disposition IN ('unmapped','mapped','deferred','waived','superseded','rejected')),
  reason TEXT,
  destination TEXT,
  authority_ref TEXT,
  origin_ref TEXT,
  active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_requirements (
  source_key TEXT NOT NULL,
  requirement_key TEXT NOT NULL,
  PRIMARY KEY(source_key, requirement_key),
  FOREIGN KEY(source_key) REFERENCES scope_sources(source_key) ON DELETE CASCADE,
  FOREIGN KEY(requirement_key) REFERENCES requirements(requirement_key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS review_findings (
  finding_key TEXT PRIMARY KEY,
  phase_key TEXT NOT NULL,
  severity TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('open','mapped','fixed','verified','deferred','waived','rejected','superseded')),
  discovered_commit TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(finding_key) REFERENCES scope_sources(source_key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS invariants (
  invariant_key TEXT PRIMARY KEY,
  phase_key TEXT NOT NULL,
  description TEXT NOT NULL,
  severity TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('active','deferred','retired')),
  last_verified_commit TEXT,
  active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS requirement_impacts (
  requirement_key TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('domain','module','invariant')),
  value TEXT NOT NULL,
  PRIMARY KEY(requirement_key, kind, value),
  FOREIGN KEY(requirement_key) REFERENCES requirements(requirement_key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS check_impacts (
  check_key TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('domain','module','invariant')),
  value TEXT NOT NULL,
  PRIMARY KEY(check_key, kind, value),
  FOREIGN KEY(check_key) REFERENCES acceptance_checks(check_key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS check_staleness (
  check_key TEXT PRIMARY KEY,
  stale INTEGER NOT NULL DEFAULT 1 CHECK(stale IN (0,1)),
  reason TEXT NOT NULL,
  changed_ref TEXT,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(check_key) REFERENCES acceptance_checks(check_key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scope_capture_gate_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  phase_key TEXT NOT NULL,
  manifest_hash TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('passed','failed')),
  failures_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fresh_review_gate_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  phase_key TEXT NOT NULL,
  commit_sha TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('passed','failed')),
  new_findings_json TEXT NOT NULL DEFAULT '[]',
  unresolved_findings_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);

-- A passing Fresh Reviewer Gate must belong to the current capture generation:
-- latest capture is PASS and completion for the same commit happened after it.
CREATE TRIGGER IF NOT EXISTS guard_v03_review_after_completion
BEFORE INSERT ON fresh_review_gate_runs
WHEN NEW.status = 'passed'
 AND EXISTS (SELECT 1 FROM scope_sources s WHERE s.phase_key = NEW.phase_key AND s.active = 1)
BEGIN
  SELECT CASE WHEN (
    SELECT cg.status FROM scope_capture_gate_runs cg
    JOIN scope_manifests sm ON sm.phase_key=cg.phase_key AND sm.content_hash=cg.manifest_hash
    WHERE cg.phase_key=NEW.phase_key
    ORDER BY cg.id DESC LIMIT 1
  ) IS NOT 'passed' THEN RAISE(ABORT, 'v0.3 fresh review requires latest capture gate to pass') END;

  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM scope_manifests sm
    JOIN gate_runs g ON g.phase_key=sm.phase_key AND g.manifest_hash=sm.content_hash
    WHERE sm.phase_key=NEW.phase_key
      AND g.commit_sha=NEW.commit_sha
      AND g.status='passed'
      AND g.created_at >= (
        SELECT cg.created_at FROM scope_capture_gate_runs cg
        WHERE cg.phase_key=NEW.phase_key AND cg.manifest_hash=sm.content_hash
        ORDER BY cg.id DESC LIMIT 1
      )
  ) THEN RAISE(ABORT, 'v0.3 fresh review requires a passing completion gate after latest capture') END;
END;

CREATE TRIGGER IF NOT EXISTS guard_v03_phase_complete_update
BEFORE UPDATE OF status ON phases
WHEN NEW.status='completed'
 AND EXISTS (SELECT 1 FROM scope_sources s WHERE s.phase_key=NEW.phase_key AND s.active=1)
BEGIN
  SELECT CASE WHEN (
    SELECT cg.status FROM scope_capture_gate_runs cg
    JOIN scope_manifests sm ON sm.phase_key=cg.phase_key AND sm.content_hash=cg.manifest_hash
    WHERE cg.phase_key=NEW.phase_key ORDER BY cg.id DESC LIMIT 1
  ) IS NOT 'passed' THEN RAISE(ABORT, 'v0.3 phase completion requires latest capture gate to pass') END;

  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM scope_manifests sm
    JOIN gate_runs g ON g.phase_key=sm.phase_key AND g.manifest_hash=sm.content_hash AND g.status='passed'
    JOIN fresh_review_gate_runs fr ON fr.phase_key=g.phase_key AND fr.commit_sha=g.commit_sha AND fr.status='passed'
    WHERE sm.phase_key=NEW.phase_key
      AND g.created_at >= (
        SELECT cg.created_at FROM scope_capture_gate_runs cg
        WHERE cg.phase_key=NEW.phase_key AND cg.manifest_hash=sm.content_hash
        ORDER BY cg.id DESC LIMIT 1
      )
      AND fr.created_at >= g.created_at
  ) THEN RAISE(ABORT, 'v0.3 phase completion requires current completion and fresh-review gates') END;
END;

CREATE TRIGGER IF NOT EXISTS guard_v03_phase_complete_insert
BEFORE INSERT ON phases
WHEN NEW.status='completed'
 AND EXISTS (SELECT 1 FROM scope_sources s WHERE s.phase_key=NEW.phase_key AND s.active=1)
BEGIN
  SELECT CASE WHEN (
    SELECT cg.status FROM scope_capture_gate_runs cg
    JOIN scope_manifests sm ON sm.phase_key=cg.phase_key AND sm.content_hash=cg.manifest_hash
    WHERE cg.phase_key=NEW.phase_key ORDER BY cg.id DESC LIMIT 1
  ) IS NOT 'passed' THEN RAISE(ABORT, 'v0.3 phase completion requires latest capture gate to pass') END;

  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM scope_manifests sm
    JOIN gate_runs g ON g.phase_key=sm.phase_key AND g.manifest_hash=sm.content_hash AND g.status='passed'
    JOIN fresh_review_gate_runs fr ON fr.phase_key=g.phase_key AND fr.commit_sha=g.commit_sha AND fr.status='passed'
    WHERE sm.phase_key=NEW.phase_key
      AND g.created_at >= (
        SELECT cg.created_at FROM scope_capture_gate_runs cg
        WHERE cg.phase_key=NEW.phase_key AND cg.manifest_hash=sm.content_hash
        ORDER BY cg.id DESC LIMIT 1
      )
      AND fr.created_at >= g.created_at
  ) THEN RAISE(ABORT, 'v0.3 phase completion requires current completion and fresh-review gates') END;
END;

CREATE TRIGGER IF NOT EXISTS guard_v03_task_complete_update
BEFORE UPDATE OF status ON tasks
WHEN NEW.status='completed'
 AND EXISTS (SELECT 1 FROM scope_sources s WHERE s.phase_key=NEW.phase_key AND s.active=1)
BEGIN
  SELECT CASE WHEN (
    SELECT cg.status FROM scope_capture_gate_runs cg
    JOIN scope_manifests sm ON sm.phase_key=cg.phase_key AND sm.content_hash=cg.manifest_hash
    WHERE cg.phase_key=NEW.phase_key ORDER BY cg.id DESC LIMIT 1
  ) IS NOT 'passed' THEN RAISE(ABORT, 'v0.3 task completion requires latest capture gate to pass') END;

  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM scope_manifests sm
    JOIN gate_runs g ON g.phase_key=sm.phase_key AND g.manifest_hash=sm.content_hash AND g.status='passed'
    JOIN fresh_review_gate_runs fr ON fr.phase_key=g.phase_key AND fr.commit_sha=g.commit_sha AND fr.status='passed'
    WHERE sm.phase_key=NEW.phase_key
      AND g.created_at >= (
        SELECT cg.created_at FROM scope_capture_gate_runs cg
        WHERE cg.phase_key=NEW.phase_key AND cg.manifest_hash=sm.content_hash
        ORDER BY cg.id DESC LIMIT 1
      )
      AND fr.created_at >= g.created_at
  ) THEN RAISE(ABORT, 'v0.3 task completion requires current completion and fresh-review gates') END;
END;

CREATE TRIGGER IF NOT EXISTS guard_v03_task_complete_insert
BEFORE INSERT ON tasks
WHEN NEW.status='completed'
 AND EXISTS (SELECT 1 FROM scope_sources s WHERE s.phase_key=NEW.phase_key AND s.active=1)
BEGIN
  SELECT CASE WHEN (
    SELECT cg.status FROM scope_capture_gate_runs cg
    JOIN scope_manifests sm ON sm.phase_key=cg.phase_key AND sm.content_hash=cg.manifest_hash
    WHERE cg.phase_key=NEW.phase_key ORDER BY cg.id DESC LIMIT 1
  ) IS NOT 'passed' THEN RAISE(ABORT, 'v0.3 task completion requires latest capture gate to pass') END;

  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM scope_manifests sm
    JOIN gate_runs g ON g.phase_key=sm.phase_key AND g.manifest_hash=sm.content_hash AND g.status='passed'
    JOIN fresh_review_gate_runs fr ON fr.phase_key=g.phase_key AND fr.commit_sha=g.commit_sha AND fr.status='passed'
    WHERE sm.phase_key=NEW.phase_key
      AND g.created_at >= (
        SELECT cg.created_at FROM scope_capture_gate_runs cg
        WHERE cg.phase_key=NEW.phase_key AND cg.manifest_hash=sm.content_hash
        ORDER BY cg.id DESC LIMIT 1
      )
      AND fr.created_at >= g.created_at
  ) THEN RAISE(ABORT, 'v0.3 task completion requires current completion and fresh-review gates') END;
END;
