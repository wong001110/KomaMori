# KomaMori Architecture

## 1. Current architectural goal

KomaMori is an **experimental modular monolith** for self-hosted manga localization and reading. The MVP intentionally keeps product/data orchestration, OCR/CV processing, translation behavior, review, and reader APIs inside one Python application rather than splitting them into services prematurely.

The implemented runtime has four application concerns:

1. Library / structured manga source
2. Content processing
3. Localization / review
4. Web workbench / reader

## 2. Implemented self-host topology

```text
Browser
  │
  ▼
Nginx container
  ├── static React/Vite production build
  └── /api/* proxy
          │
          ▼
       FastAPI
          │
     ┌────┴───────────────┐
     ▼                    ▼
 SQLite              local assets
 structured data     original / derived
     │                    │
     └────────┬───────────┘
              ▼
      Python processing
      ├── OpenCV
      ├── Tesseract / optional MangaOCR
      └── OpenAI-compatible LLM provider
```

Docker Compose exposes the web app on port `8787`; the API is internal to the Compose network and is reached through Nginx `/api` proxying. `./data` and `./assets` are bind-mounted for persistence.

For native development, Vite runs separately and proxies `/api` to FastAPI on port `8000`.

## 3. Technology choices at MVP

| Concern | Implemented choice |
| --- | --- |
| Web UI | React 19 + Vite + TypeScript |
| Visual editor/reader | structured HTML/CSS overlays |
| API | FastAPI |
| ORM | SQLAlchemy |
| Initial database | SQLite |
| Assets | local filesystem |
| Archive import | Python ZIP/CBZ parsing |
| Image inspection | Pillow |
| Detection baseline | OpenCV heuristic |
| OCR baseline | Tesseract Japanese |
| Optional OCR | MangaOCR provider |
| Cleanup baseline | OpenCV Telea inpainting |
| Translation | OpenAI-compatible provider abstraction |
| QA | deterministic application checks |
| Deployment | Docker Compose + Nginx |

Canvas/Konva, PostgreSQL, object storage, neural inpainting, background queues, and durable workflow orchestration are **not** MVP dependencies.

## 4. Core source model

The most important architectural decision is that a translated manga page is not the source of truth.

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
            ├── OCR confidence?
            ├── readingOrder
            ├── sourceStyle
            └── Localization[]
                ├── locale
                ├── text
                ├── status
                ├── source/provenance
                ├── qualityMetadata
                └── layout
```

`TextRegion`, not `Bubble`, is the root text abstraction because manga also contains narration, captions, signs, thoughts, and SFX.

Supported region types currently include:

```text
dialogue
thought
narration
caption
sign
sfx
unknown
```

SFX is represented but skipped by the automatic localization/cleanup MVP path.

## 5. Original and derived assets

Original imported pages are immutable unless a future explicit replace operation is introduced.

Derived data includes:

- OCR text
- TextRegion geometry
- clean pages
- translations
- layout metadata
- future render caches

The current reader displays either:

```text
original page
```

or:

```text
clean page (when available)
+ locale-specific structured text overlays
```

There is no pre-rendered localized page cache yet.

## 6. Application modules

### Library

Owns:

- Series / Chapter / Page records
- image and CBZ/ZIP import
- immutable original assets
- manual TextRegion CRUD API

### Processing

Owns:

- chapter/page text-region analysis
- OCR provider selection
- reading-order baseline
- clean-page generation

The MVP detector is a conventional OpenCV baseline. The architecture allows replacing detection/OCR without changing the structured source model.

### Localization

Owns:

- per-locale translations
- locked terminology
- nearby-dialogue context
- LLM provider calls
- exact approved-translation reuse
- heuristic auto-fit
- deterministic QA
- approval state

### Workbench

Owns read-oriented views for the web application:

- one chapter represented for a selected locale
- locale progress summaries
- shared page/region identity across locales

The web UI uses the same workbench representation for editing and reading rather than maintaining independent translated-page state.

## 7. Localization store

The MVP deliberately does not implement separate enterprise CAT services.

Durable localization concepts are:

```text
LocalizationTerm
├── source
├── target
├── locale
├── type
├── aliases
├── locked
└── notes

ApprovedTranslation
├── seriesId
├── locale
├── sourceText
├── targetText
└── provenance
```

This captures the useful parts of a glossary/termbase and exact approved translation reuse without creating unnecessary subsystem boundaries.

Stable translation decisions are persisted; dynamic interpretation is not.

For example:

```text
Black Knight as a locked title  → persist
approved translation of a line → persist
current character emotion       → infer when useful
sarcastic tone in one panel     → infer when useful
```

## 8. Processing graph

Conceptually the source pipeline is a DAG:

```text
Import
  ↓
Page structure
  ↓
Text detection + OCR
  │
  ├───────────────┐
  ▼               ▼
Clean page     Localization
  │               │
  └───────┬───────┘
          ▼
    locale layout
          ↓
     deterministic QA
          ↓
       human review
          ↓
        reader
```

Once TextRegions exist, clean-page generation and target-language localization are independent branches.

## 9. Translation execution

For each normal text region, the baseline LLM request receives:

```text
current source text
source language
selected target locale
nearby previous source dialogue
locked terms present in the source
```

Before calling the provider, KomaMori checks for an exact approved translation in the current series/locale and reuses it when possible.

The provider interface is intentionally OpenAI-compatible rather than bound to one model vendor.

No dedicated emotion or character-voice service exists. If visual/tone context is investigated later, it should first be tested as a general LLM/VLM input against the simpler baseline.

## 10. QA and auto-fit

The MVP prefers deterministic QA whenever possible:

```text
missing translation?
locked term violated?
known OCR confidence too low?
layout marked poor-fit?
```

Current auto-fit is heuristic:

```text
region bounding box
↓
CJK / whitespace-aware wrapping
↓
font-size search
↓
fit / poor-fit
↓
rough recommended max length
```

It does not yet perform real font measurement or polygon-aware balloon fitting. A future translation/layout loop may use the `poor-fit` result to request a shorter equivalent translation and re-run layout.

## 11. Processing execution model

MVP processing endpoints are synchronous. This is deliberate scope control, not the desired end state for large chapters.

Current:

```text
HTTP request
↓
OCR / clean / translate work
↓
response
```

Introduce a background queue only when real chapter workloads make synchronous execution materially harmful. A later worker design should add:

- persisted job state
- per-page/chapter progress
- retry boundaries
- SSE/polling UI

Temporal/distributed workflow infrastructure remains unjustified until the application develops long-lived, multi-worker, pause/resume workflow requirements.

## 12. Self-host persistence

The Compose MVP maps:

```text
./data   → /app/data
./assets → /app/assets
```

SQLite stores structured records; binary manga data stays on the filesystem.

A future multi-user/server version may replace these with PostgreSQL and object storage without changing the core Page/TextRegion/Localization abstraction.

## 13. Agent Continuity is separate from runtime state

KomaMori's runtime SQLite database is **not** the Agent Continuity database.

The development experiment uses a separate gitignored SQLite state store:

```text
.agent-continuity/state.db
```

with an external durable snapshot between ephemeral cloud sessions. GitHub remains the source of truth for code/PR/commit history; continuity SQLite stores current phase/task/checkpoint/evidence metadata.

See [`AGENT_CONTINUITY.md`](AGENT_CONTINUITY.md).

## 14. Architecture guardrails

Before adding a subsystem, ask:

- Does it remove a measured failure mode?
- Does it materially simplify existing code?
- Does it enable an experiment impossible with current boundaries?
- Does it have a genuinely different deployment/lifecycle requirement?

If none apply, keep the behavior in the modular application or leave it as an experiment.
