# Agent Continuity experiment

KomaMori is the first live test bed for the Agent Continuity method.

## Goal

A fresh cloud development session should be able to continue work without depending on previous chat context or an earlier sandbox, **and must not silently lose any approved requirement while doing so**.

```text
ephemeral agent/session
       ↓
GitHub ─────────────── implementation + approved scope manifests
       ↓
SQLite state snapshot ─ execution state + check-level evidence + gate history
       ↓
bootstrap / reconciliation
       ↓
resume first unfinished promised check
```

## Source-of-truth boundaries

- **Git-tracked scope manifest**: what the phase/task promises, with stable Requirement and Acceptance Check IDs.
- **GitHub**: code, docs, commits, branches, PRs, CI and reviewable artifacts.
- **Agent Continuity SQLite**: current phase/task, manifest revision, requirement/check state, event ledger, checkpoints, evidence mappings and gate runs.
- **ChatGPT Library during this experiment**: durable backing copy of the SQLite state file between ephemeral sessions.
- **Chat history**: optional context only; never required to resume or decide completion.

The SQLite database is intentionally excluded from Git. Approved scope is intentionally **not** excluded from Git: multi-part phases use `.agent-continuity/plans/<phase>.toml` so the promised work can be reviewed in the same PR history as the implementation.

## v0.2 completion model

```text
Phase
└── Requirement P5-R01
    ├── Acceptance Check P5-R01-C01
    │   └── Evidence bound to commit/workspace
    └── Acceptance Check P5-R01-C02
        └── Evidence bound to commit/workspace
```

A broad task title such as `CRUD`, `editor`, or `QA` is not completion evidence. If create/read/update/delete can fail independently, they need independently traceable checks when all four are required.

States such as `pending`, `blocked`, `failed`, `deferred`, `waived`, and `passed` are intentionally distinct. Omission is never treated as implicit deferral.

## Bootstrap protocol

1. Obtain repository identity and current Git state.
2. Restore `.agent-continuity/state.db` from the durable backing store.
3. Run `python scripts/continuity.py bootstrap`.
4. Validate SQLite integrity/schema.
5. Compare Git/workspace state with the recorded checkpoint.
6. Compare the synced manifest hash with the current Git-tracked scope manifest.
7. Stop and reconcile on material drift.
8. Read the active phase/task plus the manifest requirements/checks and latest gate.
9. Resume from `first_unfinished_check`, not merely from a narrative `next action`.
10. After meaningful work, record check-level evidence and publish the refreshed SQLite snapshot.

## Commands

```bash
python scripts/continuity.py init
python scripts/continuity.py bootstrap

# Sync approved scope into durable state.
python scripts/continuity.py manifest-sync \
  .agent-continuity/plans/phase-5.toml \
  --commit <scope-commit>

python scripts/continuity.py phase phase-5 \
  "Agent Continuity v0.2 completion traceability" \
  in_progress

python scripts/continuity.py task p5-continuity phase-5 \
  "Upgrade Agent Continuity runtime" \
  in_progress \
  --branch phase-5-completeness-integrity

# Link the implementation PR.
python scripts/continuity.py pr p5-continuity 6

# One evidence record may satisfy several checks, but it must name them explicitly.
python scripts/continuity.py evidence test "pytest + CI passed" \
  --task p5-continuity \
  --status passed \
  --commit <verified-commit> \
  --check P5-R01-C01 \
  --check P5-R01-C02

# Fail closed when required checks/evidence/PR linkage are missing.
python scripts/continuity.py gate phase-5 --commit <verified-commit>

# Completion is rejected unless a passing gate exists for the current manifest hash.
python scripts/continuity.py task p5-continuity phase-5 \
  "Upgrade Agent Continuity runtime" completed \
  --commit <verified-commit>
python scripts/continuity.py phase phase-5 \
  "Agent Continuity v0.2 completion traceability" completed \
  --commit <verified-commit>

python scripts/continuity.py checkpoint phase-5 \
  "Phase 5 merged" --commit <merge-sha>
```

## Completion gate

A phase using a scope manifest may become completed only when the latest gate for the **current manifest hash** passes. The gate checks at least:

- every active required Requirement has required Acceptance Checks;
- every required Acceptance Check is `passed`;
- every required check has passed evidence bound to the commit being gated;
- the phase has explicit PR linkage unless the caller intentionally opts out;
- there is no required blocked/failed/pending check.

The gate records all missing IDs. A generic `failed` result is not sufficient because the next agent needs to know exactly what remains.

If the manifest changes, the hash changes and earlier gate success no longer authorizes completion. The new scope must be synced, satisfied, and gated again.

## Persistent Library mode

```text
fetch Library object version N
  → materialize state.db
  → schema/integrity check
  → reconcile Git + manifest
  → execute/checkpoint
  → close SQLite
  → upload only against observed Library version N
  → Library version N+1
```

A version mismatch is a conflict signal. Do not force overwrite a newer state snapshot.

## Acceptance property

Agent Continuity is not proven because the database can be written. A real test must demonstrate that a fresh session can recover both:

1. **where execution stopped**, and
2. **which approved checks are still unfinished**.

KomaMori already validated destructive restore of its v0.1 phase/checkpoint history. Phase 5 extends that experiment to scope completeness and fail-closed completion gates.
