# KomaMori

**A self-hosted web workspace for turning manga pages into structured, multilingual, editable reading experiences.**

KomaMori is a personal technical exploration project for manga localization and reading. Instead of treating a translated page as one flattened output image, it keeps the source page, text regions, OCR text, masks, clean assets, localizations, review state, and per-language layout as reusable structured data.

> **Status: hardened experimental MVP.** The complete manual-review workflow is implemented for dialogue/narration-style regions. Detection, OCR, cleanup and typesetting remain exploration baselines rather than production scanlation quality.

## What works today

- image and CBZ/ZIP chapter import with bounded page/byte/pixel preflight
- Series / Chapter create, edit and delete lifecycle
- recoverable page replace, delete and reorder lifecycle
- original assets are immutable once written; page replacement creates a new original path and invalidates obsolete page-bound state instead of overwriting the old file in place
- derived-asset cleanup follows commit-safe ordering: durable DB state commits before old referenced files are removed
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
- exact reuse of approved translations when the approval is eligible for reuse
- terminology-policy changes invalidate affected review/reuse state
- multiple target locales on one shared structured source
- per-locale auto-fit metadata and poor-fit detection
- deterministic QA for missing source/translation, terminology, provider OCR confidence and layout fit
- manual translation editing, review and approval
- publication-aware per-locale readiness: `in-progress` / `review` / `ready`
- `Ready` requires resolved source classification, nonempty approved translations and zero blocking deterministic QA errors
- multilingual Reader with Original / Localized switching and readiness disclosure
- SQLite + local filesystem self-hosted persistence
- file-backed SQLite uses foreign keys, WAL and a bounded busy timeout
- versioned runtime database migration ledger
- localhost-only Docker Compose web exposure by default
- backend, frontend build, container build and browser E2E CI gates

`unknown` and `sfx` regions are intentionally excluded from automatic cleanup/localization until explicitly handled. An unresolved `unknown` region also blocks locale `Ready`; a region explicitly classified as `sfx` does not. SFX reconstruction itself remains deferred.

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
     publication readiness gate
                 ↓
       Ready / review / partial
                 ↓
               Reader
```

Original asset files are never edited in place. A page replacement writes a new original asset, commits the new page identity/state, then best-effort removes obsolete old assets. Geometry/type changes invalidate affected clean/mask state, source-text changes invalidate translation approval/reuse state, and terminology-policy changes conservatively invalidate affected locale approval/reuse state.

The cross-store failure rule is deliberate: **prefer a recoverable orphan file over a committed database reference to a file that was deleted before commit**. Interrupted post-commit cleanup may therefore leave an orphan asset; a future audit/GC command is tracked separately.

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

The Compose port is bound to `127.0.0.1` by default. KomaMori does not currently provide built-in multi-user authentication; exposing it to a LAN or public network requires an explicit binding change plus access control supplied by the operator.

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

Without these variables, import, page recovery, region editing, cleanup, manual localization, QA, approval and Reader workflows remain usable. Only **AI localize** requires a provider.

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

Browser workflows:

```bash
cd apps/web
npx playwright install chromium
npm run test:e2e
```

Pull requests run:

- backend pytest
- TypeScript + Vite production build
- Docker Compose configuration + API/Web image builds
- Playwright full-stack browser workflows, including negative release invariants

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
  ├── local immutable-file asset store
  ├── OpenCV processing + persistent masks
  ├── Tesseract / optional MangaOCR
  ├── deterministic QA / readiness gate
  └── OpenAI-compatible translation provider
```

Core model:

```text
Series
└── Chapter
    └── Page
        ├── OriginalAsset          immutable file; replace creates a new path
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
approved reusable translations
source/target locale
review status
layout metadata
```

`approved` and `reusable` are related but not identical. A human can mark a translation approved, while reuse memory is populated only for a translatable region with nonempty source text and no blocking deterministic QA error. This prevents unresolved/QA-invalid text from propagating through approved-memory reuse.

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
- post-commit best-effort asset cleanup can leave orphan files if interrupted; audit/GC tooling is deferred
- frontend dependency resolution is not yet lockfile-hardened
- OCR/LLM/prompt provenance is not yet sufficient for repeatable model benchmarking
- chapter display numbering still uses the current numeric model
- repository branch protection / required CI enforcement is not configured through the current tool boundary
- SFX reconstruction/style matching is deferred
- no built-in multi-user authentication, collaboration or public manga catalog

These are explicit engineering/research targets, not hidden production claims.

## Agent Continuity experiment

KomaMori is also the live test bed for **Agent Continuity v0.3**: disposable development sessions backed by GitHub for implementation/reviewable scope and an external SQLite execution-state snapshot.

The current protocol adds durable `ScopeSource` / `ReviewFinding` capture, cross-cutting invariants, a Scope Capture Gate, commit-bound acceptance evidence, change-impact staleness, a Completion Gate and a mandatory Fresh Reviewer Gate. A new material reviewer finding invalidates prior capture/completion authority until it is recaptured and reverified.

In Execute mode, scope creation, checkpoints, PR creation and running CI are intermediate milestones rather than stopping conditions; absent a real blocker, execution carries through to verification/review/finalization.

See [`docs/AGENT_CONTINUITY.md`](docs/AGENT_CONTINUITY.md).

The application runtime SQLite database and Agent Continuity SQLite database are separate systems.

## Non-commercial exploration

KomaMori is designed primarily for personal experimentation. The default self-host configuration is localhost-only and has no built-in multi-user authentication. It is not intended to operate a public catalog of third-party copyrighted manga. Public demos should use original, public-domain, or otherwise authorized content.

## Documentation

- [`docs/CONCEPT.md`](docs/CONCEPT.md) — product concept and scope boundaries
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — implemented architecture and data model
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — executed phases and remaining engineering/research tracks
- [`docs/AGENT_CONTINUITY.md`](docs/AGENT_CONTINUITY.md) — continuity protocol and completion gates
