from __future__ import annotations

import io

from fastapi.testclient import TestClient
from PIL import Image


def png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (320, 480), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def setup_page(client: TestClient) -> tuple[int, int]:
    series = client.post("/api/series", json={"title": "Region Lifecycle", "source_language": "ja"}).json()
    chapter = client.post(
        f"/api/series/{series['id']}/chapters",
        json={"title": "Chapter 1", "number": 1},
    ).json()
    client.post(
        f"/api/chapters/{chapter['id']}/import",
        files={"files": ("001.png", png_bytes(), "image/png")},
    )
    page = client.get(f"/api/chapters/{chapter['id']}").json()["pages"][0]
    return chapter["id"], page["id"]


def create_region(client: TestClient, page_id: int) -> dict:
    return client.post(
        f"/api/pages/{page_id}/regions",
        json={
            "region_type": "dialogue",
            "geometry": [[70, 70], [250, 70], [250, 220], [70, 220]],
            "source_text": "原文",
            "reading_order": 1,
        },
    ).json()


def test_delete_region_removes_localization(client: TestClient) -> None:
    _, page_id = setup_page(client)
    region = create_region(client, page_id)
    client.put(
        f"/api/regions/{region['id']}/localizations/en",
        json={"text": "Translation", "status": "needs-review"},
    )

    deleted = client.delete(f"/api/regions/{region['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/regions/{region['id']}/localizations").status_code == 404
    assert client.get(f"/api/pages/{page_id}/regions").json() == []


def test_delete_cleanable_region_invalidates_clean_and_removes_mask(client: TestClient) -> None:
    _, page_id = setup_page(client)
    region = create_region(client, page_id)
    assert client.post(f"/api/pages/{page_id}/clean").status_code == 200
    cleaned = client.get(f"/api/pages/{page_id}/regions").json()[0]
    assert cleaned["mask_asset"]
    assert client.get(f"/api/regions/{region['id']}/mask-asset").status_code == 200
    assert client.get(f"/api/pages/{page_id}/clean-asset").status_code == 200

    assert client.delete(f"/api/regions/{region['id']}").status_code == 204
    assert client.get(f"/api/pages/{page_id}/clean-asset").status_code == 404
    assert client.get(f"/api/regions/{region['id']}/mask-asset").status_code == 404
