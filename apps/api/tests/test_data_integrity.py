from __future__ import annotations

import io

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from komamori.main import app
from komamori.translation import TranslationRequest, get_translation_provider


class FakeTranslator:
    def __init__(self) -> None:
        self.calls: list[TranslationRequest] = []

    def translate(self, request: TranslationRequest) -> str:
        self.calls.append(request)
        return f"translated:{request.source_text}"


def page_bytes() -> bytes:
    image = Image.new("RGB", (500, 700), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 100, 220, 130), fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def setup_page(client: TestClient) -> tuple[int, int, int]:
    series = client.post("/api/series", json={"title": "Integrity", "source_language": "ja"}).json()
    chapter = client.post(
        f"/api/series/{series['id']}/chapters",
        json={"title": "Chapter 1", "number": 1},
    ).json()
    client.post(
        f"/api/chapters/{chapter['id']}/import",
        files={"files": ("001.png", page_bytes(), "image/png")},
    )
    page = client.get(f"/api/chapters/{chapter['id']}").json()["pages"][0]
    return series["id"], chapter["id"], page["id"]


def create_region(client: TestClient, page_id: int, *, region_type: str = "dialogue", source: str = "原文", order: int = 1):
    return client.post(
        f"/api/pages/{page_id}/regions",
        json={
            "region_type": region_type,
            "geometry": [[70, 70], [300, 70], [300, 240], [70, 240]],
            "source_text": source,
            "reading_order": order,
        },
    ).json()


def test_region_edits_invalidate_clean_mask_and_recompute_layout(client: TestClient) -> None:
    _, _, page_id = setup_page(client)
    region = create_region(client, page_id)
    localization = client.put(
        f"/api/regions/{region['id']}/localizations/en",
        json={"text": "A somewhat long translation for layout", "status": "needs-review"},
    ).json()
    assert client.post(f"/api/localizations/{localization['id']}/approve").status_code == 200
    assert client.post(f"/api/pages/{page_id}/clean").status_code == 200

    before = client.get(f"/api/regions/{region['id']}/localizations").json()[0]
    cleaned_region = client.get(f"/api/pages/{page_id}/regions").json()[0]
    assert cleaned_region["mask_asset"] is not None
    assert client.get(f"/api/pages/{page_id}/clean-asset").status_code == 200

    changed = client.patch(
        f"/api/regions/{region['id']}",
        json={"geometry": [[80, 80], [160, 80], [160, 130], [80, 130]]},
    )
    assert changed.status_code == 200
    assert changed.json()["mask_asset"] is None
    assert client.get(f"/api/pages/{page_id}/clean-asset").status_code == 404

    after = client.get(f"/api/regions/{region['id']}/localizations").json()[0]
    assert after["layout"] != before["layout"]
    assert after["status"] == "approved"

    source_edit = client.patch(f"/api/regions/{region['id']}", json={"source_text": "修正後の原文"})
    assert source_edit.status_code == 200
    after_source = client.get(f"/api/regions/{region['id']}/localizations").json()[0]
    assert after_source["status"] == "needs-review"


def test_editing_approved_text_requires_reapproval_and_updates_reuse_memory(client: TestClient) -> None:
    _, chapter_id, page_id = setup_page(client)
    first = create_region(client, page_id, source="同じ原文", order=1)
    loc = client.put(
        f"/api/regions/{first['id']}/localizations/en",
        json={"text": "Old approved text", "status": "needs-review"},
    ).json()
    assert client.post(f"/api/localizations/{loc['id']}/approve").json()["status"] == "approved"

    edited = client.put(
        f"/api/regions/{first['id']}/localizations/en",
        json={"text": "New approved text", "status": "approved"},
    )
    assert edited.status_code == 200
    assert edited.json()["status"] == "needs-review"

    assert client.post(f"/api/localizations/{loc['id']}/approve").json()["status"] == "approved"
    second = create_region(client, page_id, source="同じ原文", order=2)

    fake = FakeTranslator()
    app.dependency_overrides[get_translation_provider] = lambda: fake
    try:
        localized = client.post(f"/api/chapters/{chapter_id}/localize/en", json={"overwrite": False})
    finally:
        app.dependency_overrides.pop(get_translation_provider, None)

    assert localized.status_code == 200
    assert localized.json()["reused"] == 1
    assert fake.calls == []
    second_loc = client.get(f"/api/regions/{second['id']}/localizations").json()[0]
    assert second_loc["text"] == "New approved text"
    assert second_loc["source"] == "approved-memory"


def test_unknown_and_sfx_are_skipped_by_automatic_localization(client: TestClient) -> None:
    _, chapter_id, page_id = setup_page(client)
    create_region(client, page_id, region_type="unknown", source="unknown", order=1)
    create_region(client, page_id, region_type="sfx", source="ドン", order=2)
    create_region(client, page_id, region_type="dialogue", source="dialogue", order=3)

    fake = FakeTranslator()
    app.dependency_overrides[get_translation_provider] = lambda: fake
    try:
        result = client.post(f"/api/chapters/{chapter_id}/localize/en", json={"overwrite": False})
    finally:
        app.dependency_overrides.pop(get_translation_provider, None)

    assert result.status_code == 200
    assert result.json()["created"] == 1
    assert result.json()["skipped"] == 2
    assert [call.source_text for call in fake.calls] == ["dialogue"]
