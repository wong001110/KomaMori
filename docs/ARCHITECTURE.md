# KomaMori Architecture

## 1. Architectural goal

KomaMori should begin as a **modular web application with Python-native processing**, not as a collection of services.

The project has three materially different workload types:

1. interactive web editing and reading
2. structured application/data management
3. compute-heavy OCR, CV, image processing, and model inference

Those boundaries justify modules and background work, but not early microservices.

## 2. Initial shape

```text
┌────────────────────────────────────┐
│            Web Application         │
│   Library / Reader / Editor / QA   │
│        React / Next.js             │
└─────────────────┬──────────────────┘
                  │
                  ▼
┌────────────────────────────────────┐
│          Python Application        │
│              FastAPI               │
│                                    │
│ projects / chapters / pages        │
│ localization / review / render     │
└──────────────┬───────────┬─────────┘
               │           │
               ▼           ▼
       structured data   file assets
       SQLite/Postgres   local/S3-like
               │
               ▼
        background processing
               │
        ┌──────┼────────────┐
        ▼      ▼            ▼
       OCR    CV/Image     LLM/VLM
```

For a single-user local setup, SQLite + local filesystem is sufficient. PostgreSQL/object storage can be introduced when multi-user or server deployment actually requires them.

## 3. Core application modules

Keep the mental model small.

### Content Processing

Responsible for converting raw manga pages into structured source data.

Includes:

- import / archive parsing
- page metadata
- text-region detection
- OCR
- reading order
- text masks
- clean-page generation

### Localization

Responsible for target-language data and translation behavior.

Includes:

- translation generation
- nearby context assembly
- localization store lookups
- terminology constraints
- approved translation reuse
- lightweight QA

### Editor / Rendering

Responsible for turning structured localization into an editable visual result.

Includes:

- per-locale layout
- auto-fit
- manual text editing
- region editing
- render generation
- invalidation / re-rendering

### Library / Reader

Responsible for presenting processed content as a usable manga collection.

Includes:

- series / chapter browsing
- locale availability
- reading mode
- original vs translated view
- cached rendered pages

These are application modules, not separate deployed services by default.

## 4. Core data model

The initial schema should optimize for a stable source representation and replaceable derived assets.

```text
Series
└── Chapter
    └── Page
        ├── OriginalAsset
        ├── CleanAsset?              derived
        └── TextRegion[]
            ├── geometry
            ├── type
            ├── sourceText
            ├── OCR metadata
            ├── readingOrder
            ├── mask
            └── Localization[]
                ├── locale
                ├── text
                ├── status
                ├── provenance
                └── layout
```

### Series

Suggested fields:

```text
id
title
sourceLanguage
metadata
createdAt
updatedAt
```

### Chapter

```text
id
seriesId
title
number
status
pageCount
createdAt
updatedAt
```

Possible status values initially:

```text
raw
processing
review
ready
```

### Page

```text
id
chapterId
index
originalAssetId
cleanAssetId?
width
height
processingStatus
```

### TextRegion

Use this instead of making `Bubble` the root abstraction.

```text
id
pageId
type
polygon / geometry
sourceText
oCRConfidence?
readingOrder
maskAssetId?
sourceStyle?       optional
balloonId?         optional
```

Possible `type` values can begin small:

```text
dialogue
thought
narration
caption
sign
sfx
unknown
```

Do not overfit the enum before real examples are processed.

### Localization

```text
id
textRegionId
locale
text
status
source
qualityMetadata?
layout
updatedAt
```

Possible `source` values:

```text
machine
manual
approved-memory
```

Possible `status` values:

```text
draft
needs-review
approved
```

### Layout

Layout is per localization.

```text
fontFamily
fontSize
lineHeight
letterSpacing
alignment
rotation
lineBreaks / fittedLines
manualOverride
```

Keep this replaceable. Auto-layout should be able to regenerate values unless `manualOverride` is set.

## 5. Localization Store

Do not implement five separate CAT subsystems initially. A practical localization store can cover the durable decisions KomaMori needs.

Example concepts:

```text
LocalizationTerm
├ source
├ target
├ locale
├ type
├ aliases
├ locked
└ notes

ApprovedTranslation
├ sourceText
├ targetText
├ locale
├ seriesId / project scope
└ provenance

LocalizationRule
├ scope
├ key
├ value
└ notes
```

This supports the useful parts of termbases, glossaries, translation memory, and project style decisions without committing to enterprise CAT complexity.

## 6. Processing graph

The workflow should be modeled conceptually as a DAG rather than one rigid sequence.

```text
Import
  ↓
Page extraction
  ↓
Text-region detection
  ↓
OCR / reading order
  │
  ├───────────────┐
  ▼               ▼
Mask generation   Localization
  ↓               ↓
Inpainting        Translation / QA
  │               │
  └───────┬───────┘
          ▼
    Per-locale layout
          ↓
        Review
          ↓
        Render
          ↓
        Reader
```

Once source regions are known, localization and clean-page generation can proceed independently.

## 7. Derived asset rules

These should never replace the original source:

- OCR text
- masks
- clean pages
- translated text
- layouts
- rendered pages

The original import is immutable unless the user explicitly replaces it.

A rendered page is a cache/output of:

```text
clean page + locale text + locale layout
```

Changing one localization should invalidate only the affected page/locale render.

## 8. Translation execution

Baseline translation input:

```text
current source text
+ nearby dialogue
+ fixed terminology
+ approved prior translations when relevant
```

Optional visual escalation:

```text
If text-only translation is ambiguous or explicitly requested:
    include panel/page crop in a VLM call
```

Do not run a VLM for every region by default unless benchmarking shows the quality/cost tradeoff is worthwhile.

## 9. QA model

Prefer cheap deterministic checks first:

```text
OCR confidence too low?
source region has no translation?
locked terminology violated?
layout overflow?
font size below threshold?
```

Only semantic questions should normally require an LLM review, for example:

- mistranslation
- lost nuance
- context contradiction
- unnatural phrasing

This review does not need to be a separate agent architecture; it can be one structured model call when needed.

## 10. Auto-fit

Initial auto-fit can be conventional layout logic:

```text
region / balloon safe area
↓
try candidate line breaks
↓
measure text
↓
search font size
↓
score fit
↓
best acceptable layout
```

If no acceptable layout exists, return a constraint such as:

```text
poor-fit
recommended target length ≤ N
```

The translation layer may then request a shorter equivalent while preserving meaning and locked terminology.

## 11. Background execution

Do not begin with Temporal or distributed workflow infrastructure.

Start with the simplest mechanism that allows long-running work not to block HTTP requests:

```text
API request
↓
create processing task
↓
background worker
↓
progress stored
↓
UI polls or receives SSE updates
```

A lightweight Python job queue or worker process is enough initially.

Introduce durable workflow orchestration only if the project actually develops requirements such as:

- long human pause/resume steps
- complicated cross-worker dependencies
- distributed workers
- resilient workflow replay
- multi-hour/multi-day stateful execution

## 12. Initial technology direction

This is a direction, not a permanent lock-in.

| Concern | Initial choice |
| --- | --- |
| Web UI | React / Next.js |
| Interactive page editor | Canvas-based editor, likely Konva or equivalent |
| API | FastAPI |
| Initial DB | SQLite |
| Multi-user DB later | PostgreSQL |
| Asset storage | Local filesystem initially |
| OCR runtime | Python |
| CV/image processing | OpenCV / PyTorch ecosystem |
| Japanese manga OCR | Evaluate MangaOCR and alternatives |
| General multilingual OCR | Evaluate PaddleOCR and alternatives |
| Inpainting | conventional + neural routing based on region complexity |
| Translation | provider abstraction over general LLM/VLM APIs/local models |
| Progress | SSE first; WebSocket only if interaction requires it |

## 13. Architecture guardrails

Before adding a new subsystem, answer at least one of these:

- Does it remove a measured failure mode?
- Does it materially simplify the existing code?
- Does it support a real experiment that cannot be performed with current boundaries?
- Does it handle a workload with genuinely different lifecycle or deployment requirements?

If none apply, keep it inside the existing module.
