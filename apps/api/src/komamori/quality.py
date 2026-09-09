from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Chapter, Localization, LocalizationTerm, Page, TextRegion
from .region_types import TRANSLATABLE_REGION_TYPES
from .schemas import QAIssue


def terms_for(session: Session, series_id: int, locale: str) -> list[LocalizationTerm]:
    return list(
        session.scalars(
            select(LocalizationTerm).where(
                LocalizationTerm.series_id == series_id,
                LocalizationTerm.locale == locale,
            )
        )
    )


def term_variants(term: LocalizationTerm) -> list[str]:
    variants = [term.source, *(term.aliases or [])]
    return list(dict.fromkeys(value.strip() for value in variants if value and value.strip()))


def locked_terms_for_source(terms: list[LocalizationTerm], source_text: str) -> dict[str, str]:
    locked: dict[str, str] = {}
    for term in terms:
        if not term.locked:
            continue
        for variant in term_variants(term):
            if variant in source_text:
                locked[variant] = term.target
    return locked


def chapter_qa_issues(session: Session, chapter: Chapter, locale: str) -> list[QAIssue]:
    terms = terms_for(session, chapter.series_id, locale)
    issues: list[QAIssue] = []
    rows = session.execute(
        select(TextRegion, Page)
        .join(Page, TextRegion.page_id == Page.id)
        .where(Page.chapter_id == chapter.id)
        .order_by(Page.page_index, TextRegion.reading_order, TextRegion.id)
    ).all()

    for region, page in rows:
        if region.region_type not in TRANSLATABLE_REGION_TYPES:
            continue
        loc = session.scalar(
            select(Localization).where(
                Localization.text_region_id == region.id,
                Localization.locale == locale,
            )
        )
        if not region.source_text.strip():
            issues.append(
                QAIssue(
                    code="missing-source",
                    severity="error",
                    page_id=page.id,
                    region_id=region.id,
                    localization_id=loc.id if loc else None,
                    message="Translatable region has no source text",
                )
            )
        if loc is None or not loc.text.strip():
            issues.append(
                QAIssue(
                    code="untranslated",
                    severity="error",
                    page_id=page.id,
                    region_id=region.id,
                    message="Region has no translation",
                )
            )
            continue
        if region.ocr_confidence is not None and region.ocr_confidence < 0.65:
            issues.append(
                QAIssue(
                    code="low-ocr-confidence",
                    severity="warning",
                    page_id=page.id,
                    region_id=region.id,
                    localization_id=loc.id,
                    message=f"OCR confidence is {region.ocr_confidence:.2f}",
                )
            )
        for term in terms:
            if not term.locked:
                continue
            matched = [variant for variant in term_variants(term) if variant in region.source_text]
            if matched and term.target not in loc.text:
                issues.append(
                    QAIssue(
                        code="locked-term",
                        severity="error",
                        page_id=page.id,
                        region_id=region.id,
                        localization_id=loc.id,
                        message=f"Locked term '{term.source}' (matched '{matched[0]}') must use '{term.target}'",
                    )
                )
        if loc.layout.get("fitStatus") == "poor-fit":
            issues.append(
                QAIssue(
                    code="poor-fit",
                    severity="warning",
                    page_id=page.id,
                    region_id=region.id,
                    localization_id=loc.id,
                    message="Translation does not fit the current region at the minimum font size",
                )
            )
    return issues


def blocking_error_count(session: Session, chapter: Chapter, locale: str) -> int:
    return sum(1 for issue in chapter_qa_issues(session, chapter, locale) if issue.severity == "error")
