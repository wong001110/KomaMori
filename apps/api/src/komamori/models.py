from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Series(Base):
    __tablename__ = "series"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300), index=True)
    source_language: Mapped[str] = mapped_column(String(32), default="ja")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    chapters: Mapped[list["Chapter"]] = relationship(back_populates="series", cascade="all, delete-orphan")


class Chapter(Base):
    __tablename__ = "chapters"
    __table_args__ = (UniqueConstraint("series_id", "number", name="uq_chapter_series_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    series_id: Mapped[int] = mapped_column(ForeignKey("series.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    number: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default="raw")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    series: Mapped[Series] = relationship(back_populates="chapters")
    pages: Mapped[list["Page"]] = relationship(back_populates="chapter", cascade="all, delete-orphan")


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("chapter_id", "page_index", name="uq_page_chapter_index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    page_index: Mapped[int] = mapped_column(Integer)
    original_asset: Mapped[str] = mapped_column(Text)
    clean_asset: Mapped[str | None] = mapped_column(Text, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processing_status: Mapped[str] = mapped_column(String(32), default="raw")

    chapter: Mapped[Chapter] = relationship(back_populates="pages")
    text_regions: Mapped[list["TextRegion"]] = relationship(back_populates="page", cascade="all, delete-orphan")


class TextRegion(Base):
    __tablename__ = "text_regions"

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    region_type: Mapped[str] = mapped_column(String(32), default="unknown")
    geometry: Mapped[list[list[float]]] = mapped_column(JSON, default=list)
    source_text: Mapped[str] = mapped_column(Text, default="")
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reading_order: Mapped[int] = mapped_column(Integer, default=0)
    mask_asset: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_style: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    page: Mapped[Page] = relationship(back_populates="text_regions")
    localizations: Mapped[list["Localization"]] = relationship(back_populates="text_region", cascade="all, delete-orphan")


class Localization(Base):
    __tablename__ = "localizations"
    __table_args__ = (UniqueConstraint("text_region_id", "locale", name="uq_localization_region_locale"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    text_region_id: Mapped[int] = mapped_column(ForeignKey("text_regions.id", ondelete="CASCADE"), index=True)
    locale: Mapped[str] = mapped_column(String(32), index=True)
    text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    source: Mapped[str] = mapped_column(String(32), default="machine")
    quality_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    layout: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    text_region: Mapped[TextRegion] = relationship(back_populates="localizations")


class LocalizationTerm(Base):
    __tablename__ = "localization_terms"
    __table_args__ = (UniqueConstraint("series_id", "locale", "source", name="uq_term_series_locale_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    series_id: Mapped[int | None] = mapped_column(ForeignKey("series.id", ondelete="CASCADE"), nullable=True, index=True)
    locale: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(String(300))
    target: Mapped[str] = mapped_column(String(300))
    term_type: Mapped[str] = mapped_column(String(32), default="term")
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    locked: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")
