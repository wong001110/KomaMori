from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Page, TextRegion
from ..processing import OCRProvider, analyze_page, generate_clean_page, get_ocr_provider
from ..schemas import AnalyzePageResult, CleanPageResult
from ..storage import AssetStore, get_asset_store

router = APIRouter(prefix="/api", tags=["processing"])


@router.post("/pages/{page_id}/analyze", response_model=AnalyzePageResult)
def analyze_page_endpoint(
    page_id: int,
    replace: bool = Query(default=False),
    session: Session = Depends(get_session),
    assets: AssetStore = Depends(get_asset_store),
    ocr: OCRProvider = Depends(get_ocr_provider),
) -> AnalyzePageResult:
    page = session.get(Page, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")
    existing = list(session.scalars(select(TextRegion).where(TextRegion.page_id == page_id)))
    if existing and not replace:
        raise HTTPException(status_code=409, detail="Page already has text regions; use replace=true to re-analyze")
    if existing:
        session.execute(delete(TextRegion).where(TextRegion.page_id == page_id))
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
    session.commit()
    return AnalyzePageResult(page_id=page.id, regions_created=len(results))


@router.post("/pages/{page_id}/clean", response_model=CleanPageResult)
def clean_page_endpoint(
    page_id: int,
    session: Session = Depends(get_session),
    assets: AssetStore = Depends(get_asset_store),
) -> CleanPageResult:
    page = session.get(Page, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")
    regions = list(session.scalars(select(TextRegion).where(TextRegion.page_id == page_id, TextRegion.region_type != "sfx")))
    if not regions:
        raise HTTPException(status_code=409, detail="Page has no cleanable text regions")

    relative = f"derived/clean/{page.chapter_id}/{page.id}.png"
    generate_clean_page(
        assets.resolve(page.original_asset),
        [region.geometry for region in regions],
        assets.writable_path(relative),
    )
    page.clean_asset = relative
    page.processing_status = "cleaned"
    session.commit()
    return CleanPageResult(page_id=page.id, clean_asset=relative)
