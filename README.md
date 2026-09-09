# KomaMori

**A self-hosted web workspace for turning manga pages into structured, multilingual, editable reading experiences.**

KomaMori is a personal technical exploration project for manga localization and reading. Instead of treating a translated page as one flattened output image, KomaMori keeps the source page, text regions, OCR text, clean assets, localizations, and per-language layout as reusable structured data.

> **Status: experimental MVP.** The end-to-end workflow is implemented for normal dialogue/narration, but the OCR/detection/cleanup quality is still an exploration baseline rather than production scanlation quality.

## What works today

- image and CBZ/ZIP chapter import
- immutable original page assets
- automatic text-region detection and OCR
- editable OCR/source text
- derived clean pages using region-aware OpenCV inpainting
- per-series locked terminology
- OpenAI-compatible LLM translation provider with nearby dialogue context
- exact reuse of approved translations
- multiple target locales on one shared structured source
- per-locale auto-fit metadata and poor-fit detection
- deterministic QA for missing translations, locked terms, OCR confidence, and layout fit
- manual translation editing and approval in the web workbench
- multilingual reader with Original / Localized switching
- SQLite + local filesystem self-hosted persistence

SFX is intentionally excluded from automatic cleanup/localization in the MVP.

## Core workflow

```text
Import manga / CBZ
        ↓
Structured pages
        ↓
Detect text regions + OCR
        │
        ├───────────────┐
        ▼               ▼
Clean page          Localization
(OpenCV)      terms + context + LLM/manual
        │               │
        └───────┬───────┘
                ▼
          Per-locale layout
                ↓
              QA
                ↓
          Human review
                ↓
        Library / Reader
```

The original page remains immutable. Clean pages, translations, layouts, and future rendered pages are derived data and can be regenerated.

## Quick start — Docker Compose

Requirements: Docker with Compose support.

```bash
cp .env.example .env
# Optional: configure an LLM provider in .env

docker compose up --build
```

Open:

```text
http://localhost:8787
```

The Compose stack persists:

```text
./data     SQLite database
./assets   original + derived manga assets
```

The web container proxies `/api` to the FastAPI container, so the browser uses one local origin.

### Optional AI translation configuration

KomaMori can use an OpenAI-compatible Chat Completions endpoint:

```env
KOMAMORI_LLM_BASE_URL=https://your-provider.example/v1
KOMAMORI_LLM_API_KEY=...
KOMAMORI_LLM_MODEL=...
```

Without these variables, the rest of the workbench remains usable and translations can be entered manually. The **AI localize** action will report that no provider is configured.

The Docker MVP uses Tesseract Japanese OCR by default. Native development can optionally install the `mangaocr` extra and set `KOMAMORI_OCR_PROVIDER=mangaocr` for experiments.

## Local development

### API

```bash
python -m pip install -e ".[dev]"
make api
```

### Web

```bash
cd apps/web
npm install
npm run dev
```

The Vite development server proxies `/api` to `http://localhost:8000`.

### Tests

```bash
make test
```

Pull requests also run:

- backend pytest
- TypeScript + Vite production build
- Docker Compose configuration and container builds

## Current architecture

```text
Browser
  │
  ▼
React + Vite
Library / Workbench / Reader
  │
  ▼
FastAPI
  ├── SQLite structured data
  ├── local manga assets
  ├── OCR / OpenCV processing
  └── LLM provider abstraction
```

The application intentionally remains a modular monolith. OCR, cleanup, localization, QA, and workbench views are application modules, not separately deployed microservices.

Core source model:

```text
Series
└── Chapter
    └── Page
        ├── OriginalAsset
        ├── CleanAsset?       derived
        └── TextRegion[]
            ├── geometry
            ├── sourceText
            ├── OCR metadata
            └── Localization[]
                ├── locale
                ├── text
                ├── status
                └── layout
```

## Localization data philosophy

KomaMori keeps stable decisions in deterministic data instead of asking a model to rediscover them every time:

```text
locked terminology
approved translations
source/target locale
review status
layout metadata
```

Dynamic interpretation such as tone, emotion, or scene meaning is not modeled as dedicated Character Voice / Emotion services. General LLM/VLM context experiments can handle those later if benchmarks show a real benefit.

## Known MVP limitations

- text detection is currently an OpenCV heuristic, not a manga-specialized detector
- Tesseract is the default OCR baseline; real manga quality varies substantially
- clean-page generation uses basic OpenCV inpainting and may damage complex artwork
- region geometry can be edited through the API, but the MVP web UI does not yet provide a drag/resize mask editor
- auto-fit is heuristic and does not yet use polygon-aware balloon shaping
- poor-fit is detected, but automatic translation-shortening feedback is not yet closed-loop
- processing actions are synchronous; there is no background job/progress system yet
- there is no pre-rendered page cache; the reader uses structured overlays
- SFX reconstruction is intentionally deferred
- no multi-user collaboration or public manga catalog

These are post-MVP engineering/research targets, not hidden production claims.

## Agent Continuity experiment

KomaMori is also being used as a live test bed for **Agent Continuity**: disposable cloud development sessions backed by GitHub for code/review history and an external SQLite execution-state snapshot for phase/task/checkpoint/evidence recovery.

See [`docs/AGENT_CONTINUITY.md`](docs/AGENT_CONTINUITY.md).

The implementation itself does not depend on the previous chat history to describe the next development task; the continuity experiment is tracked separately from KomaMori's runtime database.

## Non-commercial exploration

KomaMori is designed for personal experimentation and small-group internal use. It is not intended to operate a public catalog of third-party copyrighted manga. Public demos should use original, public-domain, or otherwise authorized content.

## Documentation

- [`docs/CONCEPT.md`](docs/CONCEPT.md) — product concept and scope boundaries
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — implemented architecture and data model
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — completed MVP phases and post-MVP experiments
- [`docs/AGENT_CONTINUITY.md`](docs/AGENT_CONTINUITY.md) — continuity experiment protocol
