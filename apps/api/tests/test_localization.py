from __future__ import annotations

import io

from fastapi.testclient import TestClient
from PIL import Image

from komamori.main import app
from komamori.translation import TranslationRequest, get_translation_provider


class FakeTranslator:
    def __init__(self) -> None:
        self.calls: list[TranslationRequest] = []

    def translate(self, request: TranslationRequest) -> str:
        self.calls.append(request)
        if "黒騎士" in request.source_text or "ブラックナイト" in request.source_text:
            return "The Black Knight has returned."
        return f"Translated: {request.source_text}"


def png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (320, 480), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def setup_region(client: TestClient, text: str = "黒騎士が戻った") -> tuple[int, int, int]:
    series = client.post("/api/series", json={"title": "Demo", "source_language": "ja"}).json()
    chapter = client.post(f"/api/series/{series['id']}/chapters", json={"title": "Chapter 1", "number": 1}).json()
    client.post(f"/api/chapters/{chapter['id']}/import", files={"files": ("001.png", png_bytes(), "image/png")})
    page = client.get(f"/api/chapters/{chapter['id']}").json()["pages"][0]
    region = client.post(f"/api/pages/{page['id']}/regions", json={"region_type": "dialogue", "geometry": [[80, 80], [250, 80], [250, 220], [80, 220]], "source_text": text, "reading_order": 1}).json()
    return series["id"], chapter["id"], region["id"]


def test_terms_translation_qa_and_approved_reuse(client: TestClient) -> None:
    series_id, chapter_id, region_id = setup_region(client)
    term = client.post(f"/api/series/{series_id}/terms", json={"locale": "en", "source": "黒騎士", "target": "Black Knight", "locked": True})
    assert term.status_code == 201
    fake = FakeTranslator()
    app.dependency_overrides[get_translation_provider] = lambda: fake
    try:
        localized = client.post(f"/api/chapters/{chapter_id}/localize/en", json={"overwrite": False})
    finally:
        app.dependency_overrides.pop(get_translation_provider, None)
    assert localized.status_code == 200
    assert localized.json()["created"] == 1
    assert fake.calls[0].locked_terms == {"黒騎士": "Black Knight"}
    loc = client.get(f"/api/regions/{region_id}/localizations").json()[0]
    assert loc["text"] == "The Black Knight has returned."
    assert loc["layout"]["fitStatus"] == "fit"
    assert client.get(f"/api/chapters/{chapter_id}/qa/en").json()["issues"] == []
    approved = client.post(f"/api/localizations/{loc['id']}/approve")
    assert approved.status_code == 200
    assert approved.json()["remembered"] is True
    page_id = client.get(f"/api/chapters/{chapter_id}").json()["pages"][0]["id"]
    second = client.post(f"/api/pages/{page_id}/regions", json={"region_type": "dialogue", "geometry": [[70, 250], [260, 250], [260, 390], [70, 390]], "source_text": "黒騎士が戻った", "reading_order": 2}).json()
    fake2 = FakeTranslator()
    app.dependency_overrides[get_translation_provider] = lambda: fake2
    try:
        result = client.post(f"/api/chapters/{chapter_id}/localize/en", json={"overwrite": False})
    finally:
        app.dependency_overrides.pop(get_translation_provider, None)
    assert result.status_code == 200
    assert result.json()["reused"] == 1
    assert fake2.calls == []
    second_loc = client.get(f"/api/regions/{second['id']}/localizations").json()[0]
    assert second_loc["source"] == "approved-memory"


def test_locked_term_alias_is_used_for_translation_and_qa(client: TestClient) -> None:
    series_id, chapter_id, region_id = setup_region(client, "ブラックナイトが戻った")
    term = client.post(
        f"/api/series/{series_id}/terms",
        json={
            "locale": "en",
            "source": "黒騎士",
            "target": "Black Knight",
            "aliases": ["ブラックナイト"],
            "locked": True,
        },
    )
    assert term.status_code == 201

    fake = FakeTranslator()
    app.dependency_overrides[get_translation_provider] = lambda: fake
    try:
        localized = client.post(f"/api/chapters/{chapter_id}/localize/en", json={"overwrite": False})
    finally:
        app.dependency_overrides.pop(get_translation_provider, None)
    assert localized.status_code == 200
    assert fake.calls[0].locked_terms == {"ブラックナイト": "Black Knight"}
    assert client.get(f"/api/chapters/{chapter_id}/qa/en").json()["issues"] == []

    # Manual correction that drops the locked target must still be flagged when the source matched an alias.
    client.put(
        f"/api/regions/{region_id}/localizations/en",
        json={"text": "The Dark Knight returned.", "status": "needs-review"},
    )
    issues = client.get(f"/api/chapters/{chapter_id}/qa/en").json()["issues"]
    locked = [issue for issue in issues if issue["code"] == "locked-term"]
    assert len(locked) == 1
    assert "ブラックナイト" in locked[0]["message"]


def test_locked_term_and_poor_fit_are_reported(client: TestClient) -> None:
    series_id, chapter_id, region_id = setup_region(client, "黒騎士")
    client.post(f"/api/series/{series_id}/terms", json={"locale": "en", "source": "黒騎士", "target": "Black Knight", "locked": True})
    response = client.put(f"/api/regions/{region_id}/localizations/en", json={"text": "Dark Knight " + "very " * 80, "status": "needs-review"})
    assert response.status_code == 200
    issues = client.get(f"/api/chapters/{chapter_id}/qa/en").json()["issues"]
    codes = {issue["code"] for issue in issues}
    assert "locked-term" in codes
    assert "poor-fit" in codes
