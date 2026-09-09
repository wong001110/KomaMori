# KomaMori Concept

## 1. What KomaMori is

KomaMori is a **self-hosted, web-first manga localization and reading workspace** built primarily for personal technical exploration and small-group internal use.

It is not trying to compete with commercial manga platforms or maximize automation. The project exists to explore how computer vision, OCR, image processing, large multimodal models, structured localization data, typesetting, and a reader can work together in one coherent workflow.

The central idea is simple:

> A manga should not become a translated image and then lose all of its structure. KomaMori keeps that structure so the same source can support multiple languages, editing, rendering, review, and reading.

## 2. Product mental model

KomaMori should feel more like a personal manga library than a translation dashboard.

```text
Upload / Import
      ↓
Structure manga
      ↓
Localize
      ↓
Review
      ↓
Read
      ↓
Correct when needed
      ↓
Re-render
```

The reader is therefore not an unrelated feature added at the end. It is one consumer of the same structured localization project.

## 3. Source structure before translation

The first meaningful output of processing is **not a translated page**. It is a structured source page.

```text
Page
├── original image
├── text regions
│   ├── geometry
│   ├── type
│   ├── OCR text
│   ├── reading order
│   └── source visual metadata
├── text masks
└── derived clean image
```

A `TextRegion` is deliberately more general than a `Bubble` because manga contains several forms of textual content:

- dialogue
- thought text
- narration
- captions
- signs / environmental text
- interface or phone-screen text
- sound effects (SFX)

A region may be associated with a speech balloon, but the data model should not require every region to have one.

## 4. Localization is another layer

Each target language attaches its own localization data to a source text region.

```text
TextRegion
├── source text
├── English localization
│   ├── translation
│   ├── status
│   └── layout
├── Chinese localization
│   ├── translation
│   ├── status
│   └── layout
└── Malay localization
    ├── translation
    ├── status
    └── layout
```

Layout belongs to a locale because the same meaning can occupy very different amounts of space in English, Chinese, Malay, or other languages.

This makes adding another language primarily a **localization task**, not a repeat of OCR, text detection, or image cleanup.

## 5. Localization data, not an overbuilt CAT suite

Traditional CAT systems introduce concepts such as Translation Memory, Termbase, Glossary, and QA rules. KomaMori should use the useful ideas without prematurely reproducing an enterprise CAT architecture.

For the initial project, these can live under one practical concept:

**Localization Store**

It can contain:

- fixed names and terminology
- aliases
- approved translations
- translation history
- stable project-level rules
- optional world or relationship facts when they are actually useful

The distinction to preserve is not between five separate services. It is between two kinds of information:

### Durable decisions

Persist these because they should remain consistent:

- character names
- place names
- organizations
- titles
- items
- technique names
- official or approved translations
- project style decisions

### Dynamic interpretation

Usually let a general LLM/VLM infer these from the current context:

- current emotion
- sarcasm
- current speaking tone
- immediate scene mood
- whether a character is angry, nervous, or joking

KomaMori should not create dedicated character-voice or emotion subsystems unless experiments demonstrate a concrete need.

## 6. Translation strategy

Translation can use several sources of evidence without turning each one into a separate agent:

```text
Current OCR text
+ nearby dialogue
+ relevant page/panel image when useful
+ fixed terminology
+ approved previous translations
+ project rules
        ↓
General LLM / VLM
        ↓
Translation
```

General multimodal models should handle semantic reasoning such as scene context and ambiguous tone. Specialized models should be reserved for tasks where pixel-level accuracy or cost makes them more appropriate, such as OCR, masks, or inpainting.

## 7. Translation ↔ layout feedback

Translation and typesetting should not be completely isolated.

If a correct translation only fits by shrinking the text below an acceptable size, the layout engine can report a constraint back to translation:

```text
Translation
    ↓
Auto-fit
    ↓
Poor fit
    ↓
Request a shorter equivalent
    ↓
Re-fit
```

The translation system must still preserve meaning and locked terminology. Layout should influence wording only when necessary, rather than becoming an excuse for uncontrolled paraphrasing.

## 8. Cleaning and inpainting

The original page is immutable.

Cleaning produces derived assets:

```text
Original image
├── text masks
└── clean image (derived)
```

The clean image may be generated differently depending on the region:

- flat background → deterministic fill
- simple texture → conventional inpainting
- complex artwork → neural inpainting

If an inpainting result is bad, it should be possible to reject, repair, or regenerate it without losing source data.

OCR/translation and inpainting do not need to be strictly sequential after text regions are known; they can proceed as independent branches of the page-processing workflow.

## 9. Typesetting and auto-fit

Typesetting is part of each locale, not part of the source page.

The first useful auto-fit system only needs to solve practical constraints:

- available region / balloon area
- inner padding
- line breaking
- font size
- alignment
- overflow
- minimum readable size

Advanced typography can come later. The quality metric is not how sophisticated the algorithm sounds; it is how often its output can be accepted without manual correction.

## 10. SFX

Sound effects are intentionally not a first-stage automation target.

SFX can be part of the artwork itself — rotated, distorted, outlined, perspective-warped, partially hidden behind objects, or integrated with a composition. Translating them involves more than OCR and text replacement.

Initial behavior:

- detect or preserve SFX when possible
- allow manual handling
- do not let SFX block the main dialogue/narration pipeline

Later SFX experiments may explore:

- SFX OCR and semantic translation
- background reconstruction
- visual-role / style matching
- transformed text placement

## 11. Reader and library

The same structured source should power a library and reader.

```text
Library
└── Series
    └── Chapters
        ├── Raw
        ├── English ready
        ├── Chinese ready
        └── other locales
```

Potential reader modes:

- translated page
- original page
- switch target language
- original/translation comparison
- optional bilingual overlay

For normal reading, KomaMori can serve cached rendered pages for speed while keeping translations and layouts structured underneath. Editing invalidates only the affected render rather than forcing the entire chapter to be processed again.

## 12. Publish semantics

`Ready` or `Published` should first mean **available in the KomaMori library**, not necessarily public on the Internet.

Possible visibility levels later:

- private — only the owner
- shared — invited internal users
- public — only content that is original, public-domain, or otherwise authorized for redistribution/localization

Non-commercial status does not itself grant permission to publicly redistribute copyrighted manga, so public distribution is not a design assumption.

## 13. What not to build prematurely

Do not begin with:

- microservices
- dedicated emotion models
- dedicated character-voice agents
- a complex character-memory system
- vector search without an observed retrieval need
- a full enterprise CAT architecture
- automatic SFX reconstruction
- a workflow engine merely because the eventual workflow could become complex

Add these only when a measured limitation or experiment justifies them.

## 14. Exploration philosophy

KomaMori should make experiments easy without making experimental features part of the permanent architecture by default.

A useful pattern is:

```text
Hypothesis
↓
Small experiment
↓
Compare against baseline
↓
Keep, modify, or remove
```

Example:

> Speaker metadata reduces translation errors involving omitted subjects, relationships, or register.

Test it against a baseline using the same pages. If no meaningful improvement appears, speaker extraction remains optional rather than becoming a core dependency.

This keeps KomaMori useful as both a personal tool and an AI/CV learning environment.
