# KomaMori

**A self-hosted web workspace for turning manga pages into structured, multilingual, editable reading experiences.**

KomaMori is a personal technical exploration project for manga localization and reading. Instead of treating a translated page as one flattened output image, it keeps the source page, text regions, OCR text, masks, clean assets, localizations, review state, and per-language layout as reusable structured data.

> **Status: hardened experimental MVP.** The complete manual-review workflow is implemented for dialogue/narration-style regions. Detection, OCR, cleanup and typesetting remain exploration baselines rather than production scanlation quality.

## What works today

- image and CBZ/ZIP chapter import
- Series / Chapter create, edit and delete lifecycle
- immutable original page assets with derived-asset cleanup on deletion
- automatic OpenCV text-region detection + Tesseract OCR
- Tesseract word-confidence aggregation exposed to deterministic QA when available
- safe automatic detections: new detected regions begin as `unknown`, not assumed dialogue
- interactive region correction in the web workbench:
  - add
  - delete false positives
  - classify type
  - edit reading order
  - drag/move
  - resize
  - edit OCR/source text
- persistent per-region text-mask assets
- derived clean pages generated from persisted masks with OpenCV inpainting
- destructive cleanup and automatic localization restricted to explicit safe region types
- per-series locked terminology with aliases
- OpenAI-compatible LLM translation provider with nearby-dialogue context
- exact reuse of approved translations
- multiple target locales on one shared structured source
- per-locale auto-fit metadata and poor-fit detection
- deterministic QA for missing translations, terminology, provider OCR confidence and layout fit
- manual translation editing, review and approval
- per-locale readiness: `in-progress` / `review` / `ready`
- multilingual Reader with Original / Localized switching and readiness disclosure
- SQLite + local filesystem self-hosted persistence
- versioned runtime database migration ledger
- backend, frontend build, container build and browser E2E CI gates

`unknown` and `sfx` regions are intentionally excluded from automatic cleanup/localization until explicitly handled. SFX reconstruction itself remains deferred.

## Core workflow

```text
Import manga / CBZ
        ↓
Structured pages
        ↓
Detect + OCR
        ↓
unknown TextRegions
        ↓
Human classify / correct geometry
        │
        ├────────────────┐
        ▼                ▼
Persistent masks      Localization
+ clean page      terms/aliases + context
        │            + LLM/manual
        └────────┬───────┘
                 ▼
           per-locale layout
                 ↓
          deterministic QA
                 ↓
             approval
                 ↓
       Ready / review / partial
                 ↓
               Reader
```

The original page remains immutable. Masks, clean pages, translations and layout are derived/reviewable state. Geometry/type changes invalidate affected clean/mask state, and source-text changes invalidate translation approval.

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

Persistence:

```text
./data     SQLite database
./assets   original + derived manga assets
```

The web container proxies `/api` to FastAPI through Nginx, so the browser uses one local origin.

### Optional AI translation

KomaMori supports an OpenAI-compatible Chat Completions endpoint:

```env
KOMAMORI_LLM_BASE_URL=https://your-provider.example/v1
KOMAMORI_LLM_API_KEY=...
KOMAMORI_LLM_MODEL=...
```

Without these variables, import, region editing, cleanup, manual localization, QA, approval and Reader workflows remain usable. Only **AI localize** requires a provider.

Docker uses Tesseract Japanese OCR by default. Native development can optionally install the `mangaocr` extra and set `KOMAMORI_OCR_PROVIDER=mangaocr`. MangaOCR currently does not expose a confidence value through the KomaMori provider contract; confidence QA only runs when the selected provider returns confidence.

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

Vite proxies `/api` to `http://localhost:8000`.

### Tests

```bash
make test
```

Browser workflow:

```bash
cd apps/web
npx playwright install chromium
npm run test:e2e
```

Pull requests run:

- backend pytest
- TypeScript + Vite production build
- Docker Compose configuration + API/Web image builds
- Playwright full-stack browser workflow

## Current architecture

```text
Browser
  │
  ▼
React + Vite
Library / Workbench / Reader
  │
  ▼
FastAPI modular monolith
  ├── SQLite structured data + migration ledger
  ├── local original/derived assets
  ├── OpenCV processing + persistent masks
  ├── Tesseract / optional MangaOCR
  ├── deterministic QA
  └── OpenAI-compatible translation provider
```

Core model:

```text
Series
└── Chapter
    └── Page
        ├── OriginalAsset          immutable
        ├── CleanAsset?            derived
        └── TextRegion[]
            ├── type
            ├── geometry
            ├── sourceText
            ├── OCR confidence?
            ├── readingOrder
            ├── MaskAsset?         derived
            └── Localization[]
                ├── locale
                ├── text
                ├── status
                └── layout
```

The project intentionally remains a modular monolith. OCR, cleanup, localization, QA, migrations, workbench views and Reader behavior are application modules, not separately deployed microservices.

## Localization data philosophy

Stable decisions live in deterministic data instead of asking a model to rediscover them:

```text
locked terms + aliases
approved translations
source/target locale
review status
layout metadata
```

Dynamic interpretation such as emotion, sarcasm or scene meaning is not modeled as a dedicated service. General LLM/VLM context experiments can be added later only if measured evaluation justifies them.

## Known limitations

- OpenCV text detection is heuristic and can miss/merge/over-detect manga text; manual correction is therefore part of the workflow
- detected region semantic type is not automatically classified; detections intentionally start as `unknown`
- Tesseract quality varies on stylized manga text; its confidence is an OCR-engine signal, not a calibrated correctness probability
- MangaOCR currently returns no confidence through the provider contract
- OpenCV inpainting can damage complex artwork
- masks are persisted and inspectable, but the web UI does not yet provide pixel-level manual mask painting/refinement
- auto-fit is heuristic and does not yet perform real font measurement or polygon-aware balloon shaping
- poor-fit is detected, but automatic translation-shortening feedback is not closed-loop
- processing actions are synchronous; there is no background job/progress system yet
- Reader uses structured overlays; there is no pre-rendered localized page cache/invalidation layer
- SFX reconstruction/style matching is deferred
- no multi-user collaboration or public manga catalog

These are explicit engineering/research targets, not hidden production claims.

## Agent Continuity experiment

KomaMori is also the live test bed for **Agent Continuity**: disposable development sessions backed by GitHub for code/reviewable scope and an external SQLite execution-state snapshot.

The current v0.2 protocol tracks stable Requirement / Acceptance Check IDs, commit-bound evidence, scope hashes and fail-closed completion gates so resumption preserves both **where execution stopped** and **what approved work remains**.

See [`docs/AGENT_CONTINUITY.md`](docs/AGENT_CONTINUITY.md).

The application runtime SQLite database and Agent Continuity SQLite database are separate systems.

## Non-commercial exploration

KomaMori is designed for personal experimentation and small-group internal use. It is not intended to operate a public catalog of third-party copyrighted manga. Public demos should use original, public-domain, or otherwise authorized content.

## Documentation

- [`docs/CONCEPT.md`](docs/CONCEPT.md) — product concept and scope boundaries
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — implemented architecture and data model
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — executed phases and remaining engineering/research tracks
- [`docs/AGENT_CONTINUITY.md`](docs/AGENT_CONTINUITY.md) — continuity protocol and completion gates
