from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class HealthResponse(BaseModel):
    status: str
    service: str


class SeriesCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    source_language: str = Field(default="ja", min_length=2, max_length=32)


class SeriesRead(ORMModel):
    id: int
    title: str
    source_language: str


class ChapterCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    number: float


class ChapterRead(ORMModel):
    id: int
    series_id: int
    title: str
    number: float
    status: str


class PageRead(ORMModel):
    id: int
    chapter_id: int
    page_index: int
    original_asset: str
    clean_asset: str | None
    width: int | None
    height: int | None
    processing_status: str


class ChapterDetail(ChapterRead):
    pages: list[PageRead]


class SeriesDetail(SeriesRead):
    chapters: list[ChapterRead]


RegionType = Literal["dialogue", "thought", "narration", "caption", "sign", "sfx", "unknown"]


class TextRegionCreate(BaseModel):
    region_type: RegionType = "unknown"
    geometry: list[list[float]] = Field(default_factory=list)
    source_text: str = ""
    ocr_confidence: float | None = Field(default=None, ge=0, le=1)
    reading_order: int = Field(default=0, ge=0)
    source_style: dict[str, Any] = Field(default_factory=dict)


class TextRegionUpdate(BaseModel):
    region_type: RegionType | None = None
    geometry: list[list[float]] | None = None
    source_text: str | None = None
    ocr_confidence: float | None = Field(default=None, ge=0, le=1)
    reading_order: int | None = Field(default=None, ge=0)
    source_style: dict[str, Any] | None = None


class TextRegionRead(ORMModel):
    id: int
    page_id: int
    region_type: str
    geometry: list[list[float]]
    source_text: str
    ocr_confidence: float | None
    reading_order: int
    mask_asset: str | None
    source_style: dict[str, Any]


class ImportResult(BaseModel):
    chapter_id: int
    pages_imported: int
