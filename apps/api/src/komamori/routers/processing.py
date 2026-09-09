from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Chapter, Page, TextRegion
from ..processing import OCRProvider, analyze_page, generate_clean_page, generate_text_mask, get_ocr_provider
from ..region_types import CLEANABLE_REGION_TYPES
from ..schemas import AnalyzePageResult, BatchAnalyzeResult, BatchCleanResult, CleanPageResult
from ..storage import AssetStore, get_asset_store

router = APIRouter(prefix="/api", tags=["processing"])


def _page_or_404(session: Session, page_id: int) -> Page:
    page = session.get(Page, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return page


def _analyze_page(
    page: Page,
    *,
    replace: bool,
    session: Session,
    assets: AssetStore,
    ocr: OCRProvider,
) -> tuple[int, bool, list[str | None]]:
    existing = list(session.scalars(select(TextRegion).where(TextRegion.page_id == page.id)))
    if existing and not replace:
        return 0, True, []

    # OCR is allowed to fail before any durable/destructive state is changed.
    results = analyze_page(assets.resolve(page.original_asset), ocr)
    obsolete: list[str | None] = []
    if existing:
        obsolete.append(page.clean_asset)
        obsolete.extend(region.mask_asset for region in existing)
        page.clean_asset = None
        page.processing_status = "structured"
        session.execute(delete(TextRegion).where(TextRegion.page_id == page.id))
        session.flush()

    for index, result in enumerate(results, start=1):
        session.add(
            TextRegion(
                page_id=page.id,
                region_type="unknown",
                geometry=result.geometry,
                source_text=result.text,
                ocr_confidence=result.confidence,
                reading_order=index,
            )
        )
    page.processing_status = "analyzed"
    return len(results), False, obsolete


def _mask_for_region(page: Page, region: TextRegion, assets: AssetStore) -> tuple[str, str | None]:
    if region.mask_asset and assets.exists(region.mask_asset):
        return region.mask_asset, None
    relative, target = assets.unique_writable_path(
        f"derived/masks/{page.chapter_id}/{page.id}/{region.id}",
        suffix=".png",
    )
    try:
        generate_text_mask(assets.resolve(page.original_asset), region.geometry, target)
    except Exception:
        assets.delete_many_best_effort([relative])
        raise
    region.mask_asset = relative
    return relative, relative


def _clean_page(page: Page, *, session: Session, assets: AssetStore) -> tuple[bool, list[str | None], list[str]]:
    regions = list(
        session.scalars(
            select(TextRegion).where(
                TextRegion.page_id == page.id,
                TextRegion.region_type.in_(tuple(CLEANABLE_REGION_TYPES)),
            )
        )
    )
    if not regions:
        return False, [], []

    created: list[str] = []
    try:
        masks: list[str] = []
        for region in regions:
            mask, new_mask = _mask_for_region(page, region, assets)
            masks.append(mask)
            if new_mask:
                created.append(new_mask)

        old_clean = page.clean_asset
        clean_relative, clean_target = assets.unique_writable_path(
            f"derived/clean/{page.chapter_id}/{page.id}",
            suffix=".png",
        )
        # Track the path before invoking the writer so even a partial file from a
        # failing generator is known to the cleanup path.
        created.append(clean_relative)
        generate_clean_page(
            assets.resolve(page.original_asset),
            [assets.resolve(mask) for mask in masks],
            clean_target,
        )
        page.clean_asset = clean_relative
        page.processing_status = "cleaned"
        return True, [old_clean], created
    except Exception:
        assets.delete_many_best_effort(created)
        raise


@router.post("/pages/{page_id}/analyze", response_model=AnalyzePageResult)
def analyze_page_endpoint(
    page_id: int,
    replace: bool = Query(default=False),
    session: Session = Depends(get_session),
    assets: AssetStore = Depends(get_asset_store),
    ocr: OCRProvider = Depends(get_ocr_provider),
) -> AnalyzePageResult:
    page = _page_or_404(session, page_id)
    created, skipped, obsolete = _analyze_page(page, replace=replace, session=session, assets=assets, ocr=ocr)
    if skipped:
        raise HTTPException(status_code=409, detail="Page already has text regions; use replace=true to re-analyze")
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
    assets.delete_many_best_effort(obsolete)
    return AnalyzePageResult(page_id=page.id, regions_created=created)


@router.post("/chapters/{chapter_id}/analyze", response_model=BatchAnalyzeResult)
def analyze_chapter_endpoint(
    chapter_id: int,
    replace: bool = Query(default=False),
    session: Session = Depends(get_session),
    assets: AssetStore = Depends(get_asset_store),
    ocr: OCRProvider = Depends(get_ocr_provider),
) -> BatchAnalyzeResult:
    chapter = session.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="Chapter not found")
    pages = list(session.scalars(select(Page).where(Page.chapter_id == chapter_id).order_by(Page.page_index)))
    analyzed = skipped = regions_created = 0
    obsolete: list[str | None] = []
    for page in pages:
        created, was_skipped, page_obsolete = _analyze_page(page, replace=replace, session=session, assets=assets, ocr=ocr)
        obsolete.extend(page_obsolete)
        if was_skipped:
            skipped += 1
        else:
            analyzed += 1
            regions_created += created
    chapter.status = "processing"
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
    assets.delete_many_best_effort(obsolete)
    return BatchAnalyzeResult(
        chapter_id=chapter_id,
        pages_analyzed=analyzed,
        pages_skipped=skipped,
        regions_created=regions_created,
    )


@router.post("/pages/{page_id}/clean", response_model=CleanPageResult)
def clean_page_endpoint(
    page_id: int,
    session: Session = Depends(get_session),
    assets: AssetStore = Depends(get_asset_store),
) -> CleanPageResult:
    page = _page_or_404(session, page_id)
    cleaned, obsolete, created = _clean_page(page, session=session, assets=assets)
    if not cleaned:
        raise HTTPException(status_code=409, detail="Page has no explicitly cleanable text regions")
    try:
        session.commit()
    except Exception:
        session.rollback()
        assets.delete_many_best_effort(created)
        raise
    assets.delete_many_best_effort(obsolete)
    assert page.clean_asset is not None
    return CleanPageResult(page_id=page.id, clean_asset=page.clean_asset)


@router.post("/chapters/{chapter_id}/clean", response_model=BatchCleanResult)
def clean_chapter_endpoint(
    chapter_id: int,
    session: Session = Depends(get_session),
    assets: AssetStore = Depends(get_asset_store),
) -> BatchCleanResult:
    chapter = session.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="Chapter not found")
    pages = list(session.scalars(select(Page).where(Page.chapter_id == chapter_id).order_by(Page.page_index)))
    cleaned = skipped = 0
    obsolete: list[str | None] = []
    created: list[str] = []
    try:
        for page in pages:
            did_clean, page_obsolete, page_created = _clean_page(page, session=session, assets=assets)
            obsolete.extend(page_obsolete)
            created.extend(page_created)
            if did_clean:
                cleaned += 1
            else:
                skipped += 1
        session.commit()
    except Exception:
        session.rollback()
        assets.delete_many_best_effort(created)
        raise
    assets.delete_many_best_effort(obsolete)
    return BatchCleanResult(chapter_id=chapter_id, pages_cleaned=cleaned, pages_skipped=skipped)
