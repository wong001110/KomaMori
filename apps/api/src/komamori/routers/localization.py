from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..autofit import layout_payload
from ..db import get_session
from ..models import ApprovedTranslation, Chapter, Localization, LocalizationTerm, Page, Series, TextRegion
from ..quality import chapter_qa_issues, locked_terms_for_source, terms_for
from ..region_types import TRANSLATABLE_REGION_TYPES
from ..schemas import ApprovalResult, LocalizationRead, LocalizationTermCreate, LocalizationTermRead, LocalizationUpsert, LocalizeChapterRequest, LocalizeChapterResult, QAResult
from ..translation import TranslationProvider, TranslationRequest, get_translation_provider, translation_provenance

router = APIRouter(prefix="/api", tags=["localization"])


def _invalidate_locale_policy(session: Session, series_id: int, locale: str) -> None:
    localizations = list(
        session.scalars(
            select(Localization)
            .join(TextRegion, Localization.text_region_id == TextRegion.id)
            .join(Page, TextRegion.page_id == Page.id)
            .join(Chapter, Page.chapter_id == Chapter.id)
            .where(Chapter.series_id == series_id, Localization.locale == locale)
        )
    )
    for localization in localizations:
        localization.status = "needs-review"
    session.execute(
        delete(ApprovedTranslation).where(
            ApprovedTranslation.series_id == series_id,
            ApprovedTranslation.locale == locale,
        )
    )


def _clear_approved_memory_for_region(session: Session, region: TextRegion, locale: str) -> None:
    if not region.source_text.strip():
        return
    page = session.get(Page, region.page_id)
    if page is None:
        return
    chapter = session.get(Chapter, page.chapter_id)
    if chapter is None:
        return
    session.execute(
        delete(ApprovedTranslation).where(
            ApprovedTranslation.series_id == chapter.series_id,
            ApprovedTranslation.locale == locale,
            ApprovedTranslation.source_text == region.source_text,
        )
    )


@router.get("/series/{series_id}/terms", response_model=list[LocalizationTermRead])
def list_terms(series_id: int, locale: str | None = None, session: Session = Depends(get_session)):
    if session.get(Series, series_id) is None:
        raise HTTPException(status_code=404, detail="Series not found")
    statement = select(LocalizationTerm).where(LocalizationTerm.series_id == series_id)
    if locale:
        statement = statement.where(LocalizationTerm.locale == locale)
    return list(session.scalars(statement.order_by(LocalizationTerm.source)))


@router.post("/series/{series_id}/terms", response_model=LocalizationTermRead, status_code=status.HTTP_201_CREATED)
def create_term(series_id: int, payload: LocalizationTermCreate, session: Session = Depends(get_session)):
    if session.get(Series, series_id) is None:
        raise HTTPException(status_code=404, detail="Series not found")
    existing = session.scalar(
        select(LocalizationTerm).where(
            LocalizationTerm.series_id == series_id,
            LocalizationTerm.locale == payload.locale,
            LocalizationTerm.source == payload.source,
        )
    )
    if existing:
        policy_changed = (
            existing.target != payload.target
            or list(existing.aliases or []) != list(payload.aliases)
            or existing.locked != payload.locked
            or existing.term_type != payload.term_type
        )
        existing.target = payload.target
        existing.term_type = payload.term_type
        existing.aliases = payload.aliases
        existing.locked = payload.locked
        existing.notes = payload.notes
        if policy_changed:
            _invalidate_locale_policy(session, series_id, payload.locale)
        session.commit()
        session.refresh(existing)
        return existing

    term = LocalizationTerm(series_id=series_id, **payload.model_dump())
    session.add(term)
    if term.locked:
        _invalidate_locale_policy(session, series_id, payload.locale)
    session.commit()
    session.refresh(term)
    return term


@router.get("/regions/{region_id}/localizations", response_model=list[LocalizationRead])
def list_localizations(region_id: int, session: Session = Depends(get_session)):
    if session.get(TextRegion, region_id) is None:
        raise HTTPException(status_code=404, detail="Text region not found")
    return list(session.scalars(select(Localization).where(Localization.text_region_id == region_id).order_by(Localization.locale)))


@router.put("/regions/{region_id}/localizations/{locale}", response_model=LocalizationRead)
def upsert_localization(region_id: int, locale: str, payload: LocalizationUpsert, session: Session = Depends(get_session)):
    region = session.get(TextRegion, region_id)
    if region is None:
        raise HTTPException(status_code=404, detail="Text region not found")
    localization = session.scalar(
        select(Localization).where(
            Localization.text_region_id == region_id,
            Localization.locale == locale,
        )
    )
    computed_layout = payload.layout or layout_payload(payload.text, region.geometry)
    manual_provenance = {"schema_version": 1, "kind": "manual"}
    if localization is None:
        effective_status = "needs-review" if payload.status == "approved" else payload.status
        localization = Localization(
            text_region_id=region_id,
            locale=locale,
            text=payload.text,
            status=effective_status,
            source="manual",
            provenance=manual_provenance,
            layout=computed_layout,
        )
        session.add(localization)
    else:
        text_changed = localization.text != payload.text
        was_approved = localization.status == "approved"
        if text_changed:
            effective_status = "needs-review"
        elif payload.status == "approved" and localization.status != "approved":
            effective_status = "needs-review"
        else:
            effective_status = payload.status
        localization.text = payload.text
        localization.status = effective_status
        localization.source = "manual"
        localization.provenance = manual_provenance
        localization.layout = computed_layout
        if text_changed and was_approved:
            _clear_approved_memory_for_region(session, region, locale)
    session.commit()
    session.refresh(localization)
    return localization


@router.post("/chapters/{chapter_id}/localize/{locale}", response_model=LocalizeChapterResult)
def localize_chapter(
    chapter_id: int,
    locale: str,
    payload: LocalizeChapterRequest,
    session: Session = Depends(get_session),
    provider: TranslationProvider = Depends(get_translation_provider),
) -> LocalizeChapterResult:
    chapter = session.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="Chapter not found")
    series = session.get(Series, chapter.series_id)
    assert series is not None
    terms = terms_for(session, series.id, locale)
    rows = session.execute(
        select(TextRegion, Page)
        .join(Page, TextRegion.page_id == Page.id)
        .where(Page.chapter_id == chapter_id)
        .order_by(Page.page_index, TextRegion.reading_order, TextRegion.id)
    ).all()

    created = reused = skipped = 0
    history: list[str] = []
    for region, _page in rows:
        if region.region_type not in TRANSLATABLE_REGION_TYPES or not region.source_text.strip():
            skipped += 1
            continue
        existing = session.scalar(
            select(Localization).where(
                Localization.text_region_id == region.id,
                Localization.locale == locale,
            )
        )
        if existing is not None and not payload.overwrite:
            history.append(region.source_text)
            skipped += 1
            continue
        approved = session.scalar(
            select(ApprovedTranslation).where(
                ApprovedTranslation.series_id == series.id,
                ApprovedTranslation.locale == locale,
                ApprovedTranslation.source_text == region.source_text,
            )
        )
        translation_request = TranslationRequest(
            source_text=region.source_text,
            source_language=series.source_language,
            target_locale=locale,
            nearby_context=history[-payload.context_regions :] if payload.context_regions else [],
            locked_terms=locked_terms_for_source(terms, region.source_text),
        )
        if approved:
            translated = approved.target_text
            source = "approved-memory"
            provenance = {
                "schema_version": 1,
                "kind": "approved-memory",
                "memory_provenance": approved.provenance,
            }
            reused += 1
        else:
            translated = provider.translate(translation_request)
            source = "machine"
            provenance = translation_provenance(provider, translation_request)
            created += 1
        layout = layout_payload(translated, region.geometry)
        quality = {"fitStatus": layout.get("fitStatus")}
        if existing is None:
            existing = Localization(
                text_region_id=region.id,
                locale=locale,
                text=translated,
                status="needs-review",
                source=source,
                provenance=provenance,
                quality_metadata=quality,
                layout=layout,
            )
            session.add(existing)
        else:
            existing.text = translated
            existing.status = "needs-review"
            existing.source = source
            existing.provenance = provenance
            existing.quality_metadata = quality
            existing.layout = layout
        history.append(region.source_text)

    chapter.status = "review"
    session.commit()
    return LocalizeChapterResult(chapter_id=chapter.id, locale=locale, created=created, reused=reused, skipped=skipped)


@router.get("/chapters/{chapter_id}/qa/{locale}", response_model=QAResult)
def qa_chapter(chapter_id: int, locale: str, session: Session = Depends(get_session)) -> QAResult:
    chapter = session.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return QAResult(chapter_id=chapter.id, locale=locale, issues=chapter_qa_issues(session, chapter, locale))


@router.post("/localizations/{localization_id}/approve", response_model=ApprovalResult)
def approve_localization(localization_id: int, session: Session = Depends(get_session)) -> ApprovalResult:
    loc = session.get(Localization, localization_id)
    if loc is None:
        raise HTTPException(status_code=404, detail="Localization not found")
    if not loc.text.strip():
        raise HTTPException(status_code=409, detail="Cannot approve an empty localization")
    region = session.get(TextRegion, loc.text_region_id)
    assert region is not None
    page = session.get(Page, region.page_id)
    assert page is not None
    chapter = session.get(Chapter, page.chapter_id)
    assert chapter is not None

    loc.status = "approved"
    region_has_blocking_error = any(
        issue.region_id == region.id and issue.severity == "error"
        for issue in chapter_qa_issues(session, chapter, loc.locale)
    )
    remembered = bool(
        region.region_type in TRANSLATABLE_REGION_TYPES
        and region.source_text.strip()
        and not region_has_blocking_error
    )
    if remembered:
        approved = session.scalar(
            select(ApprovedTranslation).where(
                ApprovedTranslation.series_id == chapter.series_id,
                ApprovedTranslation.locale == loc.locale,
                ApprovedTranslation.source_text == region.source_text,
            )
        )
        if approved is None:
            approved = ApprovedTranslation(
                series_id=chapter.series_id,
                locale=loc.locale,
                source_text=region.source_text,
                target_text=loc.text,
            )
            session.add(approved)
        else:
            approved.target_text = loc.text
    else:
        _clear_approved_memory_for_region(session, region, loc.locale)
    session.commit()
    return ApprovalResult(localization_id=loc.id, status=loc.status, remembered=remembered)
