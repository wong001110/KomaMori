from __future__ import annotations

import io

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from komamori.main import app
from komamori.processing import get_ocr_provider


class FakeOCR:
    def read(self, image: Image.Image) -> tuple[str, float | None]:
        return "こんにちは", 0.91


def manga_page() -> bytes:
    image = Image.new("RGB", (500, 700), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((320, 100, 400, 122), fill="black")
    draw.rectangle((320, 135, 400, 157), fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def setup_chapter(client: TestClient) -> tuple[int, int, int]:
    series = client.post("/api/series", json={"title": "Workbench Demo", "source_language": "ja"}).json()
    chapter = client.post(
        f"/api/series/{series['id']}/chapters",
        json={"title": "Chapter 1", "number": 1},
    ).json()
    client.post(
        f"/api/chapters/{chapter['id']}/import",
        files={"files": ("001.png", manga_page(), "image/png")},
    )
    page = client.get(f"/api/chapters/{chapter['id']}").json()["pages"][0]
    return series["id"], chapter["id"], page["id"]


def test_batch_analyze_and_clean(client: TestClient) -> None:
    _, chapter_id, _ = setup_chapter(client)
    app.dependency_overrides[get_ocr_provider] = lambda: FakeOCR()
    try:
        analyzed = client.post(f"/api/chapters/{chapter_id}/analyze")
    finally:
        app.dependency_overrides.pop(get_ocr_provider, None)
    assert analyzed.status_code == 200
    assert analyzed.json()["pages_analyzed"] == 1
    assert analyzed.json()["regions_created"] >= 1

    cleaned = client.post(f"/api/chapters/{chapter_id}/clean")
    assert cleaned.status_code == 200
    assert cleaned.json()["pages_cleaned"] == 1


def test_shared_source_supports_two_locale_views(client: TestClient) -> None:
    _, chapter_id, page_id = setup_chapter(client)
    region = client.post(
        f"/api/pages/{page_id}/regions",
        json={
            "region_type": "dialogue",
            "geometry": [[80, 80], [300, 80], [300, 220], [80, 220]],
            "source_text": "こんにちは",
            "reading_order": 1,
        },
    ).json()
    en = client.put(
        f"/api/regions/{region['id']}/localizations/en",
        json={"text": "Hello!", "status": "approved"},
    )
    zh = client.put(
        f"/api/regions/{region['id']}/localizations/zh-TW",
        json={"text": "你好！", "status": "approved"},
    )
    assert en.status_code == zh.status_code == 200

    en_view = client.get(f"/api/chapters/{chapter_id}/view/en").json()
    zh_view = client.get(f"/api/chapters/{chapter_id}/view/zh-TW").json()
    assert en_view["pages"][0]["regions"][0]["id"] == zh_view["pages"][0]["regions"][0]["id"]
    assert en_view["pages"][0]["regions"][0]["source_text"] == "こんにちは"
    assert en_view["pages"][0]["regions"][0]["localization"]["text"] == "Hello!"
    assert zh_view["pages"][0]["regions"][0]["localization"]["text"] == "你好！"

    locales = client.get(f"/api/chapters/{chapter_id}/locales").json()
    assert {item["locale"] for item in locales} == {"en", "zh-TW"}
    assert all(item["total_regions"] == 1 for item in locales)
