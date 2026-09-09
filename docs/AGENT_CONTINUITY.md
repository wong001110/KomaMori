# Agent Continuity experiment

KomaMori is the first live test bed for the Agent Continuity method.

## Goal

A fresh cloud development session should be able to continue work without depending on the previous chat context or previous sandbox filesystem.

```text
ephemeral agent/session
       ↓
GitHub ─────────────── code + review history
       ↓
SQLite state snapshot ─ execution state
       ↓
bootstrap protocol
       ↓
resume from verified checkpoint
```

## Source-of-truth boundaries

- **GitHub**: code, docs, commits, branches, PRs, reviewable artifacts.
- **Agent Continuity SQLite**: current phase/task, event ledger, checkpoints, evidence pointers.
- **ChatGPT Library during this experiment**: durable backing copy of the SQLite state file between ephemeral sessions.
- **Chat history**: optional context only; never required to resume.

The SQLite database is intentionally excluded from Git. A session materializes/restores it from the durable backing store, operates on a working copy, then publishes an updated snapshot after meaningful checkpoints.

## Bootstrap protocol

1. Obtain the repository and current default-branch HEAD.
2. Restore `.agent-continuity/state.db` from the durable backing store.
3. Run `python scripts/continuity.py bootstrap`.
4. Compare the recorded checkpoint with GitHub state.
5. If state and Git disagree, stop advancement and reconcile before editing.
6. Resume the highest-priority active task.
7. After implementation and verification, record evidence and checkpoint state.
8. Publish the new SQLite snapshot back to the durable backing store.

## Commands

```bash
python scripts/continuity.py init
python scripts/continuity.py bootstrap
python scripts/continuity.py phase phase-0 "Project foundation" in_progress
python scripts/continuity.py task p0-foundation phase-0 "Create application foundation" in_progress --branch phase-0-foundation
python scripts/continuity.py evidence test "pytest: 1 passed" --task p0-foundation
python scripts/continuity.py checkpoint phase-0 "Foundation merged" --commit <sha>
```

## State-machine rule

A phase may advance only when:

- its implementation PR is merged;
- required tests/checks have evidence;
- a checkpoint records the merged commit;
- the durable state snapshot has been refreshed.

This is deliberately stricter than normal local development so the experiment can reveal whether continuity survives a disposable execution environment.
