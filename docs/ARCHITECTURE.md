# KomaMori Architecture

## 1. Architectural goal

KomaMori is an **experimental modular monolith** for self-hosted manga localization and reading. Product/data orchestration, OCR/CV processing, localization, review, migrations, workbench behavior and Reader APIs stay inside one FastAPI application until a measured deployment or lifecycle boundary justifies separation.

Main application concerns:

1. Library / structured manga source
2. Content processing and derived assets
3. Localization / review / QA
4. Web workbench / Reader
5. Runtime persistence lifecycle

## 2. Self-host topology

```text
Browser
  │
  ▼
Nginx container
  ├── React/Vite static build
  └── /api/* proxy
          │
          ▼
       FastAPI
       modular monolith
          │
     ┌────┴────────────────┐
     ▼                     ▼
 SQLite                local assets
 + migration ledger    original / derived
     │                     │
     └─────────┬───────────┘
               ▼
       Python processing
       ├── OpenCV
       ├── Tesseract / optional MangaOCR
       └── OpenAI-compatible LLM provider
```

Docker Compose exposes the web app on port `8787`; `./data` and `./assets` are bind-mounted. Native development uses Vite on `5173` with `/api` proxied to FastAPI on `8000`.

## 3. Implemented technology choices

| Concern | Choice |
| --- | --- |
| Web | React 19 + Vite + TypeScript |
| Editor/Reader rendering | structured HTML/CSS overlays |
| API | FastAPI |
| ORM | SQLAlchemy |
| Database | SQLite |
| Schema lifecycle | versioned in-app migration ledger |
| Binary assets | local filesystem |
| Archive import | ZIP/CBZ parsing |
| Image inspection | Pillow |
| Detection baseline | OpenCV heuristic |
| OCR baseline | Tesseract Japanese |
| Optional OCR | MangaOCR |
| Cleanup | persisted masks + OpenCV Telea inpainting |
| Translation | OpenAI-compatible provider abstraction |
| QA | deterministic application checks |
| Browser verification | Playwright |
| Deployment | Docker Compose + Nginx |

PostgreSQL, object storage, neural inpainting, background queues and distributed workflow infrastructure are not current dependencies.

## 4. Core source model

A translated bitmap is never the source of truth.

```text
Series
└── Chapter
    └── Page
        ├── originalAsset       immutable
        ├── cleanAsset?         derived
        └── TextRegion[]
            ├── type
            ├── geometry
            ├── sourceText
            ├── ocrConfidence?
            ├── readingOrder
            ├── maskAsset?      derived
            ├── sourceStyle
            └── Localization[]
                ├── locale
                ├── text
                ├── status
                ├── source/provenance
                ├── qualityMetadata
                └── layout
```

`TextRegion` is deliberately broader than `Bubble`. Supported types include:

```text
unknown
dialogue
thought
narration
caption
sign
ui
sfx
```

Automatic detection creates `unknown` regions. Semantic classification is an explicit review step because the OpenCV detector does not reliably distinguish dialogue, narration, signs or SFX.

## 5. Safe processing boundary

Automatic operations are allowlist-based:

```text
Detect + OCR
↓
unknown region
↓
human classify/correct
↓
known safe type?
├─ yes → cleanup / automatic localization allowed
└─ no  → preserve, do not destructively process
```

`unknown` and `sfx` are excluded from automatic cleanup and localization. They also do not inflate locale-completion denominators.

This is intentionally fail-safe: uncertainty costs manual review rather than artwork destruction.

## 6. Original, mask and clean assets

Original pages are immutable.

For each cleanable region:

```text
original page + region geometry
          ↓
     text mask asset
          ↓
 masks for current page
          ↓
 OpenCV inpaint clean page
```

Masks live under derived storage and are inspectable through the API. Clean pages consume those persisted masks rather than ephemeral in-memory masks.

Derived-state invalidation rules are explicit:

- geometry/type change → delete stale region mask + page clean asset;
- new cleanable region → invalidate page clean asset;
- cleanable region deletion → remove mask + invalidate clean page;
- geometry change → recompute per-locale layout;
- source OCR text change → demote localizations to `needs-review`;
- approved translation text change → demote to `needs-review`; explicit re-approval refreshes approved reuse memory.

## 7. Region correction workbench

The web workbench is the correction layer for heuristic detection. It supports:

- create region by drawing a rectangle;
- delete false positives;
- type classification;
- reading-order editing;
- drag/move;
- resize;
- OCR/source editing;
- translation editing and approval.

Reader mode does not render `unknown` or `sfx` overlays, while Workbench keeps them visible for correction.

## 8. Localization store

KomaMori keeps useful CAT-style durable decisions without creating separate enterprise CAT services.

```text
LocalizationTerm
├── source
├── target
├── locale
├── aliases[]
├── locked
└── notes

ApprovedTranslation
├── seriesId
├── locale
├── sourceText
├── targetText
└── provenance
```

A locked term matches either its canonical source or configured aliases. The exact variant found in the source is passed to the translation provider with the canonical target, and deterministic QA enforces the target for canonical/alias matches alike.

Approved translations are exact source-text reuse, scoped to series + locale.

## 9. Translation execution

For each translatable region the baseline request receives:

```text
current source text
source language
target locale
nearby previous source dialogue
locked canonical/alias terms present in source
```

Before provider invocation, KomaMori checks exact approved-translation memory. Dynamic scene interpretation is not stored as a dedicated emotion/character-voice subsystem.

## 10. OCR confidence and QA

Tesseract keeps its existing OCR text output and separately reads word-level confidence data. Valid word confidences are normalized to `0..1` and averaged for the region. If no usable confidence exists, the provider returns `None` rather than inventing certainty.

MangaOCR currently returns no confidence through the provider contract.

Deterministic QA checks:

```text
missing translation?
locked canonical/alias term violated?
provider OCR confidence below threshold?
layout poor-fit?
```

Tesseract confidence is an engine signal, not a calibrated probability of correctness.

## 11. Layout and locale readiness

Layout is locale-specific. Current auto-fit is heuristic: bounding box, CJK/whitespace-aware wrapping and font-size search produce `fit` / `poor-fit` plus a rough recommended maximum length.

Locale readiness is derived rather than manually asserted:

```text
not all translated       → in-progress
all translated           → review
all translated+approved  → ready
```

Reader surfaces this state so a partial localization is not silently presented as finished.

## 12. Runtime database lifecycle

Application startup runs a versioned migration runner. A `schema_migrations` ledger records applied versions. The current baseline migration can adopt an existing MVP database by creating only missing schema objects; existing rows are preserved.

SQLite connections explicitly enable foreign-key enforcement so database cascades match the ORM model.

The migration runner is intentionally lightweight. If future schema evolution requires complex ALTER/data transforms, adopting Alembic should be reevaluated rather than building an increasingly complex custom migration framework.

Series/Chapter deletion also cleans corresponding original/clean/mask filesystem trees so database lifecycle and asset lifecycle stay aligned.

## 13. Execution and verification model

Processing endpoints are currently synchronous:

```text
HTTP request
↓
OCR / cleanup / translation
↓
response
```

A background queue remains deferred until chapter workloads make synchronous execution materially harmful.

Pull requests verify four independent layers:

```text
backend pytest
frontend TypeScript + Vite build
Docker Compose/container build
Playwright full-stack browser workflow
```

The browser test starts real FastAPI + Vite processes and exercises the public UI/API path rather than mocking the application boundary.

## 14. Agent Continuity is separate from runtime state

KomaMori runtime SQLite and Agent Continuity SQLite are separate databases.

```text
KomaMori runtime DB
→ manga/localization application data

.agent-continuity/state.db
→ development phase/task/scope/check/evidence/gate state
```

Git-tracked `.agent-continuity/plans/*.toml` manifests define approved development scope. Agent Continuity v0.2 stores check-level evidence and refuses phase completion without a passing gate for the current manifest revision.

See [`AGENT_CONTINUITY.md`](AGENT_CONTINUITY.md).

## 15. Architecture guardrails

Before adding a subsystem, ask:

- Does it remove a measured failure mode?
- Does it materially simplify existing code?
- Does it enable an experiment impossible with current boundaries?
- Does it have a genuinely different deployment/lifecycle requirement?

If none apply, keep the behavior inside the modular application or leave it as an experiment.
