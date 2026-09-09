from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from komamori.main import app
from komamori.storage import AssetStore, ImportPage
from komamori.translation import TranslationRequest, get_translation_provider
import komamori.routers.processing as processing_router


def image_bytes() -> bytes:
    import io

    image = Image.new("RGB", (80, 100), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def setup_page(client: TestClient, title: str) -> tuple[int, int, int]:
    series = client.post("/api/series", json={"title": title, "source_language": "ja"}).json()
    chapter = client.post(
        f"/api/series/{series['id']}/chapters",
        json={"title": "Chapter", "number": 1},
    ).json()
    assert client.post(
        f"/api/chapters/{chapter['id']}/import",
        files={"files": ("001.png", image_bytes(), "image/png")},
    ).status_code == 200
    page = client.get(f"/api/chapters/{chapter['id']}").json()["pages"][0]
    return series["id"], chapter["id"], page["id"]


def add_region(client: TestClient, page_id: int, source: str, *, region_type: str = "dialogue", order: int = 1) -> dict:
    response = client.post(
        f"/api/pages/{page_id}/regions",
        json={
            "region_type": region_type,
            "geometry": [[10, 10], [60, 10], [60, 50], [10, 50]],
            "source_text": source,
            "reading_order": order,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_partial_original_write_is_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = AssetStore(tmp_path / "assets")
    page = ImportPage(filename="001.png", content=b"payload", width=1, height=1)

    def partial_then_fail(self: Path, data: bytes) -> int:
        with self.open("wb") as handle:
            handle.write(data[:2])
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_bytes", partial_then_fail)
    with pytest.raises(OSError, match="disk full"):
        store.write_original(1, 1, 1, page)
    assert list((tmp_path / "assets").rglob("*.png")) == []


def test_partial_clean_and_mask_generation_are_removed(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, page_id = setup_page(client, "Partial writers")
    add_region(client, page_id, "hello")

    def partial_mask(_original, _geometry, target: Path) -> None:
        target.write_bytes(b"partial-mask")
        raise RuntimeError("mask failed")

    monkeypatch.setattr(processing_router, "generate_text_mask", partial_mask)
    with pytest.raises(RuntimeError, match="mask failed"):
        client.post(f"/api/pages/{page_id}/clean")
    assert list((tmp_path / "assets" / "derived" / "masks").rglob("*.png")) == []

    monkeypatch.undo()

    def partial_clean(_original, _masks, target: Path) -> None:
        target.write_bytes(b"partial-clean")
        raise RuntimeError("clean failed")

    monkeypatch.setattr(processing_router, "generate_clean_page", partial_clean)
    with pytest.raises(RuntimeError, match="clean failed"):
        client.post(f"/api/pages/{page_id}/clean")
    assert list((tmp_path / "assets" / "derived" / "clean").rglob("*.png")) == []
    assert list((tmp_path / "assets" / "derived" / "masks").rglob("*.png")) == []
    assert client.get(f"/api/pages/{page_id}/regions").json()[0]["mask_asset"] is None


class FakeTranslationProvider:
    def translate(self, request: TranslationRequest) -> str:
        return f"machine:{request.source_text}"


def test_nontranslatable_or_blocked_approval_is_not_reuse_memory(client: TestClient) -> None:
    series_id, chapter_id, page_id = setup_page(client, "Reuse safety")

    unknown = add_region(client, page_id, "未分類", region_type="unknown")
    unknown_loc = client.put(
        f"/api/regions/{unknown['id']}/localizations/en",
        json={"text": "Unclassified", "status": "needs-review"},
    ).json()
    unknown_approval = client.post(f"/api/localizations/{unknown_loc['id']}/approve")
    assert unknown_approval.status_code == 200
    assert unknown_approval.json()["remembered"] is False

    assert client.post(
        f"/api/series/{series_id}/terms",
        json={"locale": "en", "source": "勇者", "target": "Champion", "aliases": [], "locked": True},
    ).status_code == 201
    first = add_region(client, page_id, "勇者", order=2)
    first_loc = client.put(
        f"/api/regions/{first['id']}/localizations/en",
        json={"text": "Hero", "status": "needs-review"},
    ).json()
    blocked_approval = client.post(f"/api/localizations/{first_loc['id']}/approve")
    assert blocked_approval.status_code == 200
    assert blocked_approval.json()["remembered"] is False

    second = add_region(client, page_id, "勇者", order=3)
    app.dependency_overrides[get_translation_provider] = lambda: FakeTranslationProvider()
    try:
        result = client.post(
            f"/api/chapters/{chapter_id}/localize/en",
            json={"overwrite": False, "context_regions": 0},
        )
    finally:
        app.dependency_overrides.pop(get_translation_provider, None)
    assert result.status_code == 200
    view = client.get(f"/api/chapters/{chapter_id}/view/en").json()
    second_view = next(region for region in view["pages"][0]["regions"] if region["id"] == second["id"])
    assert second_view["localization"]["source"] == "machine"
    assert second_view["localization"]["text"] == "machine:勇者"
