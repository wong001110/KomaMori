from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str = os.getenv("KOMAMORI_DATABASE_URL", "sqlite:///./data/komamori.db")
    asset_root: Path = Path(os.getenv("KOMAMORI_ASSET_ROOT", "./assets"))
    cors_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv("KOMAMORI_CORS_ORIGINS", "http://localhost:5173").split(",")
        if origin.strip()
    )


settings = Settings()
