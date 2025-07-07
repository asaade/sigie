# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# El simple acto de importar este módulo ejecutará la configuración de logging
# (dictConfig) que está definida a nivel de módulo en log.py.
from app.db.session import engine
from app.db import models
from app.api.items_router import router as items_router
from app.core.config import settings

# --- IMPORTACIÓN CRUCIAL POR EFECTO SECUNDARIO ---
# Esta importación asegura que todas las etapas del pipeline se registren
# antes de que el runner intente usarlas.
from app.pipelines import builtins

# La configuración del logging ya se ha ejecutado al importar 'app.core.log'.
# No se necesita ninguna llamada a setup_logging().

# Create database tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# Set all CORS enabled origins
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(items_router, prefix=settings.API_V1_STR)

@app.get("/")
def read_root():
    return {"message": "Welcome to the Item Generation API"}
