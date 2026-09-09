from __future__ import annotations

import re
from dataclasses import dataclass

CJK_RE = re.compile(r"[\u3000-\u30ff\u3400-\u9fff\uf900-\ufaff\uac00-\ud7af]")


@dataclass(frozen=True, slots=True)
class FitResult:
    font_size: int
    lines: list[str]
    status: str
    recommended_max_chars: int | None = None


def bounding_box(geometry: list[list[float]]) -> tuple[float, float]:
    if len(geometry) < 2:
        return 180.0, 120.0
    xs = [point[0] for point in geometry if len(point) >= 2]
    ys = [point[1] for point in geometry if len(point) >= 2]
    if not xs or not ys:
        return 180.0, 120.0
    return max(max(xs) - min(xs), 24.0), max(max(ys) - min(ys), 24.0)


def _tokens(text: str) -> list[str]:
    if CJK_RE.search(text) and " " not in text.strip():
        return list(text.strip())
    return text.strip().split()


def _wrap(text: str, chars_per_line: int) -> list[str]:
    tokens = _tokens(text)
    if not tokens:
        return [""]
    if CJK_RE.search(text) and " " not in text.strip():
        return ["".join(tokens[index : index + chars_per_line]) for index in range(0, len(tokens), chars_per_line)]

    lines: list[str] = []
    current = ""
    for token in tokens:
        candidate = token if not current else f"{current} {token}"
        if len(candidate) <= chars_per_line or not current:
            current = candidate
        else:
            lines.append(current)
            current = token
    if current:
        lines.append(current)
    return lines


def auto_fit(
    text: str,
    geometry: list[list[float]],
    *,
    min_font_size: int = 14,
    max_font_size: int = 48,
    padding_ratio: float = 0.10,
) -> FitResult:
    width, height = bounding_box(geometry)
    width *= 1 - padding_ratio * 2
    height *= 1 - padding_ratio * 2
    is_cjk = bool(CJK_RE.search(text))
    glyph_ratio = 1.0 if is_cjk else 0.56

    for size in range(max_font_size, min_font_size - 1, -1):
        chars_per_line = max(1, int(width / max(size * glyph_ratio, 1)))
        lines = _wrap(text, chars_per_line)
        required_height = len(lines) * size * 1.22
        if required_height <= height:
            return FitResult(font_size=size, lines=lines, status="fit")

    chars_per_line = max(1, int(width / max(min_font_size * glyph_ratio, 1)))
    max_lines = max(1, int(height / (min_font_size * 1.22)))
    recommended = max(1, chars_per_line * max_lines)
    lines = _wrap(text, chars_per_line)
    return FitResult(
        font_size=min_font_size,
        lines=lines,
        status="poor-fit",
        recommended_max_chars=recommended,
    )


def layout_payload(text: str, geometry: list[list[float]]) -> dict[str, object]:
    result = auto_fit(text, geometry)
    return {
        "fontFamily": "system-ui",
        "fontSize": result.font_size,
        "lineHeight": 1.22,
        "letterSpacing": 0,
        "alignment": "center",
        "rotation": 0,
        "fittedLines": result.lines,
        "fitStatus": result.status,
        "recommendedMaxChars": result.recommended_max_chars,
        "manualOverride": False,
    }
