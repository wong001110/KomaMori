from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import HTTPException

TRANSLATION_PROMPT_VERSION = "manga-region-v1"
TRANSLATION_TEMPERATURE = 0.2
TRANSLATION_PROVENANCE_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class TranslationRequest:
    source_text: str
    source_language: str
    target_locale: str
    nearby_context: list[str]
    locked_terms: dict[str, str]


class TranslationProvider(Protocol):
    def translate(self, request: TranslationRequest) -> str: ...


class OpenAICompatibleTranslationProvider:
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def translate(self, request: TranslationRequest) -> str:
        terms = "\n".join(f"- {source} => {target}" for source, target in request.locked_terms.items()) or "(none)"
        context = "\n".join(request.nearby_context) or "(none)"
        prompt = (
            f"Translate one manga text region from {request.source_language} to {request.target_locale}.\n"
            "Return only the translated text. Keep the meaning natural and concise for a speech balloon.\n"
            f"Mandatory terminology:\n{terms}\n"
            f"Nearby source dialogue:\n{context}\n"
            f"Current source:\n{request.source_text}"
        )
        payload = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "You are a manga localization translator."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": TRANSLATION_TEMPERATURE,
            }
        ).encode("utf-8")
        request_object = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request_object, timeout=90) as response:
                data = json.load(response)
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=f"Translation provider failed: {exc}") from exc
        try:
            return str(data["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise HTTPException(status_code=502, detail="Translation provider returned an unexpected response") from exc


def translation_provenance(provider: TranslationProvider, request: TranslationRequest) -> dict[str, Any]:
    """Describe a machine translation without persisting credentials or full prompts."""
    result: dict[str, Any] = {
        "schema_version": TRANSLATION_PROVENANCE_SCHEMA_VERSION,
        "kind": "machine",
        "provider": "openai-compatible" if isinstance(provider, OpenAICompatibleTranslationProvider) else type(provider).__name__,
        "prompt_version": TRANSLATION_PROMPT_VERSION,
        "temperature": TRANSLATION_TEMPERATURE,
        "context_regions": len(request.nearby_context),
        "locked_term_count": len(request.locked_terms),
    }
    model = getattr(provider, "model", None)
    if model:
        result["model"] = str(model)
    return result


def get_translation_provider() -> TranslationProvider:
    base_url = os.getenv("KOMAMORI_LLM_BASE_URL")
    api_key = os.getenv("KOMAMORI_LLM_API_KEY")
    model = os.getenv("KOMAMORI_LLM_MODEL")
    if not (base_url and api_key and model):
        raise HTTPException(
            status_code=503,
            detail="Translation provider is not configured. Set KOMAMORI_LLM_BASE_URL, KOMAMORI_LLM_API_KEY and KOMAMORI_LLM_MODEL.",
        )
    return OpenAICompatibleTranslationProvider(base_url, api_key, model)
