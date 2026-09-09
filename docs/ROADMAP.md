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

### Phase 4 — MVP hardening + handoff 🚧

Goal: make the implemented workflow honestly runnable as a small self-hosted MVP and align documentation with the real code.

In scope:

- Dockerized API
- Dockerized production web build + Nginx API proxy
- Compose persistence for SQLite and assets
- container build CI gate
- README / architecture / roadmap synchronization
- final Agent Continuity restore test after merge

Exit condition:

```text
docker compose up --build
```

provides the web workspace on `http://localhost:8787`, CI is green, and a fresh cloud session can restore the final development state from the durable SQLite snapshot without relying on previous chat context.

---

# Post-MVP engineering track

These improve the practical baseline before more speculative AI work.

## Reliable manga processing

- benchmark manga-specialized text detectors instead of relying on the OpenCV heuristic
- benchmark Tesseract vs MangaOCR vs other OCR choices on a fixed manga set
- preserve OCR confidence where providers expose it
- interactive region add/move/resize/delete in the web editor
- manual mask refinement
- cleanup routing: flat fill vs conventional inpaint vs neural inpaint
- background processing queue + progress UI for chapter jobs

## Layout and rendering

- polygon/balloon-aware safe area
- measured text layout rather than character-count approximation
- better line-break search and visual balance scoring
- font registry and per-locale typography presets
- optional pre-rendered page cache and invalidation

## Translation ↔ layout feedback

Current MVP detects `poor-fit` and calculates a rough target length. The next experiment is to close the loop:

```text
translation
   ↓
auto-fit
   ↓
poor-fit?
   ↓ yes
request a shorter equivalent
   ↓
re-fit + review
```

The shorter version must preserve meaning and locked terminology.

## Quality measurement

Track practical metrics rather than feature count:

- OCR correction rate
- missed/false text regions
- terminology violations
- translation corrections
- clean-page artifact rate
- % layouts accepted without manual adjustment
- manual correction time per page

---

# Post-MVP research track

## Visual-context translation

Hypothesis: a general VLM helps a subset of ambiguous dialogue.

Compare:

- text only
- nearby dialogue
- panel/page visual context

Only introduce visual escalation rules if human evaluation shows a meaningful improvement.

## Speaker metadata

Hypothesis: speaker identity helps omitted subjects, register, relationships, or pronouns.

Start with a manually labeled evaluation set. Automatic speaker detection is not justified until the translation benefit is demonstrated.

## Larger-context strategies

Compare:

- current region only
- nearby N regions
- selected prior dialogue
- chapter summary
- semantic retrieval only if long-range failures justify it

## Typography-role matching

Explore roles rather than exact font-name recognition:

```text
normal dialogue
shout
whisper
thought
narration
dramatic / horror
```

## SFX exploration

Treat SFX as a graphics/localization research problem rather than ordinary dialogue:

- detect SFX separately
- OCR stylized/rotated text
- semantic localization choices
- preserve-vs-replace modes
- transformed text placement
- outline/rotation/warp reproduction
- difficult background reconstruction

SFX automation becomes normal workflow only if it reduces graphics work without visibly damaging art.

## Experiment harness

Later, make comparisons repeatable by recording:

- model/provider
- prompt/version
- context strategy
- VLM on/off
- terminology strategy
- latency / API cost when available
- outputs
- human corrections
- preference / acceptance scores

Example comparisons:

```text
Model A vs Model B
2 nearby regions vs 6
text-only vs VLM
locked terms vs no locked terms
speaker metadata vs none
layout-aware shortening vs ordinary translation
```

---

# Architecture rule

Before introducing a new subsystem, answer at least one:

- Does it remove a measured failure mode?
- Does it materially simplify existing code?
- Does it enable a real experiment that current boundaries cannot support?
- Does it have a genuinely different deployment/lifecycle requirement?

If not, keep it inside the current modular application or leave it as an experiment.
