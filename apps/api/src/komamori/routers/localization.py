from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..autofit import layout_payload
from ..db import get_session
from ..models import ApprovedTranslation, Chapter, Localization, LocalizationTerm, Page, Series, TextRegion
from ..schemas import ApprovalResult, LocalizationRead, LocalizationTermCreate, LocalizationTermRead, LocalizationUpsert, LocalizeChapterRequest, LocalizeChapterResult, QAIssue, QAResult
from ..translation import TranslationProvider, TranslationRequest, get_translation_provider

router = APIRouter(prefix="/api", tags=["localization"])


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
    existing = session.scalar(select(LocalizationTerm).where(LocalizationTerm.series_id == series_id, LocalizationTerm.locale == payload.locale, LocalizationTerm.source == payload.source))
    if existing:
        existing.target = payload.target
        existing.term_type = payload.term_type
        existing.aliases = payload.aliases
        existing.locked = payload.locked
        existing.notes = payload.notes
        session.commit()
        session.refresh(existing)
        return existing
    term = LocalizationTerm(series_id=series_id, **payload.model_dump())
    session.add(term)
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
    localization = session.scalar(select(Localization).where(Localization.text_region_id == region_id, Localization.locale == locale))
    computed_layout = payload.layout or layout_payload(payload.text, region.geometry)
    if localization is None:
        localization = Localization(text_region_id=region_id, locale=locale, text=payload.text, status=payload.status, source="manual", layout=computed_layout)
        session.add(localization)
    else:
        localization.text = payload.text
        localization.status = payload.status
        localization.source = "manual"
        localization.layout = computed_layout
    session.commit()
    session.refresh(localization)
    return localization


def _terms_for(session: Session, series_id: int, locale: str) -> list[LocalizationTerm]:
    return list(session.scalars(select(LocalizationTerm).where(LocalizationTerm.series_id == series_id, LocalizationTerm.locale == locale)))


@router.post("/chapters/{chapter_id}/localize/{locale}", response_model=LocalizeChapterResult)
def localize_chapter(chapter_id: int, locale: str, payload: LocalizeChapterRequest, session: Session = Depends(get_session), provider: TranslationProvider = Depends(get_translation_provider)) -> LocalizeChapterResult:
    chapter = session.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="Chapter not found")
    series = session.get(Series, chapter.series_id)
    assert series is not None
    terms = _terms_for(session, series.id, locale)
    locked_terms = {term.source: term.target for term in terms if term.locked}
    rows = session.execute(select(TextRegion, Page).join(Page, TextRegion.page_id == Page.id).where(Page.chapter_id == chapter_id).order_by(Page.page_index, TextRegion.reading_order, TextRegion.id)).all()

    created = reused = skipped = 0
    history: list[str] = []
    for region, _page in rows:
        if region.region_type == "sfx" or not region.source_text.strip():
            skipped += 1
            continue
        existing = session.scalar(select(Localization).where(Localization.text_region_id == region.id, Localization.locale == locale))
        if existing is not None and not payload.overwrite:
            history.append(region.source_text)
            skipped += 1
            continue
        approved = session.scalar(select(ApprovedTranslation).where(ApprovedTranslation.series_id == series.id, ApprovedTranslation.locale == locale, ApprovedTranslation.source_text == region.source_text))
        if approved:
            translated = approved.target_text
            source = "approved-memory"
            reused += 1
        else:
            translated = provider.translate(TranslationRequest(source_text=region.source_text, source_language=series.source_language, target_locale=locale, nearby_context=history[-payload.context_regions :] if payload.context_regions else [], locked_terms={source: target for source, target in locked_terms.items() if source in region.source_text}))
            source = "machine"
            created += 1
        layout = layout_payload(translated, region.geometry)
        quality = {"fitStatus": layout.get("fitStatus")}
        if existing is None:
            existing = Localization(text_region_id=region.id, locale=locale, text=translated, status="needs-review", source=source, quality_metadata=quality, layout=layout)
            session.add(existing)
        else:
            existing.text = translated
            existing.status = "needs-review"
            existing.source = source
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
    terms = _terms_for(session, chapter.series_id, locale)
    issues: list[QAIssue] = []
    rows = session.execute(select(TextRegion, Page).join(Page, TextRegion.page_id == Page.id).where(Page.chapter_id == chapter_id).order_by(Page.page_index, TextRegion.reading_order)).all()
    for region, page in rows:
        if region.region_type == "sfx":
            continue
        loc = session.scalar(select(Localization).where(Localization.text_region_id == region.id, Localization.locale == locale))
        if loc is None or not loc.text.strip():
            issues.append(QAIssue(code="untranslated", severity="error", page_id=page.id, region_id=region.id, message="Region has no translation"))
            continue
        if region.ocr_confidence is not None and region.ocr_confidence < 0.65:
            issues.append(QAIssue(code="low-ocr-confidence", severity="warning", page_id=page.id, region_id=region.id, localization_id=loc.id, message=f"OCR confidence is {region.ocr_confidence:.2f}"))
        for term in terms:
            if term.locked and term.source in region.source_text and term.target not in loc.text:
                issues.append(QAIssue(code="locked-term", severity="error", page_id=page.id, region_id=region.id, localization_id=loc.id, message=f"Locked term must use '{term.target}'"))
        if loc.layout.get("fitStatus") == "poor-fit":
            issues.append(QAIssue(code="poor-fit", severity="warning", page_id=page.id, region_id=region.id, localization_id=loc.id, message="Translation does not fit the current region at the minimum font size"))
    return QAResult(chapter_id=chapter.id, locale=locale, issues=issues)


@router.post("/localizations/{localization_id}/approve", response_model=ApprovalResult)
def approve_localization(localization_id: int, session: Session = Depends(get_session)) -> ApprovalResult:
    loc = session.get(Localization, localization_id)
    if loc is None:
        raise HTTPException(status_code=404, detail="Localization not found")
    region = session.get(TextRegion, loc.text_region_id)
    assert region is not None
    page = session.get(Page, region.page_id)
    assert page is not None
    chapter = session.get(Chapter, page.chapter_id)
    assert chapter is not None
    loc.status = "approved"
    remembered = bool(region.source_text.strip() and loc.text.strip())
    if remembered:
        approved = session.scalar(select(ApprovedTranslation).where(ApprovedTranslation.series_id == chapter.series_id, ApprovedTranslation.locale == loc.locale, ApprovedTranslation.source_text == region.source_text))
        if approved is None:
            approved = ApprovedTranslation(series_id=chapter.series_id, locale=loc.locale, source_text=region.source_text, target_text=loc.text)
            session.add(approved)
        else:
            approved.target_text = loc.text
    session.commit()
    return ApprovalResult(localization_id=loc.id, status=loc.status, remembered=remembered)
