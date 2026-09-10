from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from komamori.main import app
from komamori.migrations import run_migrations
from komamori.processing import DetectedRegion
from komamori.translation import TranslationRequest, get_translation_provider
import komamori.routers.processing as processing_router


def _series(client: TestClient, title: str = "P12") -> int:
    response = client.post("/api/series", json={"title": title, "source_language": "ja"})
    assert response.status_code == 201
    return response.json()["id"]


def _chapter(client: TestClient, series_id: int, display: str = "1", order: float = 1) -> dict:
    response = client.post(
        f"/api/series/{series_id}/chapters",
        json={"title": f"Chapter {display}", "display_number": display, "sort_order": order},
    )
    assert response.status_code == 201
    return response.json()


def _import_page(client: TestClient, chapter_id: int) -> int:
    import io
    from PIL import Image

    image = Image.new("RGB", (80, 100), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    response = client.post(
        f"/api/chapters/{chapter_id}/import",
        files={"files": ("001.png", buffer.getvalue(), "image/png")},
    )
    assert response.status_code == 200
    return client.get(f"/api/chapters/{chapter_id}").json()["pages"][0]["id"]


def _dialogue(client: TestClient, page_id: int, source: str) -> dict:
    response = client.post(
        f"/api/pages/{page_id}/regions",
        json={
            "region_type": "dialogue",
            "geometry": [[5, 5], [50, 5], [50, 40], [5, 40]],
            "source_text": source,
            "reading_order": 1,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_chapter_display_identity_sorts_independently_and_legacy_number_remains_compatible(client: TestClient) -> None:
    series_id = _series(client, "Identity")
    extra = _chapter(client, series_id, "Extra", 20)
    assert extra["number"] < 0
    _chapter(client, series_id, "1", 1)
    _chapter(client, series_id, "10.5", 10.5)

    # Modern callers must provide a real user-visible sort key; the negative
    # compatibility sentinel is never allowed to leak into product ordering.
    incomplete_modern = client.post(
        f"/api/series/{series_id}/chapters",
        json={"title": "Missing order", "display_number": "Interlude"},
    )
    assert incomplete_modern.status_code == 422

    legacy = client.post(
        f"/api/series/{series_id}/chapters",
        json={"title": "Legacy", "number": 2},
    )
    assert legacy.status_code == 201
    assert legacy.json()["display_number"] == "2"
    assert legacy.json()["sort_order"] == 2

    labels = [row["display_number"] for row in client.get(f"/api/series/{series_id}").json()["chapters"]]
    assert labels == ["1", "2", "10.5", "Extra"]

    modern_update = client.patch(
        f"/api/chapters/{extra['id']}",
        json={"display_number": "Prologue", "sort_order": 0.5},
    )
    assert modern_update.status_code == 200
    assert modern_update.json()["display_number"] == "Prologue"
    assert modern_update.json()["sort_order"] == 0.5

    legacy_update = client.patch(
        f"/api/chapters/{legacy.json()['id']}",
        json={"number": 3},
    )
    assert legacy_update.status_code == 200
    assert legacy_update.json()["display_number"] == "3"
    assert legacy_update.json()["sort_order"] == 3


def test_legacy_database_migration_adds_identity_and_provenance_without_losing_rows(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO schema_migrations(version,name,applied_at) VALUES (1,'structured-mvp-baseline','old')"
        )
        connection.exec_driver_sql(
            "CREATE TABLE chapters(id INTEGER PRIMARY KEY, series_id INTEGER NOT NULL, title TEXT NOT NULL, number FLOAT NOT NULL, status TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE text_regions(id INTEGER PRIMARY KEY, page_id INTEGER NOT NULL, source_text TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE localizations(id INTEGER PRIMARY KEY, text_region_id INTEGER NOT NULL, locale TEXT NOT NULL, text TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO chapters(id,series_id,title,number,status) VALUES (7,1,'Legacy',10.5,'raw')"
        )
        connection.exec_driver_sql(
            "INSERT INTO text_regions(id,page_id,source_text) VALUES (9,1,'旧')"
        )
        connection.exec_driver_sql(
            "INSERT INTO localizations(id,text_region_id,locale,text) VALUES (11,9,'en','Old')"
        )

    assert run_migrations(engine) == [2]
    with engine.connect() as connection:
        row = connection.execute(text("SELECT id,title,number,display_number,sort_order FROM chapters WHERE id=7")).mappings().one()
        assert dict(row) == {"id": 7, "title": "Legacy", "number": 10.5, "display_number": "10.5", "sort_order": 10.5}
        assert connection.exec_driver_sql("SELECT source_text, ocr_provenance FROM text_regions WHERE id=9").one()[0] == "旧"
        assert connection.exec_driver_sql("SELECT text, provenance FROM localizations WHERE id=11").one()[0] == "Old"
        assert connection.exec_driver_sql("SELECT version FROM schema_migrations ORDER BY version").all() == [(1,), (2,)]


def test_analysis_persists_and_exposes_ocr_provenance(client: TestClient, monkeypatch) -> None:
    series_id = _series(client, "OCR provenance")
    chapter = _chapter(client, series_id)
    page_id = _import_page(client, chapter["id"])

    def fake_analysis(*_args, **_kwargs):
        return [
            DetectedRegion(
                geometry=[[1, 1], [20, 1], [20, 20], [1, 20]],
                text="テスト",
                confidence=0.91,
                provenance={
                    "schema_version": 1,
                    "kind": "machine-ocr",
                    "provider": "fake-ocr",
                    "model": "fixture-v1",
                },
            )
        ]

    monkeypatch.setattr(processing_router, "analyze_page", fake_analysis)
    response = client.post(f"/api/pages/{page_id}/analyze")
    assert response.status_code == 200
    region = client.get(f"/api/pages/{page_id}/regions").json()[0]
    assert region["ocr_provenance"]["provider"] == "fake-ocr"
    assert region["ocr_provenance"]["model"] == "fixture-v1"


class FakeTranslationProvider:
    model = "fake-model-v2"

    def translate(self, request: TranslationRequest) -> str:
        return f"translated:{request.source_text}"


def test_translation_provenance_covers_machine_manual_and_approved_memory_without_secrets(client: TestClient) -> None:
    series_id = _series(client, "Translation provenance")
    chapter = _chapter(client, series_id)
    page_id = _import_page(client, chapter["id"])
    first = _dialogue(client, page_id, "勇者")

    app.dependency_overrides[get_translation_provider] = lambda: FakeTranslationProvider()
    try:
        localized = client.post(
            f"/api/chapters/{chapter['id']}/localize/en",
            json={"overwrite": False, "context_regions": 3},
        )
    finally:
        app.dependency_overrides.pop(get_translation_provider, None)
    assert localized.status_code == 200

    machine = client.get(f"/api/regions/{first['id']}/localizations").json()[0]
    assert machine["source"] == "machine"
    assert machine["provenance"]["kind"] == "machine"
    assert machine["provenance"]["model"] == "fake-model-v2"
    assert machine["provenance"]["prompt_version"] == "manga-region-v1"
    serialized = str(machine["provenance"]).lower()
    assert "api_key" not in serialized and "authorization" not in serialized and "bearer" not in serialized

    manual = client.put(
        f"/api/regions/{first['id']}/localizations/en",
        json={"text": "Hero", "status": "needs-review"},
    ).json()
    assert manual["source"] == "manual"
    assert manual["provenance"] == {"schema_version": 1, "kind": "manual"}
    assert client.post(f"/api/localizations/{manual['id']}/approve").status_code == 200

    second = client.post(
        f"/api/pages/{page_id}/regions",
        json={
            "region_type": "dialogue",
            "geometry": [[10, 50], [55, 50], [55, 80], [10, 80]],
            "source_text": "勇者",
            "reading_order": 2,
        },
    ).json()
    app.dependency_overrides[get_translation_provider] = lambda: FakeTranslationProvider()
    try:
        reused = client.post(
            f"/api/chapters/{chapter['id']}/localize/en",
            json={"overwrite": False, "context_regions": 0},
        )
    finally:
        app.dependency_overrides.pop(get_translation_provider, None)
    assert reused.status_code == 200
    view = client.get(f"/api/chapters/{chapter['id']}/view/en").json()
    second_row = next(row for row in view["pages"][0]["regions"] if row["id"] == second["id"])
    assert second_row["localization"]["source"] == "approved-memory"
    assert second_row["localization"]["provenance"]["kind"] == "approved-memory"
    assert second_row["localization"]["provenance"]["memory_provenance"] == "human-approved"
