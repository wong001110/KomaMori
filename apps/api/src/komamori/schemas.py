from __future__ import annotations

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
