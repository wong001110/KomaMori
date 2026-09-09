from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np
import pytesseract
from PIL import Image


@dataclass(frozen=True, slots=True)
class DetectedRegion:
    geometry: list[list[float]]
    text: str
    confidence: float | None


class OCRProvider(Protocol):
    def read(self, image: Image.Image) -> tuple[str, float | None]: ...


class TesseractOCRProvider:
    def __init__(self, language: str = "jpn+jpn_vert") -> None:
        self.language = language

    def _language_for(self, image: Image.Image) -> str:
        width, height = image.size
        return "jpn_vert" if height > width * 1.35 and "jpn" in self.language else self.language

    def read(self, image: Image.Image) -> tuple[str, float | None]:
        lang = self._language_for(image)
        config = "--psm 6"
        text = pytesseract.image_to_string(image, lang=lang, config=config).strip()
        data = pytesseract.image_to_data(image, lang=lang, config=config, output_type=pytesseract.Output.DICT)
        confidences: list[float] = []
        for token, raw_confidence in zip(data.get("text", []), data.get("conf", []), strict=False):
            if not str(token).strip():
                continue
            try:
                value = float(raw_confidence)
            except (TypeError, ValueError):
                continue
            if value >= 0:
                confidences.append(min(max(value / 100.0, 0.0), 1.0))
        confidence = sum(confidences) / len(confidences) if confidences else None
        return text, confidence


class MangaOCRProvider:
    def __init__(self) -> None:
        try:
            from manga_ocr import MangaOcr  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("MangaOCR provider requested but the optional manga-ocr package is not installed") from exc

        self._ocr = MangaOcr()

    def read(self, image: Image.Image) -> tuple[str, float | None]:
        return str(self._ocr(image)).strip(), None


def get_ocr_provider() -> OCRProvider:
    provider = os.getenv("KOMAMORI_OCR_PROVIDER", "tesseract").lower()
    if provider == "mangaocr":
        return MangaOCRProvider()
    return TesseractOCRProvider(os.getenv("KOMAMORI_TESSERACT_LANG", "jpn+jpn_vert"))


def detect_text_boxes(image: Image.Image) -> list[tuple[int, int, int, int]]:
    rgb = np.array(image.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    binary = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        15,
    )
    height, width = gray.shape
    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (max(3, width // 140), max(3, height // 100)),
    )
    joined = cv2.dilate(binary, kernel, iterations=2)
    contours, _ = cv2.findContours(joined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    page_area = width * height
    boxes: list[tuple[int, int, int, int]] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        if area < page_area * 0.00015 or area > page_area * 0.18:
            continue
        if w < 8 or h < 8:
            continue
        pad = max(3, int(min(w, h) * 0.08))
        boxes.append((max(0, x - pad), max(0, y - pad), min(width, x + w + pad), min(height, y + h + pad)))

    boxes.sort(key=lambda box: (box[1] // max(40, height // 12), -box[0], box[1]))
    return boxes


def analyze_page(image_path: Path, ocr: OCRProvider) -> list[DetectedRegion]:
    with Image.open(image_path) as source:
        image = source.convert("RGB")
        results: list[DetectedRegion] = []
        for x1, y1, x2, y2 in detect_text_boxes(image):
            crop = image.crop((x1, y1, x2, y2))
            text, confidence = ocr.read(crop)
            if not text:
                continue
            results.append(
                DetectedRegion(
                    geometry=[[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
                    text=text,
                    confidence=confidence,
                )
            )
        return results


def _polygon_mask(shape: tuple[int, int], geometry: list[list[float]]) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    if len(geometry) < 3:
        return mask
    points = np.array([[int(p[0]), int(p[1])] for p in geometry if len(p) >= 2], dtype=np.int32)
    if len(points) < 3:
        return mask
    cv2.fillPoly(mask, [points], 255)
    return mask


def generate_text_mask(image_path: Path, geometry: list[list[float]], output_path: Path) -> Path:
    source = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if source is None:
        raise ValueError(f"Unable to read image: {image_path}")
    gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
    region_mask = _polygon_mask(gray.shape, geometry)
    dark = cv2.inRange(gray, 0, 145)
    text_mask = cv2.bitwise_and(dark, region_mask)
    text_mask = cv2.dilate(text_mask, np.ones((3, 3), np.uint8), iterations=1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), text_mask):
        raise ValueError(f"Unable to write mask image: {output_path}")
    return output_path


def generate_clean_page(image_path: Path, mask_paths: list[Path], output_path: Path) -> Path:
    source = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if source is None:
        raise ValueError(f"Unable to read image: {image_path}")
    total_mask = np.zeros(source.shape[:2], dtype=np.uint8)

    for mask_path in mask_paths:
        mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
        if mask is None:
            raise ValueError(f"Unable to read mask image: {mask_path}")
        if mask.shape != total_mask.shape:
            raise ValueError(f"Mask dimensions do not match page: {mask_path}")
        total_mask = cv2.bitwise_or(total_mask, mask)

    cleaned = source if not np.any(total_mask) else cv2.inpaint(source, total_mask, 3, cv2.INPAINT_TELEA)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), cleaned):
        raise ValueError(f"Unable to write clean image: {output_path}")
    return output_path
