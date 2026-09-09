from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from komamori import processing
from komamori.main import app
from komamori.processing import TesseractOCRProvider, detect_text_boxes, get_ocr_provider


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


def test_tesseract_provider_returns_normalized_word_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(processing.pytesseract, "image_to_string", lambda *args, **kwargs: "テスト")
    monkeypatch.setattr(
        processing.pytesseract,
        "image_to_data",
        lambda *args, **kwargs: {"text": ["", "テ", "スト"], "conf": ["-1", "40", "80"]},
    )
    provider = TesseractOCRProvider("jpn")
    text, confidence = provider.read(Image.new("RGB", (200, 100), "white"))
    assert text == "テスト"
    assert confidence == pytest.approx(0.60)


def test_default_tesseract_confidence_reaches_low_confidence_qa(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    chapter_id, page_id = setup_page(client)
    monkeypatch.delenv("KOMAMORI_OCR_PROVIDER", raising=False)
    monkeypatch.setattr(processing.pytesseract, "image_to_string", lambda *args, **kwargs: "低信頼")
    monkeypatch.setattr(
        processing.pytesseract,
        "image_to_data",
        lambda *args, **kwargs: {"text": ["低信頼"], "conf": ["42"]},
    )

    analyzed = client.post(f"/api/pages/{page_id}/analyze")
    assert analyzed.status_code == 200
    regions = client.get(f"/api/pages/{page_id}/regions").json()
    assert regions
    assert regions[0]["ocr_confidence"] == pytest.approx(0.42)

    region = regions[0]
    assert client.patch(f"/api/regions/{region['id']}", json={"region_type": "dialogue"}).status_code == 200
    assert client.put(
        f"/api/regions/{region['id']}/localizations/en",
        json={"text": "Low confidence", "status": "needs-review"},
    ).status_code == 200
    codes = {issue["code"] for issue in client.get(f"/api/chapters/{chapter_id}/qa/en").json()["issues"]}
    assert "low-ocr-confidence" in codes


def test_analyze_is_unclassified_and_cleanup_is_fail_safe(client: TestClient) -> None:
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
    assert all(region["region_type"] == "unknown" for region in regions)

    clean = client.post(f"/api/pages/{page_id}/clean")
    assert clean.status_code == 409

    for region in regions:
        response = client.patch(f"/api/regions/{region['id']}", json={"region_type": "dialogue"})
        assert response.status_code == 200

    clean = client.post(f"/api/pages/{page_id}/clean")
    assert clean.status_code == 200
    assert clean.json()["clean_asset"].startswith("derived/clean/")
    assert client.get(f"/api/pages/{page_id}/clean-asset").status_code == 200

    cleaned_regions = client.get(f"/api/pages/{page_id}/regions").json()
    assert all(region["mask_asset"].startswith("derived/masks/") for region in cleaned_regions)
    for region in cleaned_regions:
        mask = client.get(f"/api/regions/{region['id']}/mask-asset")
        assert mask.status_code == 200
        assert mask.headers["content-type"].startswith("image/png")


def test_sfx_is_not_cleaned_even_when_other_regions_are(client: TestClient) -> None:
    _, page_id = setup_page(client)
    dialogue = client.post(
        f"/api/pages/{page_id}/regions",
        json={"region_type": "dialogue", "geometry": [[360, 100], [500, 100], [500, 250], [360, 250]], "source_text": "hello", "reading_order": 1},
    ).json()
    sfx = client.post(
        f"/api/pages/{page_id}/regions",
        json={"region_type": "sfx", "geometry": [[40, 300], [200, 300], [200, 500], [40, 500]], "source_text": "ドン", "reading_order": 2},
    ).json()

    assert client.post(f"/api/pages/{page_id}/clean").status_code == 200
    refreshed = {item["id"]: item for item in client.get(f"/api/pages/{page_id}/regions").json()}
    assert refreshed[dialogue["id"]]["mask_asset"] is not None
    assert refreshed[sfx["id"]]["mask_asset"] is None
