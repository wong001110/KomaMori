from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Chapter, Page, TextRegion
from ..processing import OCRProvider, analyze_page, generate_clean_page, get_ocr_provider
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
) -> tuple[int, bool]:
    existing = list(session.scalars(select(TextRegion).where(TextRegion.page_id == page.id)))
    if existing and not replace:
        return 0, True
    if existing:
        session.execute(delete(TextRegion).where(TextRegion.page_id == page.id))
        session.flush()

    results = analyze_page(assets.resolve(page.original_asset), ocr)
    for index, result in enumerate(results, start=1):
        session.add(
            TextRegion(
                page_id=page.id,
                region_type="dialogue",
                geometry=result.geometry,
                source_text=result.text,
                ocr_confidence=result.confidence,
                reading_order=index,
            )
        )
    page.processing_status = "analyzed"
    return len(results), False


def _clean_page(page: Page, *, session: Session, assets: AssetStore) -> bool:
    regions = list(
        session.scalars(
            select(TextRegion).where(TextRegion.page_id == page.id, TextRegion.region_type != "sfx")
        )
    )
    if not regions:
        return False

    relative = f"derived/clean/{page.chapter_id}/{page.id}.png"
    generate_clean_page(
        assets.resolve(page.original_asset),
        [region.geometry for region in regions],
        assets.writable_path(relative),
    )
    page.clean_asset = relative
    page.processing_status = "cleaned"
    return True


@router.post("/pages/{page_id}/analyze", response_model=AnalyzePageResult)
def analyze_page_endpoint(
    page_id: int,
    replace: bool = Query(default=False),
    session: Session = Depends(get_session),
    assets: AssetStore = Depends(get_asset_store),
    ocr: OCRProvider = Depends(get_ocr_provider),
) -> AnalyzePageResult:
    page = _page_or_404(session, page_id)
    created, skipped = _analyze_page(page, replace=replace, session=session, assets=assets, ocr=ocr)
    if skipped:
        raise HTTPException(status_code=409, detail="Page already has text regions; use replace=true to re-analyze")
    session.commit()
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
    for page in pages:
        created, was_skipped = _analyze_page(page, replace=replace, session=session, assets=assets, ocr=ocr)
        if was_skipped:
            skipped += 1
        else:
            analyzed += 1
            regions_created += created
    chapter.status = "processing"
    session.commit()
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
    if not _clean_page(page, session=session, assets=assets):
        raise HTTPException(status_code=409, detail="Page has no cleanable text regions")
    session.commit()
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
    for page in pages:
        if _clean_page(page, session=session, assets=assets):
            cleaned += 1
        else:
            skipped += 1
    session.commit()
    return BatchCleanResult(chapter_id=chapter_id, pages_cleaned=cleaned, pages_skipped=skipped)
