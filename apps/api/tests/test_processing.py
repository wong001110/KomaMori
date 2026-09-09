from __future__ import annotations

import io

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from komamori.main import app
from komamori.processing import detect_text_boxes, get_ocr_provider


class FakeOCR:
    def read(self, image: Image.Image) -> tuple[str, float | None]:
        return "テスト", 0.92


def page_bytes() -> bytes:
    image = Image.new("RGB", (600, 900), "white")
    draw = ImageDraw.Draw(image)
    for y in (130, 165, 200):
        draw.rectangle((390, y, 470, y + 18), fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def setup_page(client: TestClient) -> tuple[int, int]:
    series = client.post("/api/series", json={"title": "Process Demo", "source_language": "ja"}).json()
    chapter = client.post(f"/api/series/{series['id']}/chapters", json={"title": "Chapter 1", "number": 1}).json()
    client.post(f"/api/chapters/{chapter['id']}/import", files={"files": ("001.png", page_bytes(), "image/png")})
    page = client.get(f"/api/chapters/{chapter['id']}").json()["pages"][0]
    return chapter["id"], page["id"]


def test_detector_finds_synthetic_text_block() -> None:
    image = Image.open(io.BytesIO(page_bytes()))
    assert detect_text_boxes(image)


def test_analyze_and_clean_page(client: TestClient) -> None:
    _, page_id = setup_page(client)
    app.dependency_overrides[get_ocr_provider] = lambda: FakeOCR()
    try:
        analyzed = client.post(f"/api/pages/{page_id}/analyze")
    finally:
        app.dependency_overrides.pop(get_ocr_provider, None)
    assert analyzed.status_code == 200
    assert analyzed.json()["regions_created"] >= 1
    regions = client.get(f"/api/pages/{page_id}/regions").json()
    assert regions[0]["source_text"] == "テスト"
    clean = client.post(f"/api/pages/{page_id}/clean")
    assert clean.status_code == 200
    assert clean.json()["clean_asset"].startswith("derived/clean/")
    clean_asset = client.get(f"/api/pages/{page_id}/clean-asset")
    assert clean_asset.status_code == 200
    assert clean_asset.headers["content-type"].startswith("image/")
