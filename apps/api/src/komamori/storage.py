from __future__ import annotations

import io
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

from .config import settings

SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
ARCHIVE_EXTENSIONS = {".cbz", ".zip"}
MAX_UPLOAD_PAGES = 500
MAX_ARCHIVE_PAGES = MAX_UPLOAD_PAGES
MAX_PAGE_BYTES = 50 * 1024 * 1024
MAX_TOTAL_UPLOAD_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_IMAGE_PIXELS = 100_000_000


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
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                raise HTTPException(status_code=413, detail=f"Image dimensions are too large: {filename}")
            image.verify()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid image: {filename}") from exc
    return ImportPage(filename=_safe_name(filename), content=content, width=width, height=height)


async def _read_upload_limited(upload: UploadFile, limit: int, detail: str) -> bytes:
    content = await upload.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(status_code=413, detail=detail)
    return content


async def unpack_uploads(files: list[UploadFile]) -> list[ImportPage]:
    if not files:
        raise HTTPException(status_code=400, detail="At least one image or CBZ file is required")
    if len(files) > MAX_UPLOAD_PAGES:
        raise HTTPException(status_code=413, detail="Too many uploaded pages")

    if len(files) == 1 and Path(files[0].filename or "").suffix.lower() in ARCHIVE_EXTENSIONS:
        archive_name = files[0].filename or "chapter.cbz"
        archive_bytes = await _read_upload_limited(files[0], MAX_ARCHIVE_BYTES, "Archive is too large")
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
                if len(entries) > MAX_UPLOAD_PAGES:
                    raise HTTPException(status_code=413, detail="Archive contains too many pages")

                total_uncompressed = 0
                for info in entries:
                    if info.file_size > MAX_PAGE_BYTES:
                        raise HTTPException(status_code=413, detail=f"Archive page is too large: {info.filename}")
                    total_uncompressed += info.file_size
                    if total_uncompressed > MAX_TOTAL_UPLOAD_BYTES:
                        raise HTTPException(status_code=413, detail="Archive uncompressed content is too large")

                pages: list[ImportPage] = []
                for info in entries:
                    pages.append(_inspect_image(info.filename, archive.read(info)))
                return pages
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=422, detail=f"Invalid CBZ/ZIP archive: {archive_name}") from exc

    pages: list[ImportPage] = []
    total_bytes = 0
    for upload in files:
        filename = upload.filename or "page.png"
        if Path(filename).suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
            raise HTTPException(status_code=422, detail=f"Unsupported file type: {filename}")
        remaining = MAX_TOTAL_UPLOAD_BYTES - total_bytes
        if remaining <= 0:
            raise HTTPException(status_code=413, detail="Uploaded pages are too large in aggregate")
        limit = min(MAX_PAGE_BYTES, remaining)
        content = await _read_upload_limited(upload, limit, f"Page or aggregate upload is too large: {filename}")
        total_bytes += len(content)
        pages.append(_inspect_image(filename, content))

    pages.sort(key=lambda item: _natural_key(item.filename))
    return pages


class AssetStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _target(self, relative: str | Path) -> Path:
        target = (self.root / relative).resolve()
        if target != self.root and self.root not in target.parents:
            raise ValueError("Asset path escaped root")
        return target

    def unique_relative(self, directory: str | Path, filename: str) -> str:
        safe = _safe_name(filename)
        return (Path(directory) / f"{uuid4().hex}-{safe}").as_posix()

    def unique_writable_path(self, directory: str | Path, suffix: str = ".bin") -> tuple[str, Path]:
        relative = (Path(directory) / f"{uuid4().hex}{suffix}").as_posix()
        return relative, self.writable_path(relative)

    def write_original(self, series_id: int, chapter_id: int, page_index: int, page: ImportPage) -> str:
        relative = self.unique_relative(
            Path("original") / str(series_id) / str(chapter_id),
            f"{page_index:04d}-{page.filename}",
        )
        target = self._target(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(page.content)
        return relative

    def writable_path(self, relative: str) -> Path:
        target = self._target(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def exists(self, relative: str | None) -> bool:
        if not relative:
            return False
        return self._target(relative).is_file()

    def delete(self, relative: str | None) -> None:
        if not relative:
            return
        target = self._target(relative)
        if target.is_file():
            target.unlink()

    def delete_tree(self, relative: str | Path) -> None:
        target = self._target(relative)
        if target == self.root:
            raise ValueError("Refusing to delete the asset root")
        if target.is_dir():
            shutil.rmtree(target)
        elif target.is_file():
            target.unlink()

    def delete_many_best_effort(self, relatives: list[str | None]) -> None:
        for relative in dict.fromkeys(value for value in relatives if value):
            try:
                self.delete(relative)
            except OSError:
                # DB state is already committed. An orphan is safer than a dangling DB reference.
                continue

    def delete_trees_best_effort(self, relatives: list[str | Path]) -> None:
        for relative in dict.fromkeys(relatives):
            try:
                self.delete_tree(relative)
            except OSError:
                continue

    def resolve(self, relative: str) -> Path:
        target = self._target(relative)
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Asset not found")
        return target


def get_asset_store() -> AssetStore:
    return AssetStore(settings.asset_root)
