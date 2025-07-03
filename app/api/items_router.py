# app/api/items_router.py

import logging
from typing import List, Optional, Dict
from uuid import UUID
from pathlib import Path
from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.pipelines.runner import run as run_pipeline
from app.schemas.item_schemas import (
    UserGenerateParams,
    ItemPayloadSchema,
    ReportEntrySchema,
    AuditEntrySchema,
    FinalEvaluationSchema
)
from app.schemas.models import Item # Para type hints
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/items", tags=["items"])
PIPELINE_PATH = Path(__file__).parents[2] / "pipeline.yml"

class ItemAPIOutput(BaseModel):
    # item_id ya es el ID principal del ítem. Será el mismo que la PK en la DB.
    item_id: UUID # Originalmente era item.temp_id, pero se cambió a item.item_id en discusión previa.

    status: str
    payload: Optional[ItemPayloadSchema] = None
    findings: List[ReportEntrySchema] = Field(default_factory=list, description="Lista unificada de hallazgos (errores y advertencias) para el ítem.")
    audits: List[AuditEntrySchema] = Field(default_factory=list, description="Historial de auditoría del procesamiento del ítem")
    token_usage: Optional[int] = None
    # CAMBIO AQUÍ: Eliminar db_id
    # db_id: Optional[UUID] = Field(None, description="ID de DB definitivo") # ELIMINADO: item_id ya es la PK en DB.
    final_evaluation: Optional[FinalEvaluationSchema] = Field(None, description="Evaluación final de calidad del ítem.")

class GenerateItemsAPIResponse(BaseModel):
    success: bool
    total_tokens_used: int
    results: List[ItemAPIOutput]

@router.post(
    "/generate",
    response_model=GenerateItemsAPIResponse,
    summary="Generar ítems de opción múltiple",
    description="Inicia un pipeline para generar ítems basados en los parámetros proporcionados y devuelve el estado de cada uno."
)
async def generate_items(request: UserGenerateParams, db: Session = Depends(get_db)):
    logger.info(f"Received generation request for {request.n_items} items.")

    try:
        final_items: List[Item]
        pipeline_ctx: Dict
        final_items, pipeline_ctx = await run_pipeline(str(PIPELINE_PATH), request, ctx={"db": db})

        total_tokens_used = pipeline_ctx.get("usage_tokens_total", 0)

        all_successful = not any(
            item.status.endswith((".fail", ".error")) for item in final_items
        )

        results_for_api: List[ItemAPIOutput] = []
        for item in final_items:
            results_for_api.append(
                ItemAPIOutput(
                    item_id=item.item_id, # Asignar item.item_id como el ID principal de la API
                    status=item.status,
                    payload=item.payload,
                    findings=item.findings,
                    audits=item.audits,
                    token_usage=item.token_usage,
                    # db_id=item.db_id, # ELIMINADO: Ya no existe en ItemAPIOutput ni en Item Pydantic
                    final_evaluation=item.final_evaluation
                )
            )

        return GenerateItemsAPIResponse(
            success=all_successful,
            total_tokens_used=total_tokens_used,
            results=results_for_api
        )

    except Exception as e:
        logger.exception(f"Pipeline execution failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error durante la ejecución del pipeline: {e}"
        )
