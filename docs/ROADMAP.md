# KomaMori Roadmap

KomaMori is developed **phase by phase through pull requests**. The rule is usable capability first, experiments second: an optional AI feature should not become permanent architecture until it solves a measured failure of the simpler baseline.

## MVP execution history

### Phase 0 — Foundation ✅

PR #1

Implemented:

- FastAPI + SQLAlchemy application foundation
- React/Vite web shell
- SQLite/local asset direction
- `Series → Chapter → Page → TextRegion → Localization` source model
- immutable-original / derived-asset boundary
- Agent Continuity SQLite schema and bootstrap protocol

Gate evidence:

- API health test
- continuity state initialization/bootstrap
- first durable SQLite snapshot stored outside the ephemeral workspace

---

### Phase 1 — Structured manga core ✅

PR #2

Implemented:

- Series / Chapter creation and browsing
- image import
- CBZ/ZIP import
- natural page ordering
- image validation and original asset persistence
- manual TextRegion API
- initial Library web UI

Gate evidence:

- backend import/asset/region tests
- 3 pytest tests passing at the phase gate

---

### Phase 2 — Localization processing core ✅

PR #3

Implemented:

- OpenCV text-region detection baseline
- pluggable OCR provider
  - Tesseract default
  - MangaOCR optional runtime
- derived clean-page generation with OpenCV inpainting
- locked terminology
- OpenAI-compatible translation provider abstraction
- nearby-dialogue context
- exact approved-translation reuse
- per-locale Localization data
- heuristic auto-fit
- deterministic QA
- approval/reuse workflow

Gate evidence:

- synthetic processing tests with fake OCR
- translation tests with fake provider
- 7 pytest tests passing at the phase gate

Explicitly deferred:

- SFX reconstruction
- character-voice subsystem
- emotion subsystem
- semantic RAG

---

### Phase 3 — Web localization workbench + multilingual reader ✅

PR #4

Implemented:

- chapter-level Detect/OCR and Clean actions
- multilingual workbench view API
- locale completion indicators
- shared structured `MangaStage` overlay rendering
- OCR/source text editing
- target translation editing
- terminology editing
- deterministic QA issue navigation
- approval from the editor
- multilingual reader
- Original / Localized reader toggle
- Library → Workbench → Reader workflow
- GitHub Actions for backend tests and real frontend production build

Gate evidence:

- 9 local pytest tests passing
- local TS/TSX syntax transpile check
- GitHub Actions frontend `npm install + npm run build` success
- GitHub Actions backend pytest success

The same processed source was explicitly tested with both `en` and `zh-TW` localizations sharing one TextRegion identity.

---

### Phase 4 — MVP hardening + handoff ✅

Implemented:

- Dockerized API
- Dockerized production web build + Nginx API proxy
- Compose persistence for SQLite and assets
- container build CI gate
- README / architecture / roadmap synchronization
- destructive Agent Continuity restore test from Library

Gate evidence:

- backend pytest success
- frontend production build success
- Docker Compose configuration and API/Web image build success
- restored continuity state matched the final GitHub main checkpoint

---

### Phase 5 — Agent Continuity v0.2 completion traceability ✅

PR #6

Implemented:

- Git-tracked phase scope manifests with stable Requirement / Acceptance Check IDs
- durable manifest hash/revision state
- check-level evidence records bound to commit/workspace identity
- declared evidence-kind enforcement (`test`, `review`, etc.)
- fail-closed completion gates that enumerate missing IDs
- scope-change invalidation
- completion rejection without a current passing gate
- completeness-aware bootstrap with first unfinished check
- backward-compatible v0.1 SQLite upgrade
- task PR linkage

This phase upgrades continuity from “resume where execution stopped” to “resume without silently dropping promised work.”

---

### Phase 6 — Data integrity + safe processing 🚧

Approved scope: `.agent-continuity/plans/phase-6.toml`

In scope:

- automatic detections remain `unknown` until explicitly classified
- destructive cleanup uses a cleanable-type allowlist
- `unknown` and `sfx` are excluded from automatic cleanup/localization/locale completion counts
- persistent per-region text-mask assets
- clean pages are generated from persisted masks
- geometry/type edits invalidate stale mask and clean-page assets
- geometry edits recompute per-locale layout
- source OCR edits demote localizations to `needs-review`
- editing approved translation text demotes it to `needs-review`
- explicit re-approval refreshes approved-translation reuse memory

Exit condition:

- every `P6-*` acceptance check has commit-bound required evidence
- PR CI is green
- v0.2 completion gate passes for the exact PR head and post-merge tree-equivalent commit

---

# Next engineering track

After Phase 6, prioritize correction UX and persistence lifecycle before speculative multimodal work:

- interactive region create/delete/type/move/resize
- manual mask refinement
- chapter/locale readiness lifecycle
- SQLite schema migrations
- one full browser E2E workflow
- OCR confidence only when a provider genuinely exposes it
- translation ↔ layout shortening feedback

# Research track

Later experiments remain hypothesis-driven:

- manga-specialized detector benchmarking
- OCR provider benchmarking
- VLM visual-context escalation
- speaker metadata
- larger context strategies
- typography-role matching
- SFX reconstruction
- repeatable experiment harness

# Architecture rule

Before introducing a new subsystem, answer at least one:

- Does it remove a measured failure mode?
- Does it materially simplify existing code?
- Does it enable a real experiment that current boundaries cannot support?
- Does it have a genuinely different deployment/lifecycle requirement?

If not, keep it inside the current modular application or leave it as an experiment.
