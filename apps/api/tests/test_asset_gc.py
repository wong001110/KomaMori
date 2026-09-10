from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import komamori.asset_gc as asset_gc
from komamori.asset_gc import audit_assets, referenced_assets
from komamori.db import Base
from komamori.models import Chapter, Page, Series, TextRegion
from komamori.storage import AssetStore


def _session(tmp_path: Path) -> tuple[Session, AssetStore]:
    engine = create_engine(f"sqlite:///{tmp_path / 'gc.db'}")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    store = AssetStore(tmp_path / "assets")
    return session, store


def _write(store: AssetStore, relative: str, content: bytes = b"x") -> Path:
    target = store.writable_path(relative)
    target.write_bytes(content)
    return target


def test_asset_audit_reports_referenced_missing_and_orphans_and_dry_run_is_default(tmp_path: Path) -> None:
    session, store = _session(tmp_path)
    try:
        series = Series(title="GC", source_language="ja")
        session.add(series)
        session.flush()
        chapter = Chapter(series_id=series.id, title="One", number=1, display_number="1", sort_order=1)
        session.add(chapter)
        session.flush()
        page = Page(
            chapter_id=chapter.id,
            page_index=1,
            original_asset="original/ref.png",
            clean_asset="derived/clean/missing.png",
            processing_status="cleaned",
        )
        session.add(page)
        session.flush()
        region = TextRegion(
            page_id=page.id,
            region_type="dialogue",
            geometry=[[0, 0], [1, 0], [1, 1], [0, 1]],
            source_text="x",
            mask_asset="derived/masks/ref.png",
        )
        session.add(region)
        session.commit()

        original = _write(store, "original/ref.png")
        mask = _write(store, "derived/masks/ref.png")
        orphan = _write(store, "derived/clean/orphan.png")

        report = audit_assets(session, store)
        assert report.referenced == ["derived/clean/missing.png", "derived/masks/ref.png", "original/ref.png"]
        assert report.missing_references == ["derived/clean/missing.png"]
        assert report.orphan_files == ["derived/clean/orphan.png"]
        assert report.deleted == []
        assert original.exists() and mask.exists() and orphan.exists()
    finally:
        session.close()


def test_delete_mode_only_removes_old_orphans_and_preserves_referenced_and_recent_files(tmp_path: Path) -> None:
    session, store = _session(tmp_path)
    try:
        series = Series(title="GC", source_language="ja")
        session.add(series)
        session.flush()
        chapter = Chapter(series_id=series.id, title="One", number=1, display_number="1", sort_order=1)
        session.add(chapter)
        session.flush()
        page = Page(chapter_id=chapter.id, page_index=1, original_asset="original/ref.png", processing_status="structured")
        session.add(page)
        session.commit()

        referenced = _write(store, "original/ref.png")
        old_orphan = _write(store, "derived/old-orphan.png")
        recent_orphan = _write(store, "derived/recent-orphan.png")
        now = 2_000_000.0
        os.utime(old_orphan, (now - 7200, now - 7200))
        os.utime(recent_orphan, (now - 10, now - 10))

        report = audit_assets(session, store, delete=True, grace_seconds=3600, now_timestamp=now)
        assert report.deleted == ["derived/old-orphan.png"]
        assert report.skipped_recent_orphans == ["derived/recent-orphan.png"]
        assert referenced.exists()
        assert not old_orphan.exists()
        assert recent_orphan.exists()
    finally:
        session.close()


def test_gc_rechecks_references_in_fresh_transactions_before_unlink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'concurrent.db'}")
    Base.metadata.create_all(engine)
    store = AssetStore(tmp_path / "assets")
    session = Session(engine, expire_on_commit=False)
    other = Session(engine, expire_on_commit=False)
    try:
        series = Series(title="GC race", source_language="ja")
        session.add(series)
        session.flush()
        chapter = Chapter(series_id=series.id, title="One", number=1, display_number="1", sort_order=1)
        session.add(chapter)
        session.commit()
        chapter_id = chapter.id

        candidate = _write(store, "original/just-written.png")
        os.utime(candidate, (1_000_000.0, 1_000_000.0))

        original_existing_assets = asset_gc.existing_assets
        injected = False

        def scan_then_commit_reference(current_store: AssetStore) -> set[str]:
            nonlocal injected
            result = original_existing_assets(current_store)
            if not injected:
                injected = True
                other.add(
                    Page(
                        chapter_id=chapter_id,
                        page_index=1,
                        original_asset="original/just-written.png",
                        processing_status="structured",
                    )
                )
                other.commit()
            return result

        monkeypatch.setattr(asset_gc, "existing_assets", scan_then_commit_reference)
        report = audit_assets(session, store, delete=True, grace_seconds=0, now_timestamp=2_000_000.0)
        assert candidate.exists()
        assert report.deleted == []
        assert "original/just-written.png" in referenced_assets(session, store)
    finally:
        other.close()
        session.close()


def test_gc_refuses_pending_session_writes(tmp_path: Path) -> None:
    session, store = _session(tmp_path)
    try:
        session.add(Series(title="not committed", source_language="ja"))
        with pytest.raises(ValueError, match="no pending writes"):
            audit_assets(session, store, delete=True)
    finally:
        session.close()


def test_gc_fails_closed_on_escaped_durable_reference(tmp_path: Path) -> None:
    session, store = _session(tmp_path)
    try:
        series = Series(title="GC", source_language="ja")
        session.add(series)
        session.flush()
        chapter = Chapter(series_id=series.id, title="One", number=1, display_number="1", sort_order=1)
        session.add(chapter)
        session.flush()
        session.add(Page(chapter_id=chapter.id, page_index=1, original_asset="../escape.png", processing_status="structured"))
        session.commit()
        with pytest.raises(ValueError, match="escapes root"):
            referenced_assets(session, store)
    finally:
        session.close()


def test_gc_refuses_symlink_entries_inside_asset_root(tmp_path: Path) -> None:
    session, store = _session(tmp_path)
    external = tmp_path / "outside.txt"
    external.write_text("outside", encoding="utf-8")
    link = store.root / "link.txt"
    try:
        link.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")
    try:
        with pytest.raises(ValueError, match="refuses symlink"):
            audit_assets(session, store)
        assert external.read_text(encoding="utf-8") == "outside"
    finally:
        session.close()
