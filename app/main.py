# app/main.py (VERIFICAR Y MANTENER)

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import ORJSONResponse

from app.db.session import init_db # Asegúrate de que esta línea esté correcta
from app.api.items_router import router as items_router

# ───────────────────────────────────────────── logging
# Es bueno centralizar la configuración de logging. Esta es una buena base.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("sigie.main") # Logger específico para main

app = FastAPI(
    title="SIGIE – Generador de Ítems MCQ",
    version="2025.06",
    default_response_class=ORJSONResponse,
)

app.add_middleware(GZipMiddleware, minimum_size=1024)

# ───────────────────────────────────────────── lifecycle
@app.on_event("startup")
async def on_startup() -> None:
    init_db() # Inicializa la base de datos
    pipeline_path = Path(__file__).parents[1] / "pipeline.yml"
    log.info("🚀 Pipeline activo: %s", pipeline_path.resolve())

@app.on_event("shutdown")
async def on_shutdown() -> None:
    log.info("👋  API apagándose…")

# ───────────────────────────────────────────── routers
app.include_router(items_router) # Se asegura de que el router de ítems esté incluido

# ───────────────────────────────────────────── health
@app.get("/health", tags=["meta"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
