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

-- Agent Continuity v0.2: approved scope and completion traceability.
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
