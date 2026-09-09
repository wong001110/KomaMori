# KomaMori Roadmap

This roadmap is intentionally staged around **usable capability first, experimentation second**.

The project is a personal/small-group technical exploration, so later phases may investigate ideas with uncertain product ROI. However, each experiment should have a baseline and a clear hypothesis rather than becoming permanent architecture by default.

---

## Phase 0 — Project foundation

### Goal

Create the smallest stable project skeleton and lock the source/localization data model before implementing AI features.

### Deliverables

- [ ] Next.js / React web application shell
- [ ] FastAPI application backend
- [ ] SQLite database
- [ ] local asset storage layout
- [ ] Series / Chapter / Page entities
- [ ] `TextRegion` schema
- [ ] per-locale `Localization` schema
- [ ] original vs derived asset rules
- [ ] basic Library → Series → Chapter navigation

### Exit condition

A manga chapter can be imported manually and represented as structured pages even if regions/translations are still entered by hand.

---

## Phase 1 — Usable single-language localization core

### Goal

Complete one chapter through the full workflow without requiring external image-editing software for normal dialogue/narration.

### Import and processing

- [ ] image import
- [ ] CBZ import
- [ ] page ordering
- [ ] text-region detection
- [ ] OCR integration
- [ ] reading-order reconstruction
- [ ] editable OCR results

### Cleaning

- [ ] generate text masks
- [ ] preserve immutable original page
- [ ] flat-background cleanup
- [ ] basic inpainting
- [ ] clean asset preview / reject / regenerate

### Localization

- [ ] choose one initial target language
- [ ] LLM translation provider abstraction
- [ ] nearby-dialogue context
- [ ] editable translation results
- [ ] simple fixed terminology store

### Typesetting

- [ ] basic text overlay editor
- [ ] locale layout data
- [ ] font selection
- [ ] alignment / line-height controls
- [ ] initial auto-fit
- [ ] manual override support

### Review / reader

- [ ] per-region review status
- [ ] render translated page
- [ ] chapter reader
- [ ] original / translated toggle

### Out of scope

- SFX reconstruction
- speaker detection
- character voice model
- emotion classifier
- semantic RAG
- multi-user collaboration

### Exit condition

A normal dialogue-heavy chapter can be imported, OCRed, translated, cleaned, typeset, reviewed, and read inside KomaMori.

---

## Phase 2 — Multilingual structured library

### Goal

Validate the key KomaMori abstraction: process the manga source once, then attach multiple localizations without repeating OCR or cleanup.

### Deliverables

- [ ] multiple target locales per chapter
- [ ] locale-specific layout
- [ ] language switcher in reader
- [ ] locale readiness/status indicators
- [ ] per-locale page render cache
- [ ] render invalidation after editing
- [ ] optional bilingual/original comparison mode

### Localization Store expansion

- [ ] locked terminology
- [ ] aliases
- [ ] approved translations
- [ ] project localization rules
- [ ] basic fuzzy reuse of previous approved lines where useful

Do not split these into separate CAT services unless real complexity appears.

### Exit condition

The same processed chapter can be read in at least two target languages using one shared structured source.

---

## Phase 3 — Quality and review loop

### Goal

Reduce the amount of manual correction without hiding AI uncertainty.

### Deterministic QA

- [ ] untranslated-region detection
- [ ] locked-term validation
- [ ] low OCR-confidence warnings
- [ ] overflow detection
- [ ] minimum readable font-size rule
- [ ] missing/invalid region checks

### Semantic QA

- [ ] optional structured LLM review
- [ ] mistranslation / context warning
- [ ] naturalness suggestions
- [ ] preserve original + suggestion + accepted edit provenance

### Translation ↔ layout feedback

- [ ] detect poor fit
- [ ] calculate useful shortening target
- [ ] request shorter equivalent translation
- [ ] preserve locked terminology and meaning constraints
- [ ] re-run auto-fit
- [ ] compare shortened result with original translation

### Reader correction loop

- [ ] jump from reader region/page to editor
- [ ] edit translation
- [ ] invalidate affected render only
- [ ] regenerate page
- [ ] save approved result for future reuse

### Exit condition

The user can focus primarily on exceptions and low-confidence regions instead of manually inspecting every system step from scratch.

---

## Phase 4 — Multimodal translation experiments

### Goal

Measure where visual/contextual signals improve translation instead of assuming every manga translation needs a complicated character system.

Each experiment must compare against the current baseline.

### Experiment A — Visual-context escalation

**Hypothesis:** a VLM improves ambiguous dialogue when nearby visual context matters.

- [ ] select ambiguous/low-confidence examples
- [ ] text-only baseline
- [ ] panel-image + text run
- [ ] compare human preference / correction rate
- [ ] decide when VLM escalation is worthwhile

### Experiment B — Speaker metadata

**Hypothesis:** speaker identity reduces errors involving omitted subjects, register, relationships, or pronouns.

- [ ] manually label a small evaluation set first
- [ ] compare translation with/without speaker metadata
- [ ] only then investigate automatic speaker extraction

Speaker detection is promoted to core only if it produces a meaningful improvement.

### Experiment C — Larger context

**Hypothesis:** selected prior dialogue improves continuity more than simply increasing raw context size.

Compare:

- current region only
- nearby N regions
- current panel
- selected previous dialogue
- later, semantic retrieval if justified

### Explicit non-goal

Do not create dedicated emotion or character-voice services simply because the concepts exist. Let a general LLM/VLM infer dynamic tone from context unless evidence shows that durable modeling improves results.

---

## Phase 5 — Rendering intelligence

### Goal

Explore harder visual-localization problems after the standard dialogue pipeline is stable.

### Advanced auto-fit

- [ ] polygon / balloon-aware safe area
- [ ] better candidate line-break search
- [ ] balanced line scoring
- [ ] vertical text experimentation if relevant
- [ ] script-specific typography rules

### Typography role

Instead of predicting exact original font names, explore visual roles such as:

```text
normal dialogue
shout
whisper
thought
narration
horror / dramatic
```

- [ ] source visual-style extraction
- [ ] target font-role mapping
- [ ] compare manual preference

### Advanced cleanup

- [ ] route between deterministic fill / conventional inpaint / neural inpaint
- [ ] manual mask refinement
- [ ] difficult artwork benchmark

---

## Phase 6 — SFX exploration

### Goal

Treat SFX as a dedicated graphics/localization research problem instead of letting it complicate the initial pipeline.

Possible experiments:

- [ ] identify SFX regions separately from normal text
- [ ] OCR stylized/rotated Japanese SFX
- [ ] semantic translation / localization choices
- [ ] preserve-vs-replace reader mode
- [ ] transformed target text placement
- [ ] outline / rotation / warp reproduction
- [ ] background reconstruction quality

### Success criterion

SFX automation should only become a normal workflow when it reduces manual graphics work without visibly damaging the artwork.

---

## Phase 7 — Experiment harness

### Goal

Turn KomaMori into a repeatable domain-specific AI experimentation environment without coupling experiments to production behavior.

### Track per run

- model/provider
- prompt/version
- context strategy
- VLM on/off
- terminology strategy
- latency
- estimated API cost when applicable
- translation output
- human corrections
- acceptance/preference score

### Example comparisons

```text
Model A vs Model B
2 nearby bubbles vs 6
text-only vs VLM
fixed terms vs no fixed terms
speaker metadata vs none
layout-aware shortening vs ordinary translation
```

### Exit condition

A new translation hypothesis can be evaluated against a fixed dataset without changing the core application workflow.

---

## Possible later directions — not committed roadmap

These are ideas, not promised phases:

- progressive/on-demand chapter processing while reading
- prefetching likely next chapters/pages
- LAN/private multi-user access
- comments or lightweight internal review collaboration
- self-hosted local LLM/VLM providers
- PostgreSQL migration
- object storage
- semantic retrieval across long series
- public demo/library for authorized content

---

# Evaluation principles

## Primary practical metric

For real chapter use, track roughly:

```text
manual correction time per page
```

and/or:

```text
% regions accepted without manual modification
```

This matters more than how many AI components are present.

## Useful component metrics

### OCR

- detection misses
- OCR correction rate
- reading-order errors

### Translation

- meaning errors
- terminology errors
- context errors
- naturalness corrections

### Cleaning

- accepted clean regions/pages
- visible artifacts
- destructive inpainting errors

### Typesetting

- auto-accepted layout
- minor manual adjustment
- full manual redo

## Research rule

Every optional intelligence feature should answer:

> What measurable failure does this solve compared with the simpler baseline?

If the answer remains unclear, keep the feature as an experiment or remove it.

---

# Current status

**Phase 0 — concept and architecture definition.**

No implementation assumptions beyond the initial architecture should be treated as permanent until the first real chapter passes through the workflow.
