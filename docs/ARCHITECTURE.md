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
Browser on host
  │
  ▼
127.0.0.1:8787
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

Docker Compose binds the web app to host loopback on `127.0.0.1:8787` by default; `./data` and `./assets` are bind-mounted. KomaMori has no built-in multi-user authentication, so wider network exposure is an explicit operator concern rather than a default topology. Native development uses Vite on `5173` with `/api` proxied to FastAPI on `8000`.

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
| Archive import | bounded ZIP/CBZ parsing |
| Image inspection | Pillow with pixel bounds |
| Detection baseline | OpenCV heuristic |
| OCR baseline | Tesseract Japanese |
| Optional OCR | MangaOCR |
| Cleanup | persisted masks + OpenCV Telea inpainting |
| Translation | OpenAI-compatible provider abstraction |
| QA | deterministic application checks + publication readiness gate |
| Browser verification | Playwright positive + negative release workflows |
| Deployment | Docker Compose + Nginx, localhost-only default bind |

PostgreSQL, object storage, neural inpainting, background queues and distributed workflow infrastructure are not current dependencies.

## 4. Core source model

A translated bitmap is never the source of truth.

```text
Series
└── Chapter
    └── Page
        ├── originalAsset       immutable file version
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

Original asset **files** are immutable once written. Page recovery does not edit an original file in place: replacement writes a new unique original asset path, atomically moves durable page state to that path, invalidates obsolete page-bound regions/localizations/masks/clean state, then removes old files after commit.

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

`unknown` and `sfx` are excluded from automatic cleanup and localization. They do not inflate the translation denominator. However, `unknown` means source review is unresolved and therefore blocks locale `Ready`; explicitly classified `sfx` does not.

This is intentionally fail-safe: uncertainty costs manual review rather than artwork destruction.

## 6. Original, mask and clean asset lifecycle

For each cleanable region:

```text
original page + region geometry
          ↓
unique text-mask asset
          ↓
 masks for current page
          ↓
unique OpenCV inpaint clean asset
```

Masks live under derived storage and are inspectable through the API. Clean pages consume persisted masks rather than ephemeral in-memory masks.

Derived-state invalidation rules are explicit:

- geometry/type change → clear region mask reference + page clean reference; remove old files after DB commit;
- new cleanable region → invalidate page clean reference; remove old clean after commit;
- cleanable region deletion → delete region/DB state, then remove obsolete mask/clean files;
- geometry change → recompute per-locale layout;
- source OCR text change → demote localizations to `needs-review` and invalidate affected reuse memory;
- approved translation text change → demote to `needs-review`; explicit re-approval may refresh reuse memory;
- terminology-policy change → conservatively demote series/locale localizations and clear affected approved reuse memory;
- page replacement → write new original, invalidate old page-bound structured/derived state, commit, then remove obsolete files;
- page deletion → delete DB state and normalize remaining indexes before post-commit file cleanup;
- page reorder → preserve page identities/content while safely normalizing `page_index` values.

### Cross-store commit rule

SQLite and the filesystem cannot share one native transaction. KomaMori therefore uses this failure preference:

```text
prepare/write new unique assets
        ↓
commit durable DB references/state
        ↓
best-effort remove obsolete old assets
```

A failed new writer removes its partial new file. A DB commit failure removes newly prepared files and leaves previously referenced files intact. A crash during post-commit cleanup can leave an **orphan file**, which is safer and recoverable compared with a DB row pointing at an asset deleted before commit. Orphan audit/GC is explicitly deferred.

## 7. Region correction and page recovery

The web workbench is the correction layer for heuristic detection. It supports:

- create region by drawing a rectangle;
- delete false positives;
- type classification;
- reading-order editing;
- drag/move;
- resize;
- OCR/source editing;
- translation editing and approval.

The Library additionally supports imported page recovery:

- replace one page with a new original;
- delete one page;
- move/reorder pages with exact page-set validation and collision-safe index normalization.

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

A locked term matches either its canonical source or configured aliases. The exact variant found in source text is passed to the translation provider with the canonical target, and deterministic QA enforces the target for canonical/alias matches alike.

Approved translations are exact source-text reuse, scoped to series + locale. `approved` is a human workflow state; **reusable** is stricter. Reuse memory is populated only for a translatable region with nonempty source and no blocking deterministic QA error. Unknown/SFX or blocking-QA-invalid approvals therefore cannot pollute approved-memory reuse.

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

## 10. OCR confidence and deterministic QA

Tesseract keeps OCR text output and separately reads word-level confidence data. Valid word confidences are normalized to `0..1` and averaged for the region. If no usable confidence exists, the provider returns `None` rather than inventing certainty.

MangaOCR currently returns no confidence through the provider contract.

Shared deterministic QA checks include:

```text
translatable region missing source?     error
missing translation?                    error
locked canonical/alias term violated?   error
provider OCR confidence below threshold? warning
layout poor-fit?                         warning
```

Tesseract confidence is an engine signal, not a calibrated probability of correctness.

## 11. Publication-aware locale readiness

Layout is locale-specific. Current auto-fit is heuristic: bounding box, CJK/whitespace-aware wrapping and font-size search produce `fit` / `poor-fit` plus a rough recommended maximum length.

Locale readiness is derived rather than manually asserted. Translation denominator contains explicit translatable region types; unresolved `unknown` regions are tracked separately as a source-review blocker.

```text
any unresolved unknown
or incomplete translation
        → in-progress

all translated + source classified
but not all approved
or blocking deterministic QA error exists
        → review

all translatable regions translated
+ all have nonempty approved text
+ zero unresolved unknown
+ zero blocking deterministic QA error
        → ready
```

Warnings such as low OCR confidence or poor fit remain visible to QA but do not by themselves block `Ready` unless promoted to an error policy later. Reader surfaces readiness so partial or blocked localization is not silently presented as finished.

## 12. Runtime database lifecycle

Application startup runs a versioned migration runner. A `schema_migrations` ledger records applied versions. The current baseline migration can adopt an existing MVP database by creating only missing schema objects; existing rows are preserved.

File-backed SQLite connections explicitly enable:

```text
PRAGMA foreign_keys=ON
PRAGMA journal_mode=WAL
PRAGMA busy_timeout=5000
```

SQLAlchemy also uses a bounded SQLite connection timeout. The migration runner remains intentionally lightweight; if future schema evolution requires complex ALTER/data transforms, adopting Alembic should be reevaluated rather than growing an ad-hoc migration framework indefinitely.

## 13. Untrusted import boundary

Direct images and CBZ/ZIP uploads are bounded before expensive allocation where possible:

- page-count limit;
- per-page byte limit;
- aggregate direct/uncompressed byte limit;
- archive compressed byte limit;
- ZipInfo uncompressed-size preflight before reading an entry;
- image pixel-count limit before decode-heavy processing.

These are self-host safety bounds rather than a claim that KomaMori is a hardened hostile multi-tenant upload service.

## 14. Execution and verification model

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
Playwright full-stack browser workflows
```

Browser tests start real FastAPI + Vite processes and exercise public UI/API paths. They include both the positive manual-localization path and negative publication invariants such as unresolved unknown and locked-term QA blockers.

## 15. Agent Continuity is separate from runtime state

KomaMori runtime SQLite and Agent Continuity SQLite are separate databases.

```text
KomaMori runtime DB
→ manga/localization application data

.agent-continuity/state.db
→ development source/finding/phase/task/requirement/check/invariant/evidence/gate state
```

Git-tracked `.agent-continuity/plans/*.toml` manifests define captured development scope. Agent Continuity v0.3 adds durable source/finding capture, Scope Capture Gate, cross-cutting invariants, impact-driven stale evidence, Completion Gate and mandatory Fresh Reviewer Gate. A fresh reviewer finding invalidates prior capture/completion authority until the finding is mapped/disposed, scope is recaptured and current evidence is reverified.

See [`AGENT_CONTINUITY.md`](AGENT_CONTINUITY.md).

## 16. Architecture guardrails

Before adding a subsystem, ask:

- Does it remove a measured failure mode?
- Does it materially simplify existing code?
- Does it enable an experiment impossible with current boundaries?
- Does it have a genuinely different deployment/lifecycle requirement?

If none apply, keep the behavior inside the modular application or leave it as an experiment.
