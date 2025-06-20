# app/api/items_router.py (ACTUALIZADO)

from fastapi import APIRouter, HTTPException, status
from typing import List, Optional
from pathlib import Path
import json
import logging
from uuid import UUID

from app.pipelines.runner import run
from app.schemas.item_schemas import (
    UserGenerateParams,       # Importamos directamente los parámetros del usuario
    ItemPayloadSchema,        # Para el payload de cada ítem
    ReportEntrySchema,        # Para errores y advertencias
    AuditEntrySchema          # Para el historial de auditoría
)
from app.schemas.models import Item # Solo para type hints en la respuesta del runner
from pydantic import BaseModel, Field # Para definir el esquema de respuesta de la API

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/items", tags=["items"])
PIPELINE_PATH = Path(__file__).parents[2] / "pipeline.yml"

# --- Esquemas de entrada y salida para la API ---

# `GenerationRequest` ahora hereda de `UserGenerateParams` y añade `n_items`
class GenerationRequest(UserGenerateParams):
    cantidad: int = Field(..., alias="n_items", gt=0, description="Número de ítems a generar")

    class Config:
        populate_by_name = True # Permite usar el alias 'n_items' en la entrada JSON

# Esquema para la respuesta individual de cada ítem en la API
class ItemAPIOutput(BaseModel):
    item_id: UUID = Field(..., description="ID temporal del ítem utilizado durante el pipeline")
    status: str = Field(..., description="Estado final del ítem al salir del pipeline")
    payload: Optional[ItemPayloadSchema] = Field(None, description="Contenido completo del ítem si fue generado y validado")
    errors: List[ReportEntrySchema] = Field(default_factory=list, description="Lista de errores detectados en el ítem")
    warnings: List[ReportEntrySchema] = Field(default_factory=list, description="Lista de advertencias para el ítem")
    audits: List[AuditEntrySchema] = Field(default_factory=list, description="Historial de auditoría del procesamiento del ítem")
    token_usage: Optional[int] = Field(None, description="Número de tokens consumidos por el ítem en las etapas LLM (distribuido)")

    # Podrías añadir un campo para el DB ID si el persistencia ya lo devuelve aquí.
    # db_id: Optional[UUID] = None

# Esquema para la respuesta global de la API para la generación de ítems
class GenerateItemsAPIResponse(BaseModel):
    success: bool = Field(..., description="Indica si la operación de pipeline fue exitosa en general")
    total_tokens_used: int = Field(..., description="Total de tokens consumidos por todas las etapas LLM en el pipeline")
    results: List[ItemAPIOutput] = Field(..., description="Resultados individuales para cada ítem procesado")

# --- Rutas de la API ---

@router.post(
    "/generate",
    response_model=GenerateItemsAPIResponse,
    summary="Generar ítems de opción múltiple",
    description="Inicia un pipeline para generar ítems basados en los parámetros proporcionados y devuelve el estado de cada uno."
)
async def generate_items(request: GenerationRequest):
    logger.info(f"Received generation request for {request.cantidad} items.")

    # Convertir `n_items` de `GenerationRequest` a `cantidad` para `UserGenerateParams`
    # y construir el objeto UserGenerateParams para el runner
    user_params = UserGenerateParams(
        tipo_generacion=request.tipo_generacion,
        cantidad=request.cantidad,
        idioma_item=request.idioma_item,
        area=request.area,
        asignatura=request.asignatura,
        tema=request.tema,
        contexto_regional=request.contexto_regional,
        nivel_destinatario=request.nivel_destinatario,
        nivel_cognitivo=request.nivel_cognitivo,
        dificultad_prevista=request.dificultad_prevista,
        parametro_irt_b=request.parametro_irt_b,
        referencia_curricular=request.referencia_curricular,
        habilidad_evaluable=request.habilidad_evaluable,
        tipo_reactivo=request.tipo_reactivo,
        fragmento_contexto=request.fragmento_contexto,
        recurso_visual=request.recurso_visual,
        estimulo_compartido=request.estimulo_compartido,
        especificaciones_por_item=request.especificaciones_por_item
    )

    try:
        # El runner ahora inicializa los ítems basados en user_params.cantidad
        final_items: List[Item]
        pipeline_ctx: Dict
        final_items, pipeline_ctx = await run(str(PIPELINE_PATH), user_params)

        total_tokens_used = pipeline_ctx.get("usage_tokens_total", 0)

        # Construir la lista de resultados para la respuesta de la API
        results_for_api: List[ItemAPIOutput] = []
        all_successful = True

        for item in final_items:
            # Si el ítem llega a un estado de fallo persistente, se marca como no exitoso.
            # Define aquí qué estados de 'status' consideras un 'éxito' para la API
            if item.status in ["fatal_error",
                               "failed_hard_validation_after_retries",
                               "failed_logic_validation_after_retries",
                               "failed_policy_validation_after_retries",
                               "final_failed_validation",
                               "generation_failed"]: # Añadir más estados de fallo si es necesario
                all_successful = False

            results_for_api.append(
                ItemAPIOutput(
                    item_id=item.temp_id,
                    status=item.status,
                    payload=item.payload, # El payload puede estar ausente si la generación falló
                    errors=item.errors,
                    warnings=item.warnings,
                    audits=item.audits,
                    token_usage=item.token_usage
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

# Puedes mantener otras rutas existentes si las hay, ej. /items/{item_id} para obtener un ítem por ID
# @router.get("/{item_id}", response_model=ItemOut)
# async def get_item(item_id: str):
#     # Aquí iría la lógica para recuperar un ítem de la BD
#     pass
