# app/api/items_router.py

from fastapi import APIRouter, HTTPException, status
from typing import List, Optional, Dict # Eliminar 'Dict' si no se usa directamente en firmas
from pathlib import Path
import logging
from uuid import UUID

from app.pipelines.runner import run
from app.schemas.item_schemas import (
    UserGenerateParams,
    ItemPayloadSchema,
    ReportEntrySchema,
    AuditEntrySchema
)
from app.schemas.models import Item
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/items", tags=["items"])
PIPELINE_PATH = Path(__file__).parents[2] / "pipeline.yml"

class GenerationRequest(UserGenerateParams):
    cantidad: int = Field(..., alias="n_items", gt=0, description="Número de ítems a generar")

    class Config:
        populate_by_name = True

class ItemAPIOutput(BaseModel):
    item_id: UUID = Field(..., description="ID temporal del ítem utilizado durante el pipeline")
    status: str = Field(..., description="Estado final del ítem al salir del pipeline")
    payload: Optional[ItemPayloadSchema] = Field(None, description="Contenido completo del ítem si fue generado y validado")
    errors: List[ReportEntrySchema] = Field(default_factory=list, description="Lista de errores detectados en el ítem")
    warnings: List[ReportEntrySchema] = Field(default_factory=list, description="Lista de advertencias para el ítem")
    audits: List[AuditEntrySchema] = Field(default_factory=list, description="Historial de auditoría del procesamiento del ítem")
    token_usage: Optional[int] = Field(None, description="Número de tokens consumidos por el ítem en las etapas LLM (distribuido)")
    db_id: Optional[UUID] = Field(None, description="ID definitivo del ítem en la base de datos, si fue persistido.")

class GenerateItemsAPIResponse(BaseModel):
    success: bool = Field(..., description="Indica si la operación de pipeline fue exitosa en general")
    total_tokens_used: int = Field(..., description="Total de tokens consumidos por todas las etapas LLM en el pipeline")
    results: List[ItemAPIOutput] = Field(..., description="Resultados individuales para cada ítem procesado")

@router.post(
    "/generate",
    response_model=GenerateItemsAPIResponse,
    summary="Generar ítems de opción múltiple",
    description="Inicia un pipeline para generar ítems basados en los parámetros proporcionados y devuelve el estado de cada uno."
)
async def generate_items(request: GenerationRequest):
    logger.info(f"Received generation request for {request.cantidad} items.")

    # --- INICIO DE LA MODIFICACIÓN CRÍTICA ---
    # Simplificar la creación de user_params para que Pydantic maneje el alias 'n_items'
    # request.model_dump(by_alias=True) convertirá 'cantidad' a 'n_items'
    # y UserGenerateParams lo validará correctamente.
    user_params = UserGenerateParams.model_validate(request.model_dump(by_alias=True))
    # --- FIN DE LA MODIFICACIÓN CRÍTICA ---

    try:
        final_items: List[Item]
        pipeline_ctx: Dict
        final_items, pipeline_ctx = await run(str(PIPELINE_PATH), user_params)

        total_tokens_used = pipeline_ctx.get("usage_tokens_total", 0)

        results_for_api: List[ItemAPIOutput] = []
        all_successful = True

        for item in final_items:
            if item.status in ["fatal_error",
                               "failed_hard_validation_after_retries",
                               "failed_logic_validation_after_retries",
                               "failed_policy_validation_after_retries",
                               "final_failed_validation",
                               "generation_failed",
                               "llm_generation_failed",
                               "generation_validation_failed",
                               "generation_failed_mismatch",
                               "persistence_failed_db_error",
                               "persistence_failed_unexpected_error",
                               "final_error_on_persist_stage"
                               ]:
                all_successful = False

            results_for_api.append(
                ItemAPIOutput(
                    item_id=item.temp_id,
                    status=item.status,
                    payload=item.payload,
                    errors=item.errors,
                    warnings=item.warnings,
                    audits=item.audits,
                    token_usage=item.token_usage,
                    db_id=item.item_id
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
