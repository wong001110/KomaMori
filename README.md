# KomaMori

**A self-hosted web workspace for turning manga pages into structured, multilingual, editable reading experiences.**

KomaMori is a personal technical exploration project focused on manga localization rather than a commercial translation service. The core idea is to treat manga as **structured, localizable content** instead of a collection of flattened images.

A manga page is processed into reusable source data — text regions, OCR text, masks, clean assets, translations, and language-specific layout — then reused by the editor and reader.

## Core flow

```text
Import manga
    ↓
Detect text regions
    ↓
OCR + reading order
    ↓
Structured page data
   ↙             ↘
Masks / clean     Localization
assets             per language
   ↘             ↙
     Auto layout
          ↓
        Review
          ↓
        Render
          ↓
   Library / Reader
```

The important boundary is that **localization data is attached to structured text regions, not baked directly into the source image**. Original pages remain immutable; cleaned and rendered pages are derived assets that can be regenerated.

## What KomaMori explores

- manga text-region detection and OCR
- reading-order reconstruction
- AI-assisted translation with nearby panel/dialogue context
- fixed terminology and approved translation reuse
- text masks and inpainting for clean page assets
- language-specific typesetting and auto-fit
- translation ↔ layout feedback when translated text does not fit well
- human review and correction inside a web editor
- multilingual manga reading from the same structured source
- optional multimodal experiments where a general VLM can use visual context to resolve ambiguous dialogue

## Product shape

KomaMori is intended to feel like a small personal manga library rather than a translation dashboard.

```text
Library
└── Series
    └── Chapter
        ├── Original
        ├── English
        ├── 中文
        └── Other localizations
```

A chapter moves through a lightweight lifecycle:

```text
raw → processing → review → ready
```

The same structured source can support editing, rendering, experimentation, and reading without re-running OCR or image cleanup for every language.

## Design principles

1. **Structure first** — convert pages into reusable text regions and metadata before treating translation as the final artifact.
2. **Keep originals immutable** — OCR, masks, clean pages, translations, and renders are derived data.
3. **Use general models for semantic reasoning** — tone, emotion, ambiguity, and scene interpretation should usually be inferred from context instead of becoming separate AI subsystems.
4. **Persist decisions, not guesses** — names, terminology, approved translations, and stable localization rules belong in durable project data.
5. **Prefer deterministic checks where possible** — terminology violations, missing text, low OCR confidence, and layout overflow should not require an LLM when software can verify them directly.
6. **Human review remains first-class** — the goal is useful assistance and experimentation, not pretending every AI result is final.
7. **Avoid premature architecture** — start as a modular web application with Python-native AI processing; split services only when real workload boundaries require it.

## Initial technical direction

KomaMori is web-first and self-hostable.

```text
React / Next.js web UI
        │
        ▼
Python API / application backend
        │
        ├── structured project data
        ├── local or object-file storage
        └── background processing
                 │
                 ├── OCR
                 ├── OpenCV / image processing
                 ├── inpainting
                 └── LLM / VLM providers
```

Exact libraries are intentionally not locked yet. The project should validate the workflow before committing to unnecessary infrastructure.

## Scope boundaries

### Core

- image / CBZ import
- text-region detection
- OCR
- source page structure
- masks and clean-page generation
- translation with localization data
- per-language layout
- auto-fit
- review/edit workflow
- multilingual reader

### Later experiments

- speaker metadata when it demonstrably helps translation
- richer visual-context translation
- typography-role matching
- SFX localization
- model / prompt / context A/B evaluation
- progressive chapter processing

Specialized character-voice or emotion subsystems are **not** part of the core architecture. Modern general multimodal models can usually infer these dynamically from the current scene and dialogue; they should only become dedicated features if experiments show a clear benefit.

## Non-commercial exploration

KomaMori is designed for personal experimentation and small-group internal use. It is not intended to provide a public catalog of third-party copyrighted manga. Publicly shared demo content should be original, public-domain, or otherwise authorized for redistribution and localization.

## Documentation

- [`docs/CONCEPT.md`](docs/CONCEPT.md) — product concept, boundaries, and key ideas
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — core data model and processing architecture
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — staged implementation and research roadmap

## Status

**Concept / architecture definition.** Implementation has not started yet.
