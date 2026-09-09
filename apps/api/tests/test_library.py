from __future__ import annotations

import io
import zipfile

from fastapi.testclient import TestClient
from PIL import Image


def png_bytes(width: int = 120, height: int = 180) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def create_series_and_chapter(client: TestClient) -> tuple[int, int]:
    series = client.post("/api/series", json={"title": "Demo", "source_language": "ja"})
    assert series.status_code == 201
    series_id = series.json()["id"]
    chapter = client.post(
        f"/api/series/{series_id}/chapters",
        json={"title": "Chapter 1", "number": 1},
    )
    assert chapter.status_code == 201
    return series_id, chapter.json()["id"]


def test_image_import_and_manual_region(client: TestClient) -> None:
    _, chapter_id = create_series_and_chapter(client)
    response = client.post(
        f"/api/chapters/{chapter_id}/import",
        files=[
            ("files", ("002.png", png_bytes(200, 300), "image/png")),
            ("files", ("001.png", png_bytes(180, 280), "image/png")),
        ],
    )
    assert response.status_code == 200
    assert response.json()["pages_imported"] == 2

    chapter = client.get(f"/api/chapters/{chapter_id}").json()
    assert [page["page_index"] for page in chapter["pages"]] == [1, 2]
    assert chapter["pages"][0]["width"] == 180

    page_id = chapter["pages"][0]["id"]
    region = client.post(
        f"/api/pages/{page_id}/regions",
        json={
            "region_type": "dialogue",
            "geometry": [[10, 10], [80, 10], [80, 60], [10, 60]],
            "source_text": "こんにちは",
            "reading_order": 1,
        },
    )
    assert region.status_code == 201
    assert region.json()["source_text"] == "こんにちは"

    asset = client.get(f"/api/pages/{page_id}/asset")
    assert asset.status_code == 200
    assert asset.headers["content-type"].startswith("image/")


def test_cbz_import_uses_natural_page_order(client: TestClient) -> None:
    _, chapter_id = create_series_and_chapter(client)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("10.png", png_bytes(100, 100))
        zf.writestr("2.png", png_bytes(90, 90))
        zf.writestr("1.png", png_bytes(80, 80))
    response = client.post(
        f"/api/chapters/{chapter_id}/import",
        files={"files": ("demo.cbz", archive.getvalue(), "application/vnd.comicbook+zip")},
    )
    assert response.status_code == 200
    chapter = client.get(f"/api/chapters/{chapter_id}").json()
    assert [page["width"] for page in chapter["pages"]] == [80, 90, 100]
