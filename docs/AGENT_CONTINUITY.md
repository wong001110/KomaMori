# Agent Continuity experiment

KomaMori is the live test bed for **Agent Continuity v0.3**.

## Goal

A fresh development session must recover not only where execution stopped, but also:

1. what the original source/request/reviewer findings were;
2. whether every material source item was captured into current scope;
3. which cross-cutting invariants may be affected by changes;
4. which acceptance checks still lack current evidence;
5. whether a fresh reviewer found any material defect outside the checklist.

```text
ephemeral agent/session
       ↓
ScopeSource / ReviewFinding registry
       ↓
Scope Capture Gate
       ↓
Git-tracked Requirements / Acceptance Checks / Invariants
       ↓
implementation + evidence + impact staleness
       ↓
Completion Gate       -> scope-complete
       ↓
Fresh Reviewer Gate   -> review-clear
       ↓
merge/checkpoint      -> finalized
```

`scope-complete` does **not** mean defect-free. It means the currently captured/approved scope has passed its gate.

## Source-of-truth boundaries

- **ScopeSource / ReviewFinding registry**: durable original intent, reviewer findings, discovered defects and explicit dispositions.
- **Git-tracked scope manifest**: how current source items map to Requirement / Acceptance Check IDs and invariants.
- **GitHub**: implementation, docs, commits, PRs, CI and reviewable artifacts.
- **Agent Continuity SQLite**: current execution state, source mappings, requirements/checks, invariants, stale evidence, gate history, checkpoints and events.
- **ChatGPT Library during this experiment**: durable backing copy of the SQLite state file between ephemeral sessions.
- **Chat history**: optional context only; never canonical continuation state.

## v0.3 source capture

Material inputs become stable IDs before broad implementation:

```text
SRC-*  user/spec/policy/scope-change item
FND-*  reviewer/discovered defect or risk
```

Every source/finding must be one of:

```text
mapped
explicitly deferred
waived
superseded
rejected
```

`unmapped` blocks the Scope Capture Gate. Silence is never an implicit defer.

## Scope Capture Gate

Before broad implementation:

- every material source/finding has explicit durable disposition;
- every mapped source points to one or more Requirement IDs;
- every required Requirement has required observable Acceptance Checks;
- every active invariant introduced by the phase is mapped to at least one required check;
- no required item exists only in chat/reviewer prose.

Example:

```bash
python scripts/continuity_v03.py manifest-sync \
  .agent-continuity/plans/phase-10.toml --commit <scope-commit>
python scripts/continuity_v03.py capture-gate phase-10
```

## Invariants and change impact

Features are not the only things that matter. v0.3 tracks cross-cutting properties such as:

```text
INV-DATA-001   durable DB state must not reference missing required assets
INV-READY-001  Ready cannot coexist with unresolved source review
INV-CONT-001   material source items cannot silently disappear from scope
```

Requirements/checks may declare impacted modules/domains/invariants. When a later commit changes an impacted module, the mapped check becomes stale until reverified.

```bash
python scripts/continuity_v03.py impact phase-10 \
  --module scripts/continuity_v03.py \
  --changed-ref <commit>
```

## Completion Gate

Completion still requires every required acceptance check and declared evidence kind to be current for the accepted commit/workspace. It additionally requires a passing Scope Capture Gate for the current manifest hash and no stale impacted checks.

```bash
python scripts/continuity_v03.py gate phase-10 --commit <verified-commit>
```

A passing completion gate means **scope-complete**.

## Fresh Reviewer Gate

Execute mode then performs a fresh review deliberately outside the checklist. It searches for:

- failure / rollback / recovery paths;
- cross-store and data invariants;
- state-machine / publication semantics;
- security / exposure / permission boundaries;
- resource limits;
- migration/upgrade compatibility;
- regression/change-impact surfaces;
- documentation/claim drift.

New material findings must be registered immediately:

```bash
python scripts/continuity_v03.py finding \
  FND-10-006 phase-10 P0 \
  "New review finding" \
  "Description" --commit <reviewed-commit>
```

The review gate fails while any material finding remains non-terminal:

```bash
python scripts/continuity_v03.py review-gate phase-10 --commit <reviewed-commit>
```

If review creates required work, update scope, rerun Scope Capture Gate, implement/reverify, rerun Completion Gate, then review again.

### Durable-store finalization guard

The repository keeps the older `scripts/continuity.py` for backward compatibility with historical v0.1/v0.2 state. v0.3 therefore does not rely only on callers choosing the new CLI. SQLite triggers activate for phases that contain v0.3 scope sources and reject `Phase` or `Task` transition to `completed` unless the current manifest has:

- a passing Scope Capture Gate;
- a passing Completion Gate; and
- a passing Fresh Reviewer Gate bound to the same accepted commit as the Completion Gate.

This makes the durable store the fail-closed boundary: invoking the legacy CLI directly cannot bypass v0.3 finalization policy.

## Execute mode

For multi-part project work:

```text
Inspect reality
→ capture sources/findings
→ Scope Capture Gate
→ implement
→ verify + impact/stale reconciliation
→ Completion Gate
→ Fresh Reviewer Gate
→ loop on findings until clear
→ merge/checkpoint
→ final reconcile/publish durable state
```

Execute mode reduces narration, not validation depth.

## Persistent Library mode

```text
fetch Library object version N
→ materialize state.db
→ integrity/schema check
→ reconcile Git + source registry + manifest
→ execute/checkpoint locally
→ close SQLite
→ upload only against observed Library version N
→ Library version N+1
```

A version mismatch is a conflict signal. Do not overwrite a newer state snapshot blindly.

## Acceptance property

Agent Continuity v0.3 is successful only when a new session can recover:

- where execution stopped;
- which original sources/findings remain unresolved;
- which mapped checks are incomplete or stale;
- which invariants need re-verification;
- whether completion and fresh-review gates are valid for the current commit.
