from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..autofit import layout_payload
from ..db import get_session
from ..models import ApprovedTranslation, Chapter, Localization, Page, Series, TextRegion
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
    assets.delete_trees_best_effort(
        [
            f"original/{series_id}/{chapter_id}",
            f"derived/clean/{chapter_id}",
            f"derived/masks/{chapter_id}",
        ]
    )


def _region_asset_paths(regions: list[TextRegion]) -> list[str | None]:
    return [region.mask_asset for region in regions]


def _renumber_pages_without_collisions(session: Session, pages: list[Page]) -> None:
    if not pages:
        return
    max_index = max(page.page_index for page in pages)
    offset = max_index + len(pages) + 1000
    for position, page in enumerate(pages, start=1):
        page.page_index = offset + position
    session.flush()
    for position, page in enumerate(pages, start=1):
        page.page_index = position


def _format_legacy_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else format(float(value), "g")


def _next_legacy_number(session: Session, series_id: int) -> float:
    """Reserve a negative bridge value so modern chapters do not consume legacy numbers."""
    values = list(session.scalars(select(Chapter.number).where(Chapter.series_id == series_id)))
    negative = [float(value) for value in values if float(value) < 0]
    return min(negative) - 1.0 if negative else -1.0


def _ensure_legacy_number_available(session: Session, series_id: int, number: float, exclude_id: int | None = None) -> None:
    statement = select(Chapter.id).where(Chapter.series_id == series_id, Chapter.number == number)
    if exclude_id is not None:
        statement = statement.where(Chapter.id != exclude_id)
    if session.scalar(statement) is not None:
        raise HTTPException(status_code=409, detail="A chapter with this legacy number already exists")


def _chapter_create_identity(session: Session, series_id: int, payload: ChapterCreate) -> tuple[float, str, float]:
    if payload.number is None and payload.display_number is None and payload.sort_order is None:
        raise HTTPException(status_code=422, detail="Provide display_number/sort_order or legacy number")
    if payload.number is not None:
        legacy_number = float(payload.number)
        _ensure_legacy_number_available(session, series_id, legacy_number)
    else:
        legacy_number = _next_legacy_number(session, series_id)
    sort_order = float(payload.sort_order if payload.sort_order is not None else (payload.number if payload.number is not None else legacy_number))
    display_number = (payload.display_number or _format_legacy_number(payload.number if payload.number is not None else sort_order)).strip()
    if not display_number:
        raise HTTPException(status_code=422, detail="display_number must not be empty")
    return legacy_number, display_number, sort_order


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
    chapters = list(
        session.scalars(
            select(Chapter)
            .where(Chapter.series_id == series_id)
            .order_by(Chapter.sort_order, Chapter.id)
        )
    )
    return SeriesDetail(
        id=series.id,
        title=series.title,
        source_language=series.source_language,
        chapters=[ChapterRead.model_validate(chapter) for chapter in chapters],
    )


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
    session.delete(series)
    session.commit()
    for chapter_id in chapter_ids:
        _delete_chapter_assets(assets, series_id, chapter_id)
    assets.delete_trees_best_effort([f"original/{series_id}"])
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/series/{series_id}/chapters", response_model=ChapterRead, status_code=status.HTTP_201_CREATED)
def create_chapter(series_id: int, payload: ChapterCreate, session: Session = Depends(get_session)) -> Chapter:
    _get_or_404(session, Series, series_id)
    legacy_number, display_number, sort_order = _chapter_create_identity(session, series_id, payload)
    chapter = Chapter(
        series_id=series_id,
        title=payload.title.strip(),
        number=legacy_number,
        display_number=display_number,
        sort_order=sort_order,
    )
    session.add(chapter)
    session.commit()
    session.refresh(chapter)
    return chapter


@router.get("/chapters/{chapter_id}", response_model=ChapterDetail)
def get_chapter(chapter_id: int, session: Session = Depends(get_session)) -> ChapterDetail:
    chapter = _get_or_404(session, Chapter, chapter_id)
    pages = list(session.scalars(select(Page).where(Page.chapter_id == chapter_id).order_by(Page.page_index)))
    return ChapterDetail(
        id=chapter.id,
        series_id=chapter.series_id,
        title=chapter.title,
        number=chapter.number,
        display_number=chapter.display_number,
        sort_order=chapter.sort_order,
        status=chapter.status,
        pages=[PageRead.model_validate(page) for page in pages],
    )


@router.patch("/chapters/{chapter_id}", response_model=ChapterRead)
def update_chapter(chapter_id: int, payload: ChapterUpdate, session: Session = Depends(get_session)) -> Chapter:
    chapter = _get_or_404(session, Chapter, chapter_id)
    changes = payload.model_dump(exclude_unset=True)
    modern_identity = "display_number" in changes or "sort_order" in changes

    if "title" in changes and changes["title"] is not None:
        chapter.title = changes["title"].strip()

    if "number" in changes and changes["number"] is not None:
        legacy_number = float(changes["number"])
        if legacy_number != chapter.number:
            _ensure_legacy_number_available(session, chapter.series_id, legacy_number, chapter.id)
            chapter.number = legacy_number
        if not modern_identity:
            chapter.display_number = _format_legacy_number(legacy_number)
            chapter.sort_order = legacy_number

    if "display_number" in changes and changes["display_number"] is not None:
        label = str(changes["display_number"]).strip()
        if not label:
            raise HTTPException(status_code=422, detail="display_number must not be empty")
        chapter.display_number = label

    if "sort_order" in changes and changes["sort_order"] is not None:
        chapter.sort_order = float(changes["sort_order"])

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
    series_id = chapter.series_id
    session.delete(chapter)
    session.commit()
    _delete_chapter_assets(assets, series_id, chapter_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/chapters/{chapter_id}/import", response_model=ImportResult)
async def import_chapter_pages(chapter_id: int, files: list[UploadFile] = File(...), session: Session = Depends(get_session), assets: AssetStore = Depends(get_asset_store)) -> ImportResult:
    chapter = _get_or_404(session, Chapter, chapter_id)
    existing_page = session.scalar(select(Page.id).where(Page.chapter_id == chapter_id).limit(1))
    if existing_page is not None:
        raise HTTPException(status_code=409, detail="Chapter already has imported pages")
    imported = await unpack_uploads(files)
    created_assets: list[str] = []
    try:
        for page_index, import_page in enumerate(imported, start=1):
            relative = assets.write_original(chapter.series_id, chapter.id, page_index, import_page)
            created_assets.append(relative)
            session.add(Page(chapter_id=chapter.id, page_index=page_index, original_asset=relative, width=import_page.width, height=import_page.height, processing_status="structured"))
        chapter.status = "processing"
        session.commit()
    except Exception:
        session.rollback()
        assets.delete_many_best_effort(created_assets)
        raise
    return ImportResult(chapter_id=chapter.id, pages_imported=len(imported))


@router.put("/pages/{page_id}/asset", response_model=PageRead)
async def replace_page_asset(
    page_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    assets: AssetStore = Depends(get_asset_store),
) -> Page:
    page = _get_or_404(session, Page, page_id)
    chapter = _get_or_404(session, Chapter, page.chapter_id)
    imported = await unpack_uploads([file])
    if len(imported) != 1:
        raise HTTPException(status_code=422, detail="Page replacement requires exactly one image")
    replacement = imported[0]
    regions = list(session.scalars(select(TextRegion).where(TextRegion.page_id == page.id)))
    obsolete: list[str | None] = [page.original_asset, page.clean_asset, *_region_asset_paths(regions)]
    new_asset = assets.write_original(chapter.series_id, chapter.id, page.page_index, replacement)
    try:
        page.original_asset = new_asset
        page.clean_asset = None
        page.width = replacement.width
        page.height = replacement.height
        page.processing_status = "structured"
        session.execute(delete(TextRegion).where(TextRegion.page_id == page.id))
        chapter.status = "processing"
        session.commit()
    except Exception:
        session.rollback()
        assets.delete_many_best_effort([new_asset])
        raise
    assets.delete_many_best_effort(obsolete)
    session.refresh(page)
    return page


@router.delete("/pages/{page_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_page(
    page_id: int,
    session: Session = Depends(get_session),
    assets: AssetStore = Depends(get_asset_store),
) -> Response:
    page = _get_or_404(session, Page, page_id)
    regions = list(session.scalars(select(TextRegion).where(TextRegion.page_id == page.id)))
    obsolete: list[str | None] = [page.original_asset, page.clean_asset, *_region_asset_paths(regions)]
    chapter_id = page.page_id if False else page.chapter_id
    session.delete(page)
    session.flush()
    remaining = list(session.scalars(select(Page).where(Page.chapter_id == chapter_id).order_by(Page.page_index, Page.id)))
    _renumber_pages_without_collisions(session, remaining)
    chapter = _get_or_404(session, Chapter, chapter_id)
    chapter.status = "processing"
    session.commit()
    assets.delete_many_best_effort(obsolete)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/chapters/{chapter_id}/pages/order", response_model=list[PageRead])
def reorder_pages(chapter_id: int, page_ids: list[int], session: Session = Depends(get_session)) -> list[Page]:
    _get_or_404(session, Chapter, chapter_id)
    pages = list(session.scalars(select(Page).where(Page.chapter_id == chapter_id).order_by(Page.page_index, Page.id)))
    current_ids = [page.id for page in pages]
    if len(page_ids) != len(set(page_ids)) or set(page_ids) != set(current_ids):
        raise HTTPException(status_code=422, detail="page_ids must contain every chapter page exactly once")
    by_id = {page.id: page for page in pages}
    ordered = [by_id[page_id] for page_id in page_ids]
    _renumber_pages_without_collisions(session, ordered)
    session.commit()
    return ordered


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
    old_clean = page.clean_asset if payload.region_type in CLEANABLE_REGION_TYPES else None
    if old_clean:
        page.clean_asset = None
        page.processing_status = "analyzed"
    region = TextRegion(page_id=page_id, **payload.model_dump())
    session.add(region)
    session.commit()
    assets.delete_many_best_effort([old_clean])
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
    chapter = _get_or_404(session, Chapter, page.chapter_id)
    changes = payload.model_dump(exclude_unset=True)
    geometry_changed = "geometry" in changes and changes["geometry"] != region.geometry
    type_changed = "region_type" in changes and changes["region_type"] != region.region_type
    source_changed = "source_text" in changes and changes["source_text"] != region.source_text
    old_source = region.source_text
    obsolete: list[str | None] = []

    if geometry_changed or type_changed:
        obsolete.extend([region.mask_asset, page.clean_asset])
        region.mask_asset = None
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
            if old_source.strip():
                approved = session.scalar(
                    select(ApprovedTranslation).where(
                        ApprovedTranslation.series_id == chapter.series_id,
                        ApprovedTranslation.locale == localization.locale,
                        ApprovedTranslation.source_text == old_source,
                    )
                )
                if approved is not None:
                    session.delete(approved)

    session.commit()
    assets.delete_many_best_effort(obsolete)
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
    obsolete: list[str | None] = [region.mask_asset]
    if region.region_type in CLEANABLE_REGION_TYPES and page.clean_asset:
        obsolete.append(page.clean_asset)
        page.clean_asset = None
        page.processing_status = "analyzed"
    session.delete(region)
    session.commit()
    assets.delete_many_best_effort(obsolete)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
