from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import Base, engine
from .routers.library import router as library_router
from .routers.localization import router as localization_router
from .routers.processing import router as processing_router
from .routers.workbench import router as workbench_router
from .schemas import HealthResponse


@asynccontextmanager
async def lifespan(_: FastAPI):
    from . import models  # noqa: F401

    settings.asset_root.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="KomaMori API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(library_router)
app.include_router(processing_router)
app.include_router(localization_router)
app.include_router(workbench_router)


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="komamori-api")
