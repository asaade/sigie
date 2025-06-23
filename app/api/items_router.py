# app/api/items_router.py

import logging
from typing import List, Optional
from uuid import UUID
from pathlib import Path
from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.pipelines.runner import run
from app.schemas.item_schemas import (
    UserGenerateParams,
    ItemPayloadSchema,
    ReportEntrySchema,
    AuditEntrySchema,
    # GenerationResponse # Asumiendo que se añadió en el paso anterior
)
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/items", tags=["items"])
PIPELINE_PATH = Path(__file__).parents[2] / "pipeline.yml"

class ItemAPIOutput(BaseModel):
    item_id: UUID
    status: str
    payload: Optional[ItemPayloadSchema] = None
    errors: List[ReportEntrySchema]
    warnings: List[ReportEntrySchema]
    audits: List[AuditEntrySchema]
    token_usage: Optional[int]
    db_id: Optional[UUID] = None

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
        # La llamada al runner es la misma, pero el input 'request' ahora es directamente UserGenerateParams
        final_items, pipeline_ctx = await run(str(PIPELINE_PATH), request, ctx={"db": db})

        total_tokens_used = pipeline_ctx.get("usage_tokens_total", 0)

        # Lógica de éxito mejorada: es exitoso si NINGÚN ítem terminó en un estado de fallo.
        all_successful = not any(
            item.status.endswith((".fail", ".error")) for item in final_items
        )

        results_for_api = [
            ItemAPIOutput(
                item_id=item.temp_id,
                status=item.status,
                payload=item.payload,
                errors=item.errors,
                warnings=item.warnings,
                audits=item.audits,
                token_usage=item.token_usage,
                db_id=item.item_id
            ) for item in final_items
        ]

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
