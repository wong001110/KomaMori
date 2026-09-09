from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

from .config import settings

SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
ARCHIVE_EXTENSIONS = {".cbz", ".zip"}
MAX_ARCHIVE_PAGES = 500
MAX_PAGE_BYTES = 50 * 1024 * 1024


@dataclass(slots=True)
class ImportPage:
    filename: str
    content: bytes
    width: int
    height: int


def _natural_key(value: str) -> list[object]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def _safe_name(value: str) -> str:
    name = Path(value).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.")
    return cleaned or "page.png"


def _inspect_image(filename: str, content: bytes) -> ImportPage:
    if len(content) > MAX_PAGE_BYTES:
        raise HTTPException(status_code=413, detail=f"Page is too large: {filename}")
    try:
        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
            image.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid image: {filename}") from exc
    return ImportPage(filename=_safe_name(filename), content=content, width=width, height=height)


async def unpack_uploads(files: list[UploadFile]) -> list[ImportPage]:
    if not files:
        raise HTTPException(status_code=400, detail="At least one image or CBZ file is required")

    if len(files) == 1 and Path(files[0].filename or "").suffix.lower() in ARCHIVE_EXTENSIONS:
        archive_name = files[0].filename or "chapter.cbz"
        archive_bytes = await files[0].read()
        try:
            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
                entries = [
                    info
                    for info in archive.infolist()
                    if not info.is_dir() and Path(info.filename).suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
                ]
                entries.sort(key=lambda item: _natural_key(item.filename))
                if not entries:
                    raise HTTPException(status_code=422, detail=f"No supported images in {archive_name}")
                if len(entries) > MAX_ARCHIVE_PAGES:
                    raise HTTPException(status_code=413, detail="Archive contains too many pages")
                return [_inspect_image(info.filename, archive.read(info)) for info in entries]
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=422, detail=f"Invalid CBZ/ZIP archive: {archive_name}") from exc

    pages: list[ImportPage] = []
    for upload in files:
        filename = upload.filename or "page.png"
        if Path(filename).suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
            raise HTTPException(status_code=422, detail=f"Unsupported file type: {filename}")
        pages.append(_inspect_image(filename, await upload.read()))

    pages.sort(key=lambda item: _natural_key(item.filename))
    return pages


class AssetStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def write_original(self, series_id: int, chapter_id: int, page_index: int, page: ImportPage) -> str:
        relative = Path("original") / str(series_id) / str(chapter_id) / f"{page_index:04d}-{page.filename}"
        target = (self.root / relative).resolve()
        if self.root not in target.parents:
            raise ValueError("Asset path escaped root")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(page.content)
        return relative.as_posix()

    def writable_path(self, relative: str) -> Path:
        target = (self.root / relative).resolve()
        if target != self.root and self.root not in target.parents:
            raise ValueError("Asset path escaped root")
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def resolve(self, relative: str) -> Path:
        target = (self.root / relative).resolve()
        if target != self.root and self.root not in target.parents:
            raise HTTPException(status_code=404, detail="Asset not found")
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Asset not found")
        return target


def get_asset_store() -> AssetStore:
    return AssetStore(settings.asset_root)
