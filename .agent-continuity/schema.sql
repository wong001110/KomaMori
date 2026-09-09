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
