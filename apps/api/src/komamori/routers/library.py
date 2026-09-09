from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..autofit import layout_payload
from ..db import get_session
from ..models import Chapter, Localization, Page, Series, TextRegion
from ..region_types import CLEANABLE_REGION_TYPES
from ..schemas import ChapterCreate, ChapterDetail, ChapterRead, ChapterUpdate, ImportResult, PageRead, SeriesCreate, SeriesDetail, SeriesRead, SeriesUpdate, TextRegionCreate, TextRegionRead, TextRegionUpdate
from ..storage import AssetStore, get_asset_store, unpack_uploads

router = APIRouter(prefix="/api", tags=["library"])


def _get_or_404(session: Session, model: type[Series] | type[Chapter] | type[Page] | type[TextRegion], object_id: int):
    value = session.get(model, object_id)
    if value is None:
        raise HTTPException(status_code=404, detail=f"{model.__name__} not found")
    return value


def _delete_chapter_assets(assets: AssetStore, series_id: int, chapter_id: int) -> None:
    assets.delete_tree(f"original/{series_id}/{chapter_id}")
    assets.delete_tree(f"derived/clean/{chapter_id}")
    assets.delete_tree(f"derived/masks/{chapter_id}")


@router.get("/series", response_model=list[SeriesRead])
def list_series(session: Session = Depends(get_session)) -> list[Series]:
    return list(session.scalars(select(Series).order_by(Series.updated_at.desc())))


@router.post("/series", response_model=SeriesRead, status_code=status.HTTP_201_CREATED)
def create_series(payload: SeriesCreate, session: Session = Depends(get_session)) -> Series:
    series = Series(title=payload.title.strip(), source_language=payload.source_language)
    session.add(series)
    session.commit()
    session.refresh(series)
    return series


@router.get("/series/{series_id}", response_model=SeriesDetail)
def get_series(series_id: int, session: Session = Depends(get_session)) -> SeriesDetail:
    series = _get_or_404(session, Series, series_id)
    chapters = list(session.scalars(select(Chapter).where(Chapter.series_id == series_id).order_by(Chapter.number)))
    return SeriesDetail(id=series.id, title=series.title, source_language=series.source_language, chapters=[ChapterRead.model_validate(chapter) for chapter in chapters])


@router.patch("/series/{series_id}", response_model=SeriesRead)
def update_series(series_id: int, payload: SeriesUpdate, session: Session = Depends(get_session)) -> Series:
    series = _get_or_404(session, Series, series_id)
    changes = payload.model_dump(exclude_unset=True)
    if "title" in changes and changes["title"] is not None:
        changes["title"] = changes["title"].strip()
    for key, value in changes.items():
        if value is not None:
            setattr(series, key, value)
    session.commit()
    session.refresh(series)
    return series


@router.delete("/series/{series_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_series(
    series_id: int,
    session: Session = Depends(get_session),
    assets: AssetStore = Depends(get_asset_store),
) -> Response:
    series = _get_or_404(session, Series, series_id)
    chapter_ids = list(session.scalars(select(Chapter.id).where(Chapter.series_id == series_id)))
    for chapter_id in chapter_ids:
        _delete_chapter_assets(assets, series_id, chapter_id)
    assets.delete_tree(f"original/{series_id}")
    session.delete(series)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/series/{series_id}/chapters", response_model=ChapterRead, status_code=status.HTTP_201_CREATED)
def create_chapter(series_id: int, payload: ChapterCreate, session: Session = Depends(get_session)) -> Chapter:
    _get_or_404(session, Series, series_id)
    existing = session.scalar(select(Chapter).where(Chapter.series_id == series_id, Chapter.number == payload.number))
    if existing:
        raise HTTPException(status_code=409, detail="A chapter with this number already exists")
    chapter = Chapter(series_id=series_id, title=payload.title.strip(), number=payload.number)
    session.add(chapter)
    session.commit()
    session.refresh(chapter)
    return chapter


@router.get("/chapters/{chapter_id}", response_model=ChapterDetail)
def get_chapter(chapter_id: int, session: Session = Depends(get_session)) -> ChapterDetail:
    chapter = _get_or_404(session, Chapter, chapter_id)
    pages = list(session.scalars(select(Page).where(Page.chapter_id == chapter_id).order_by(Page.page_index)))
    return ChapterDetail(id=chapter.id, series_id=chapter.series_id, title=chapter.title, number=chapter.number, status=chapter.status, pages=[PageRead.model_validate(page) for page in pages])


@router.patch("/chapters/{chapter_id}", response_model=ChapterRead)
def update_chapter(chapter_id: int, payload: ChapterUpdate, session: Session = Depends(get_session)) -> Chapter:
    chapter = _get_or_404(session, Chapter, chapter_id)
    changes = payload.model_dump(exclude_unset=True)
    if "number" in changes and changes["number"] is not None and changes["number"] != chapter.number:
        duplicate = session.scalar(
            select(Chapter.id).where(
                Chapter.series_id == chapter.series_id,
                Chapter.number == changes["number"],
                Chapter.id != chapter.id,
            )
        )
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="A chapter with this number already exists")
    if "title" in changes and changes["title"] is not None:
        changes["title"] = changes["title"].strip()
    for key, value in changes.items():
        if value is not None:
            setattr(chapter, key, value)
    session.commit()
    session.refresh(chapter)
    return chapter


@router.delete("/chapters/{chapter_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chapter(
    chapter_id: int,
    session: Session = Depends(get_session),
    assets: AssetStore = Depends(get_asset_store),
) -> Response:
    chapter = _get_or_404(session, Chapter, chapter_id)
    _delete_chapter_assets(assets, chapter.series_id, chapter.id)
    session.delete(chapter)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/chapters/{chapter_id}/import", response_model=ImportResult)
async def import_chapter_pages(chapter_id: int, files: list[UploadFile] = File(...), session: Session = Depends(get_session), assets: AssetStore = Depends(get_asset_store)) -> ImportResult:
    chapter = _get_or_404(session, Chapter, chapter_id)
    existing_page = session.scalar(select(Page.id).where(Page.chapter_id == chapter_id).limit(1))
    if existing_page is not None:
        raise HTTPException(status_code=409, detail="Chapter already has imported pages")
    imported = await unpack_uploads(files)
    for page_index, import_page in enumerate(imported, start=1):
        relative = assets.write_original(chapter.series_id, chapter.id, page_index, import_page)
        session.add(Page(chapter_id=chapter.id, page_index=page_index, original_asset=relative, width=import_page.width, height=import_page.height, processing_status="structured"))
    chapter.status = "processing"
    session.commit()
    return ImportResult(chapter_id=chapter.id, pages_imported=len(imported))


@router.get("/pages/{page_id}/asset")
def page_asset(page_id: int, session: Session = Depends(get_session), assets: AssetStore = Depends(get_asset_store)) -> FileResponse:
    page = _get_or_404(session, Page, page_id)
    return FileResponse(assets.resolve(page.original_asset))


@router.get("/pages/{page_id}/clean-asset")
def clean_page_asset(page_id: int, session: Session = Depends(get_session), assets: AssetStore = Depends(get_asset_store)) -> FileResponse:
    page = _get_or_404(session, Page, page_id)
    if not page.clean_asset:
        raise HTTPException(status_code=404, detail="Clean page has not been generated")
    return FileResponse(assets.resolve(page.clean_asset))


@router.get("/regions/{region_id}/mask-asset")
def region_mask_asset(region_id: int, session: Session = Depends(get_session), assets: AssetStore = Depends(get_asset_store)) -> FileResponse:
    region = _get_or_404(session, TextRegion, region_id)
    if not region.mask_asset:
        raise HTTPException(status_code=404, detail="Text mask has not been generated")
    return FileResponse(assets.resolve(region.mask_asset), media_type="image/png")


@router.get("/pages/{page_id}/regions", response_model=list[TextRegionRead])
def list_regions(page_id: int, session: Session = Depends(get_session)) -> list[TextRegion]:
    _get_or_404(session, Page, page_id)
    return list(session.scalars(select(TextRegion).where(TextRegion.page_id == page_id).order_by(TextRegion.reading_order, TextRegion.id)))


@router.post("/pages/{page_id}/regions", response_model=TextRegionRead, status_code=status.HTTP_201_CREATED)
def create_region(
    page_id: int,
    payload: TextRegionCreate,
    session: Session = Depends(get_session),
    assets: AssetStore = Depends(get_asset_store),
) -> TextRegion:
    page = _get_or_404(session, Page, page_id)
    if payload.region_type in CLEANABLE_REGION_TYPES and page.clean_asset:
        assets.delete(page.clean_asset)
        page.clean_asset = None
        page.processing_status = "analyzed"
    region = TextRegion(page_id=page_id, **payload.model_dump())
    session.add(region)
    session.commit()
    session.refresh(region)
    return region


@router.patch("/regions/{region_id}", response_model=TextRegionRead)
def update_region(
    region_id: int,
    payload: TextRegionUpdate,
    session: Session = Depends(get_session),
    assets: AssetStore = Depends(get_asset_store),
) -> TextRegion:
    region = _get_or_404(session, TextRegion, region_id)
    page = _get_or_404(session, Page, region.page_id)
    changes = payload.model_dump(exclude_unset=True)
    geometry_changed = "geometry" in changes and changes["geometry"] != region.geometry
    type_changed = "region_type" in changes and changes["region_type"] != region.region_type
    source_changed = "source_text" in changes and changes["source_text"] != region.source_text

    if geometry_changed or type_changed:
        assets.delete(region.mask_asset)
        region.mask_asset = None
        assets.delete(page.clean_asset)
        page.clean_asset = None
        page.processing_status = "analyzed"

    for key, value in changes.items():
        setattr(region, key, value)

    localizations = list(session.scalars(select(Localization).where(Localization.text_region_id == region.id)))
    if geometry_changed:
        for localization in localizations:
            localization.layout = layout_payload(localization.text, region.geometry) if localization.text else {}
            localization.quality_metadata = {
                **(localization.quality_metadata or {}),
                "fitStatus": localization.layout.get("fitStatus") if localization.layout else None,
            }
    if source_changed:
        for localization in localizations:
            localization.status = "needs-review"

    session.commit()
    session.refresh(region)
    return region


@router.delete("/regions/{region_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_region(
    region_id: int,
    session: Session = Depends(get_session),
    assets: AssetStore = Depends(get_asset_store),
) -> Response:
    region = _get_or_404(session, TextRegion, region_id)
    page = _get_or_404(session, Page, region.page_id)
    assets.delete(region.mask_asset)
    if region.region_type in CLEANABLE_REGION_TYPES and page.clean_asset:
        assets.delete(page.clean_asset)
        page.clean_asset = None
        page.processing_status = "analyzed"
    session.delete(region)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
