from __future__ import annotations

import io
import sqlite3
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session as SASession

from komamori import storage
from komamori.db import configure_sqlite_connection
from komamori.main import app
from komamori.translation import TranslationRequest, get_translation_provider
import komamori.routers.processing as processing_router


def png(width: int = 80, height: int = 100, shade: int = 255) -> bytes:
    image = Image.new("RGB", (width, height), (shade, shade, shade))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def setup_chapter(client: TestClient, *, pages: int = 1, title: str = "P11") -> tuple[int, int, list[dict]]:
    series = client.post("/api/series", json={"title": title, "source_language": "ja"}).json()
    chapter = client.post(
        f"/api/series/{series['id']}/chapters",
        json={"title": "Chapter", "number": 1},
    ).json()
    files = [
        ("files", (f"{index:03d}.png", png(shade=255 - index), "image/png"))
        for index in range(1, pages + 1)
    ]
    response = client.post(f"/api/chapters/{chapter['id']}/import", files=files)
    assert response.status_code == 200
    detail = client.get(f"/api/chapters/{chapter['id']}").json()
    return series["id"], chapter["id"], detail["pages"]


def add_dialogue(client: TestClient, page_id: int, source: str = "こんにちは", order: int = 1) -> dict:
    response = client.post(
        f"/api/pages/{page_id}/regions",
        json={
            "region_type": "dialogue",
            "geometry": [[10, 10], [60, 10], [60, 50], [10, 50]],
            "source_text": source,
            "reading_order": order,
        },
    )
    assert response.status_code == 201
    return response.json()


def localize_and_approve(client: TestClient, region_id: int, text: str, locale: str = "en") -> dict:
    loc = client.put(
        f"/api/regions/{region_id}/localizations/{locale}",
        json={"text": text, "status": "needs-review"},
    ).json()
    approved = client.post(f"/api/localizations/{loc['id']}/approve")
    assert approved.status_code == 200
    return loc


def locale_status(client: TestClient, chapter_id: int, locale: str = "en") -> str:
    rows = client.get(f"/api/chapters/{chapter_id}/locales").json()
    return next(item["status"] for item in rows if item["locale"] == locale)


def test_failed_region_and_chapter_commit_keep_referenced_assets(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, chapter_id, pages = setup_chapter(client, title="Commit safety")
    page_id = pages[0]["id"]
    region = add_dialogue(client, page_id)
    assert client.post(f"/api/pages/{page_id}/clean").status_code == 200

    page_before = client.get(f"/api/chapters/{chapter_id}").json()["pages"][0]
    region_before = client.get(f"/api/pages/{page_id}/regions").json()[0]
    clean_path = tmp_path / "assets" / page_before["clean_asset"]
    mask_path = tmp_path / "assets" / region_before["mask_asset"]
    original_path = tmp_path / "assets" / page_before["original_asset"]
    assert clean_path.is_file() and mask_path.is_file() and original_path.is_file()

    with monkeypatch.context() as patcher:
        patcher.setattr(SASession, "commit", lambda self: (_ for _ in ()).throw(RuntimeError("commit failed")))
        with pytest.raises(RuntimeError, match="commit failed"):
            client.patch(f"/api/regions/{region['id']}", json={"geometry": [[15, 15], [65, 15], [65, 55], [15, 55]]})

    assert clean_path.is_file() and mask_path.is_file()
    region_after = client.get(f"/api/pages/{page_id}/regions").json()[0]
    assert region_after["geometry"] == region_before["geometry"]
    assert region_after["mask_asset"] == region_before["mask_asset"]

    with monkeypatch.context() as patcher:
        patcher.setattr(SASession, "commit", lambda self: (_ for _ in ()).throw(RuntimeError("commit failed")))
        with pytest.raises(RuntimeError, match="commit failed"):
            client.delete(f"/api/chapters/{chapter_id}")

    assert original_path.is_file()
    assert client.get(f"/api/chapters/{chapter_id}").status_code == 200


def test_failed_reanalysis_preserves_previous_regions_and_derived_assets(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, chapter_id, pages = setup_chapter(client, title="Analyze rollback")
    page_id = pages[0]["id"]
    region = add_dialogue(client, page_id)
    assert client.post(f"/api/pages/{page_id}/clean").status_code == 200
    page_before = client.get(f"/api/chapters/{chapter_id}").json()["pages"][0]
    region_before = client.get(f"/api/pages/{page_id}/regions").json()[0]

    def fail_analysis(*_args, **_kwargs):
        raise RuntimeError("OCR failed")

    monkeypatch.setattr(processing_router, "analyze_page", fail_analysis)
    with pytest.raises(RuntimeError, match="OCR failed"):
        client.post(f"/api/pages/{page_id}/analyze?replace=true")

    assert client.get(f"/api/pages/{page_id}/regions").json()[0]["id"] == region["id"]
    assert (tmp_path / "assets" / page_before["clean_asset"]).is_file()
    assert (tmp_path / "assets" / region_before["mask_asset"]).is_file()


def test_clean_assets_use_unique_paths_and_cleanup_old_versions(client: TestClient, tmp_path: Path) -> None:
    _, chapter_id, pages = setup_chapter(client, title="Unique clean")
    page_id = pages[0]["id"]
    add_dialogue(client, page_id)
    first = client.post(f"/api/pages/{page_id}/clean").json()["clean_asset"]
    first_path = tmp_path / "assets" / first
    assert first_path.is_file()

    second = client.post(f"/api/pages/{page_id}/clean").json()["clean_asset"]
    assert second != first
    assert (tmp_path / "assets" / second).is_file()
    assert not first_path.exists()


def test_page_replace_delete_and_reorder_recover_without_stale_page_state(client: TestClient, tmp_path: Path) -> None:
    _, chapter_id, pages = setup_chapter(client, pages=3, title="Page recovery")
    middle = pages[1]
    region = add_dialogue(client, middle["id"], source="old page")
    localize_and_approve(client, region["id"], "Old page")
    assert client.post(f"/api/pages/{middle['id']}/clean").status_code == 200
    before = client.get(f"/api/chapters/{chapter_id}").json()["pages"][1]
    old_original = tmp_path / "assets" / before["original_asset"]
    old_clean = tmp_path / "assets" / before["clean_asset"]

    response = client.put(
        f"/api/pages/{middle['id']}/asset",
        files={"file": ("replacement.png", png(90, 120, 200), "image/png")},
    )
    assert response.status_code == 200
    replaced = response.json()
    assert replaced["original_asset"] != before["original_asset"]
    assert replaced["clean_asset"] is None
    assert replaced["processing_status"] == "structured"
    assert client.get(f"/api/pages/{middle['id']}/regions").json() == []
    assert not old_original.exists() and not old_clean.exists()

    detail = client.get(f"/api/chapters/{chapter_id}").json()
    ids = [page["id"] for page in detail["pages"]]
    reordered_ids = [ids[2], ids[0], ids[1]]
    reordered = client.put(f"/api/chapters/{chapter_id}/pages/order", json=reordered_ids)
    assert reordered.status_code == 200
    assert [page["id"] for page in reordered.json()] == reordered_ids
    assert [page["page_index"] for page in reordered.json()] == [1, 2, 3]
    assert client.put(f"/api/chapters/{chapter_id}/pages/order", json=[reordered_ids[0], reordered_ids[0], reordered_ids[2]]).status_code == 422

    deleted_id = reordered_ids[1]
    assert client.delete(f"/api/pages/{deleted_id}").status_code == 204
    remaining = client.get(f"/api/chapters/{chapter_id}").json()["pages"]
    assert [page["page_index"] for page in remaining] == [1, 2]
    assert deleted_id not in [page["id"] for page in remaining]


def test_unknown_blocks_ready_sfx_does_not_and_empty_approval_is_rejected(client: TestClient) -> None:
    _, chapter_id, pages = setup_chapter(client, title="Ready semantics")
    page_id = pages[0]["id"]
    dialogue = add_dialogue(client, page_id)
    localize_and_approve(client, dialogue["id"], "Hello")
    assert locale_status(client, chapter_id) == "ready"

    unknown = client.post(
        f"/api/pages/{page_id}/regions",
        json={
            "region_type": "unknown",
            "geometry": [[1, 1], [8, 1], [8, 8], [1, 8]],
            "source_text": "unresolved",
            "reading_order": 2,
        },
    ).json()
    assert locale_status(client, chapter_id) == "in-progress"
    assert client.patch(f"/api/regions/{unknown['id']}", json={"region_type": "sfx"}).status_code == 200
    assert locale_status(client, chapter_id) == "ready"

    empty_region = add_dialogue(client, page_id, source="empty approval", order=3)
    empty = client.put(
        f"/api/regions/{empty_region['id']}/localizations/en",
        json={"text": "", "status": "needs-review"},
    ).json()
    assert client.post(f"/api/localizations/{empty['id']}/approve").status_code == 409


def test_blocking_qa_prevents_ready_while_warning_alone_does_not(client: TestClient) -> None:
    series_id, chapter_id, pages = setup_chapter(client, title="QA readiness")
    page_id = pages[0]["id"]
    assert client.post(
        f"/api/series/{series_id}/terms",
        json={"locale": "en", "source": "勇者", "target": "Champion", "aliases": [], "locked": True},
    ).status_code == 201
    region = client.post(
        f"/api/pages/{page_id}/regions",
        json={
            "region_type": "dialogue",
            "geometry": [[10, 10], [60, 10], [60, 50], [10, 50]],
            "source_text": "勇者です",
            "ocr_confidence": 0.5,
            "reading_order": 1,
        },
    ).json()
    localize_and_approve(client, region["id"], "Hero")
    assert locale_status(client, chapter_id) == "review"
    qa = client.get(f"/api/chapters/{chapter_id}/qa/en").json()["issues"]
    assert any(issue["code"] == "locked-term" and issue["severity"] == "error" for issue in qa)

    client.put(
        f"/api/regions/{region['id']}/localizations/en",
        json={"text": "Champion", "status": "needs-review"},
    )
    loc = client.get(f"/api/regions/{region['id']}/localizations").json()[0]
    assert client.post(f"/api/localizations/{loc['id']}/approve").status_code == 200
    assert locale_status(client, chapter_id) == "ready"
    qa = client.get(f"/api/chapters/{chapter_id}/qa/en").json()["issues"]
    assert any(issue["code"] == "low-ocr-confidence" and issue["severity"] == "warning" for issue in qa)
    assert not any(issue["severity"] == "error" for issue in qa)


class FakeTranslationProvider:
    def translate(self, request: TranslationRequest) -> str:
        return f"machine:{request.source_text}"


def test_terminology_policy_change_demotes_approval_and_clears_reuse_memory(client: TestClient) -> None:
    series_id, chapter_id, pages = setup_chapter(client, title="Policy invalidation")
    page_id = pages[0]["id"]
    assert client.post(
        f"/api/series/{series_id}/terms",
        json={"locale": "en", "source": "勇者", "target": "Hero", "aliases": [], "locked": True},
    ).status_code == 201
    first = add_dialogue(client, page_id, source="勇者")
    localize_and_approve(client, first["id"], "Hero")

    updated_term = client.post(
        f"/api/series/{series_id}/terms",
        json={"locale": "en", "source": "勇者", "target": "Champion", "aliases": ["ゆうしゃ"], "locked": True},
    )
    assert updated_term.status_code == 201
    first_loc = client.get(f"/api/regions/{first['id']}/localizations").json()[0]
    assert first_loc["status"] == "needs-review"

    second = add_dialogue(client, page_id, source="勇者", order=2)
    app.dependency_overrides[get_translation_provider] = lambda: FakeTranslationProvider()
    try:
        result = client.post(f"/api/chapters/{chapter_id}/localize/en", json={"overwrite": False, "context_regions": 0})
    finally:
        app.dependency_overrides.pop(get_translation_provider, None)
    assert result.status_code == 200
    view = client.get(f"/api/chapters/{chapter_id}/view/en").json()
    second_view = next(region for region in view["pages"][0]["regions"] if region["id"] == second["id"])
    assert second_view["localization"]["source"] == "machine"
    assert second_view["localization"]["text"] == "machine:勇者"


def test_upload_preflight_limits_count_uncompressed_size_and_pixels(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _, chapter_id, _ = setup_chapter(client, title="Upload seed")
    # Use a fresh empty chapter because imports are intentionally one-shot.
    series = client.get("/api/series").json()[0]
    empty = client.post(f"/api/series/{series['id']}/chapters", json={"title": "Empty", "number": 2}).json()

    monkeypatch.setattr(storage, "MAX_UPLOAD_PAGES", 1)
    too_many = client.post(
        f"/api/chapters/{empty['id']}/import",
        files=[
            ("files", ("1.png", png(2, 2), "image/png")),
            ("files", ("2.png", png(2, 2), "image/png")),
        ],
    )
    assert too_many.status_code == 413

    monkeypatch.setattr(storage, "MAX_UPLOAD_PAGES", 500)
    monkeypatch.setattr(storage, "MAX_PAGE_BYTES", 10)
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("001.png", b"x" * 20)
    archive_response = client.post(
        f"/api/chapters/{empty['id']}/import",
        files={"files": ("chapter.cbz", archive_buffer.getvalue(), "application/zip")},
    )
    assert archive_response.status_code == 413

    monkeypatch.setattr(storage, "MAX_PAGE_BYTES", 50 * 1024 * 1024)
    monkeypatch.setattr(storage, "MAX_IMAGE_PIXELS", 10)
    pixel_response = client.post(
        f"/api/chapters/{empty['id']}/import",
        files={"files": ("large-pixels.png", png(4, 4), "image/png")},
    )
    assert pixel_response.status_code == 413


def test_file_sqlite_pragmas_enable_foreign_keys_wal_and_busy_timeout(tmp_path: Path) -> None:
    database = tmp_path / "pragmas.db"
    connection = sqlite3.connect(database)
    try:
        configure_sqlite_connection(connection, enable_wal=True)
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    finally:
        connection.close()
