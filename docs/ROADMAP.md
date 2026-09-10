# KomaMori Roadmap

KomaMori is developed **phase by phase through pull requests**. The rule is usable capability first, experiments second: optional AI features do not become permanent architecture until they solve a measured failure of the simpler baseline.

## Execution history

### Phase 0 — Foundation ✅
PR #1

- FastAPI + SQLAlchemy foundation
- React/Vite web shell
- SQLite/local asset direction
- `Series → Chapter → Page → TextRegion → Localization` model
- immutable-original / derived-asset boundary
- Agent Continuity v0.1 bootstrap/state store

### Phase 1 — Structured manga core ✅
PR #2

- Series / Chapter creation and browsing
- image + CBZ/ZIP import
- natural page ordering and validation
- immutable original asset persistence
- initial TextRegion API and Library UI

### Phase 2 — Localization processing core ✅
PR #3

- OpenCV text detection baseline
- Tesseract default OCR + optional MangaOCR
- cleanup/inpainting baseline
- locked terminology
- OpenAI-compatible translation provider
- approved-translation reuse
- per-locale localization, auto-fit and deterministic QA

### Phase 3 — Web workbench + multilingual reader ✅
PR #4

- chapter Detect/OCR + Clean actions
- multilingual workbench and Reader
- OCR/source + target editing
- terms, QA navigation and approval
- shared structured overlays
- backend + frontend CI

### Phase 4 — MVP hardening + self-host handoff ✅
PR #5

- Dockerized API and production web/Nginx
- Compose persistence
- container-build CI
- README/architecture alignment
- destructive Agent Continuity restore verification

### Phase 5 — Agent Continuity v0.2 completion traceability ✅
PR #6

- Git-tracked scope manifests with stable Requirement / Acceptance Check IDs
- durable manifest revision/hash state
- check-level evidence bound to commit/workspace
- evidence-kind enforcement
- fail-closed gates with missing-ID reporting
- scope-change invalidation
- completeness-aware bootstrap
- backward-compatible v0.1 state upgrade

This phase changed continuity from “resume where execution stopped” to “resume without silently dropping promised work already captured in scope.”

### Phase 6 — Data integrity + safe processing ✅
PR #7

- detections default to `unknown` instead of assuming dialogue
- cleanup/localization use explicit safe-type allowlists
- `unknown` / `sfx` excluded from destructive automatic processing
- persistent per-region mask assets
- clean pages generated from persisted masks
- geometry/type/create/delete invalidation for derived clean/mask state
- geometry edits recompute layout
- source edits invalidate review approval
- edited approved translations require re-approval before reuse memory updates

### Phase 7 — Interactive region correction ✅
PR #8

- false-positive region deletion
- region type + reading-order editing
- drag/move + resize geometry correction
- draw-to-add region flow
- Reader hides `unknown` / `sfx` overlays while Workbench keeps them available for correction

### Phase 8 — Application data lifecycle ✅
PR #9

- versioned SQLite migration ledger/runner
- adoption of existing databases without destructive reset
- SQLite foreign-key enforcement
- complete Series / Chapter create-read-update-delete lifecycle
- filesystem asset cleanup on chapter/series deletion
- Library edit/delete controls
- per-locale `in-progress` / `review` / `ready` readiness
- readiness surfaced in Reader

### Phase 9 — Verification + localization correctness ✅
PR #10

- actionable default Tesseract confidence from word-level OCR confidence
- locked terminology aliases in translation and deterministic QA
- Workbench alias configuration/review
- real full-stack Playwright browser workflow
- README / architecture / roadmap alignment
- Agent Continuity v0.2 completeness audit
- backend pytest, frontend production build, container build and Playwright E2E verified on the accepted tree

### Phase 10 — Agent Continuity v0.3 + Execute reviewer loop ✅
PR #11

- durable `ScopeSource` and `ReviewFinding` capture before requirement compression
- cross-cutting invariant registry
- Scope Capture Gate before broad implementation
- impacted-module evidence staleness
- mandatory Fresh Reviewer Gate after completion evidence
- new reviewer findings invalidate earlier gate authority and require recapture/reverification
- SQLite-level finalization guards prevent the legacy v0.2 CLI from bypassing v0.3 gates
- `scope-complete` is explicitly distinct from `defect-free`
- fixed the RegionEditor operation-feedback race surfaced by the fresh-review/E2E loop

### Phase 11 — Integrity & release semantics ✅
PR #12

- commit-safe DB/filesystem mutation ordering: prefer recoverable orphan files over dangling durable references
- fail-safe re-analysis and unique generated mask/clean assets
- source-review + deterministic-QA publication gate for locale `Ready`
- nonempty approval and reuse-memory safety
- page replace/delete/reorder recovery lifecycle and Library controls
- terminology-policy invalidation of approvals/reuse memory
- upload page/byte/uncompressed/pixel preflight limits
- file-backed SQLite foreign keys + WAL + bounded busy timeout
- localhost-only default Compose exposure
- backend invariant regression tests + negative browser release tests

Phase 11 passed Scope Capture, Completion and Fresh Reviewer gates on the accepted PR tree, was squash-merged, and was reconciled against the tree-equivalent merge commit.

### Phase 12 — Backlog hardening & reproducibility 🚧
PR #15

Current required scope:

- registry-resolved committed frontend lockfile; frontend/E2E/container builds use `npm ci`
- secret-free OCR and translation provenance for repeatable model-path inspection
- explicit manual / approved-memory localization provenance
- additive chapter identity v2: human-facing `display_number` separated from numeric `sort_order`, with legacy `number` compatibility
- dry-run-first orphan asset audit/GC with reference safety and an age grace period
- regression tests and browser coverage for the migrated chapter workflow

GitHub branch protection is deliberately **user-owned repository administration**. It remains visible as a handoff but is not an Agent Continuity blocker for executable project work.

Phase 12 is complete only after its current manifest passes Scope Capture, Completion and Fresh Reviewer gates on the accepted commit, then passes post-merge reconciliation.

## Explicitly unfinished engineering

These are tracked future work, not missing hidden scope:

- pixel-level manual mask painting/refinement
- manga-specialized detector benchmarking and possible replacement of the OpenCV heuristic
- OCR provider benchmarking/calibration beyond Tesseract’s engine confidence
- background processing queue + progress UI for long chapter jobs
- measured/polygon-aware typography and layout
- translation ↔ layout automatic shortening loop
- optional pre-rendered localized-page cache + invalidation

## User-owned repository administration

- configure GitHub `main` branch protection / rulesets and required CI checks according to the owner’s repository policy

This item is not an application/runtime blocker and does not stop Execute mode from completing agent-owned backlog.

## Research track

These remain hypothesis-driven experiments:

- VLM visual-context escalation
- speaker metadata
- larger-context strategies
- typography-role matching
- SFX reconstruction/style transfer
- repeatable model/prompt/context experiment harness

## Deliberate non-goals / deferred behavior

- automatic semantic region-type classification is **not** trusted yet; detections intentionally begin as `unknown` and require correction/classification before destructive processing
- SFX reconstruction remains deferred
- no character-voice or emotion microservices
- no multi-user/public manga catalog in the current self-hosted MVP

## Architecture rule

Before introducing a new subsystem, answer at least one:

- Does it remove a measured failure mode?
- Does it materially simplify existing code?
- Does it enable a real experiment that current boundaries cannot support?
- Does it have a genuinely different deployment/lifecycle requirement?

If not, keep the behavior inside the current modular application or leave it as an experiment.
