from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Chapter, Localization, Page, TextRegion
from ..quality import blocking_error_count
from ..region_types import TRANSLATABLE_REGION_TYPES
from ..schemas import (
    ChapterLocalizationView,
    LocaleSummary,
    LocalizationRead,
    PageLocalizationView,
    RegionLocalizationView,
)

router = APIRouter(prefix="/api", tags=["workbench"])


def _locale_status(translated: int, approved: int, total: int, *, unknown_regions: int, blocking_errors: int) -> str:
    if total > 0 and translated == total and approved == total and unknown_regions == 0 and blocking_errors == 0:
        return "ready"
    if total > 0 and translated == total and unknown_regions == 0:
        return "review"
    return "in-progress"


@router.get("/chapters/{chapter_id}/locales", response_model=list[LocaleSummary])
def chapter_locales(chapter_id: int, session: Session = Depends(get_session)) -> list[LocaleSummary]:
    chapter = session.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="Chapter not found")

    regions = list(
        session.scalars(
            select(TextRegion)
            .join(Page, TextRegion.page_id == Page.id)
            .where(Page.chapter_id == chapter_id)
        )
    )
    if not regions:
        return []

    unknown_regions = sum(1 for region in regions if region.region_type == "unknown")
    translatable_ids = {
        region.id for region in regions if region.region_type in TRANSLATABLE_REGION_TYPES
    }
    region_ids = [region.id for region in regions]
    localizations = list(
        session.scalars(select(Localization).where(Localization.text_region_id.in_(region_ids)))
    )
    if not localizations:
        return []

    by_locale: dict[str, dict[str, int]] = {}
    for localization in localizations:
        stats = by_locale.setdefault(localization.locale, {"translated": 0, "approved": 0})
        if localization.text_region_id not in translatable_ids:
            continue
        if localization.text.strip():
            stats["translated"] += 1
        if localization.status == "approved" and localization.text.strip():
            stats["approved"] += 1

    total = len(translatable_ids)
    return [
        LocaleSummary(
            locale=locale,
            translated=stats["translated"],
            approved=stats["approved"],
            total_regions=total,
            status=_locale_status(
                stats["translated"],
                stats["approved"],
                total,
                unknown_regions=unknown_regions,
                blocking_errors=blocking_error_count(session, chapter, locale),
            ),
        )
        for locale, stats in sorted(by_locale.items())
    ]


@router.get("/chapters/{chapter_id}/view/{locale}", response_model=ChapterLocalizationView)
def chapter_localization_view(
    chapter_id: int,
    locale: str,
    session: Session = Depends(get_session),
) -> ChapterLocalizationView:
    chapter = session.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="Chapter not found")
    pages = list(session.scalars(select(Page).where(Page.chapter_id == chapter_id).order_by(Page.page_index)))
    page_ids = [page.id for page in pages]
    regions = (
        list(
            session.scalars(
                select(TextRegion)
                .where(TextRegion.page_id.in_(page_ids))
                .order_by(TextRegion.page_id, TextRegion.reading_order, TextRegion.id)
            )
        )
        if page_ids
        else []
    )
    region_ids = [region.id for region in regions]
    localizations = (
        list(
            session.scalars(
                select(Localization).where(
                    Localization.text_region_id.in_(region_ids),
                    Localization.locale == locale,
                )
            )
        )
        if region_ids
        else []
    )
    localization_by_region = {localization.text_region_id: localization for localization in localizations}
    regions_by_page: dict[int, list[TextRegion]] = {}
    for region in regions:
        regions_by_page.setdefault(region.page_id, []).append(region)

    page_views: list[PageLocalizationView] = []
    for page in pages:
        region_views = [
            RegionLocalizationView(
                id=region.id,
                page_id=region.page_id,
                region_type=region.region_type,
                geometry=region.geometry,
                source_text=region.source_text,
                ocr_confidence=region.ocr_confidence,
                reading_order=region.reading_order,
                localization=(
                    LocalizationRead.model_validate(localization_by_region[region.id])
                    if region.id in localization_by_region
                    else None
                ),
            )
            for region in regions_by_page.get(page.id, [])
        ]
        page_views.append(
            PageLocalizationView(
                id=page.id,
                page_index=page.page_index,
                width=page.width,
                height=page.height,
                original_url=f"/api/pages/{page.id}/asset",
                clean_url=f"/api/pages/{page.id}/clean-asset" if page.clean_asset else None,
                regions=region_views,
            )
        )
    return ChapterLocalizationView(
        chapter_id=chapter.id,
        series_id=chapter.series_id,
        title=chapter.title,
        number=chapter.number,
        locale=locale,
        pages=page_views,
    )
