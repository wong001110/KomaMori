from __future__ import annotations

import io

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from komamori.main import app
from komamori.storage import get_asset_store


def png_bytes() -> bytes:
    image = Image.new("RGB", (400, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 100, 220, 130), fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def create_library(client: TestClient) -> tuple[dict, dict, dict]:
    series = client.post("/api/series", json={"title": "Lifecycle", "source_language": "ja"}).json()
    chapter = client.post(
        f"/api/series/{series['id']}/chapters",
        json={"title": "Chapter 1", "number": 1},
    ).json()
    client.post(
        f"/api/chapters/{chapter['id']}/import",
        files={"files": ("001.png", png_bytes(), "image/png")},
    )
    page = client.get(f"/api/chapters/{chapter['id']}").json()["pages"][0]
    return series, chapter, page


def add_dialogue(client: TestClient, page_id: int, source: str, order: int) -> dict:
    return client.post(
        f"/api/pages/{page_id}/regions",
        json={
            "region_type": "dialogue",
            "geometry": [[70, 70 + order * 100], [300, 70 + order * 100], [300, 150 + order * 100], [70, 150 + order * 100]],
            "source_text": source,
            "reading_order": order,
        },
    ).json()


def test_series_and_chapter_update_endpoints(client: TestClient) -> None:
    series, chapter, _ = create_library(client)
    updated_series = client.patch(
        f"/api/series/{series['id']}",
        json={"title": "Renamed series", "source_language": "ja"},
    )
    assert updated_series.status_code == 200
    assert updated_series.json()["title"] == "Renamed series"

    updated_chapter = client.patch(
        f"/api/chapters/{chapter['id']}",
        json={"title": "Renamed chapter", "number": 1.5},
    )
    assert updated_chapter.status_code == 200
    assert updated_chapter.json()["title"] == "Renamed chapter"
    assert updated_chapter.json()["number"] == 1.5

    duplicate = client.post(
        f"/api/series/{series['id']}/chapters",
        json={"title": "Chapter 2", "number": 2},
    ).json()
    conflict = client.patch(f"/api/chapters/{duplicate['id']}", json={"number": 1.5})
    assert conflict.status_code == 409


def test_delete_chapter_removes_original_clean_and_mask_assets(client: TestClient) -> None:
    series, chapter, page = create_library(client)
    region = add_dialogue(client, page["id"], "原文", 1)
    assert client.post(f"/api/pages/{page['id']}/clean").status_code == 200
    page_after = client.get(f"/api/chapters/{chapter['id']}").json()["pages"][0]
    region_after = client.get(f"/api/pages/{page['id']}/regions").json()[0]
    store = app.dependency_overrides[get_asset_store]()
    assert store.exists(page_after["original_asset"])
    assert store.exists(page_after["clean_asset"])
    assert store.exists(region_after["mask_asset"])

    assert client.delete(f"/api/chapters/{chapter['id']}").status_code == 204
    assert client.get(f"/api/chapters/{chapter['id']}").status_code == 404
    assert not store.exists(page_after["original_asset"])
    assert not store.exists(page_after["clean_asset"])
    assert not store.exists(region_after["mask_asset"])
    assert client.get(f"/api/series/{series['id']}").json()["chapters"] == []


def test_delete_series_cascades_database_rows_and_assets(client: TestClient) -> None:
    series, chapter, page = create_library(client)
    region = add_dialogue(client, page["id"], "共有", 1)
    localization = client.put(
        f"/api/regions/{region['id']}/localizations/en",
        json={"text": "Shared", "status": "needs-review"},
    ).json()
    client.post(f"/api/localizations/{localization['id']}/approve")
    client.post(
        f"/api/series/{series['id']}/terms",
        json={"locale": "en", "source": "共有", "target": "Shared", "locked": True},
    )
    assert client.post(f"/api/pages/{page['id']}/clean").status_code == 200
    original = client.get(f"/api/chapters/{chapter['id']}").json()["pages"][0]["original_asset"]
    store = app.dependency_overrides[get_asset_store]()
    assert store.exists(original)

    assert client.delete(f"/api/series/{series['id']}").status_code == 204
    assert client.get(f"/api/series/{series['id']}").status_code == 404
    assert client.get(f"/api/chapters/{chapter['id']}").status_code == 404
    assert client.get(f"/api/regions/{region['id']}/localizations").status_code == 404
    assert not store.exists(original)


def test_locale_readiness_moves_from_in_progress_to_review_to_ready(client: TestClient) -> None:
    series, chapter, page = create_library(client)
    first = add_dialogue(client, page["id"], "一", 1)
    second = add_dialogue(client, page["id"], "二", 2)

    first_loc = client.put(
        f"/api/regions/{first['id']}/localizations/en",
        json={"text": "One", "status": "needs-review"},
    ).json()
    summary = client.get(f"/api/chapters/{chapter['id']}/locales").json()[0]
    assert summary["status"] == "in-progress"

    second_loc = client.put(
        f"/api/regions/{second['id']}/localizations/en",
        json={"text": "Two", "status": "needs-review"},
    ).json()
    summary = client.get(f"/api/chapters/{chapter['id']}/locales").json()[0]
    assert summary["status"] == "review"

    client.post(f"/api/localizations/{first_loc['id']}/approve")
    client.post(f"/api/localizations/{second_loc['id']}/approve")
    summary = client.get(f"/api/chapters/{chapter['id']}/locales").json()[0]
    assert summary["status"] == "ready"
