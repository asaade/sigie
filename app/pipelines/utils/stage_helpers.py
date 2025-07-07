# app/pipelines/utils/stage_helpers.py

from __future__ import annotations
from datetime import datetime
from typing import List, Dict, Any, Optional
import uuid

# --- CORRECCIÓN DE IMPORTACIONES ---
from app.schemas.models import Item  # El modelo principal ahora viene de aquí
from app.schemas.enums import ItemStatus # El enum de estados viene de aquí
from app.schemas.item_schemas import (
    ItemGenerationParams,
    RevisionLogEntry,
    ValidationResultSchema,
)
from app.core.log import logger

# ---------------------------------------------------------------------------
# Funciones Helper Esenciales para el Pipeline
# ---------------------------------------------------------------------------

def initialize_items_for_pipeline(params: Dict[str, Any]) -> List[Item]:
    """
    Inicializa una lista de objetos Item para ser procesados por el pipeline.
    """
    try:
        gen_params = ItemGenerationParams.model_validate(params)
    except Exception as e:
        logger.error(f"Error al validar los parámetros de generación: {e}", exc_info=True)
        return []

    items_to_process: List[Item] = []
    batch_id = str(uuid.uuid4())

    for _ in range(gen_params.n_items):
        # --- CREACIÓN DE ÍTEM SIMPLIFICADA ---
        # El modelo 'Item' ahora tiene valores por defecto para 'status', 'findings', etc.
        new_item = Item(
            batch_id=batch_id,
            generation_params=gen_params.model_dump(mode="json"),
        )
        items_to_process.append(new_item)

    logger.info(f"Initialized {len(items_to_process)} items for pipeline, batch_id: {batch_id}.")
    return items_to_process


def add_revision_log_entry(
    item: Item,
    stage_name: str,
    status: ItemStatus,
    comment: str,
):
    """
    Función centralizada para actualizar el estado de un ítem y añadir una
    entrada a su 'revision_log' en el payload.
    """
    item.status = status
    item.status_comment = f"[{stage_name}] {comment}"

    # El campo 'audits' en el modelo Item ahora se usa para el log de revisión.
    log_entry = RevisionLogEntry(
        stage_name=stage_name,
        timestamp=datetime.utcnow(),
        status=status,
        comment=comment,
    )
    item.audits.append(log_entry)

    if item.payload:
        item.payload.revision_log.append(log_entry)

    if status == ItemStatus.FATAL:
        logger.error(f"Item {item.temp_id}: {item.status_comment}")
    else:
        logger.info(f"Item {item.temp_id}: {item.status_comment}")


def handle_missing_payload(item: Item, stage_name: str) -> bool:
    """
    Maneja el caso donde el payload del ítem está ausente, marcándolo como fatal.
    Retorna True si el payload falta, False en caso contrario.
    """
    # La etapa 'generate_items' es la única que puede ejecutarse sin payload.
    if not item.payload and stage_name != "generate_items":
        comment = "Error Crítico: El payload del ítem está ausente y es requerido para esta etapa."
        add_revision_log_entry(item, stage_name, ItemStatus.FATAL, comment)
        return True
    return False


def handle_item_id_mismatch(
    item: Item, stage_name: str, expected_id: str, actual_id: Optional[str]
) -> bool:
    """
    Maneja el caso de un mismatch de ID en la respuesta de un LLM.
    Retorna True si hay un mismatch, False en caso contrario.
    """
    if not actual_id or actual_id != expected_id:
        comment = (
            f"Error Crítico: El ID en la respuesta del LLM ('{actual_id}') "
            f"no coincide con el esperado ('{expected_id}')."
        )
        add_revision_log_entry(item, stage_name, ItemStatus.FATAL, comment)
        return True
    return False


def get_error_message_from_validation_result(
    result: ValidationResultSchema, context: str
) -> str:
    """Genera un mensaje de resumen a partir de un resultado de validación."""
    error_codes = ", ".join([f.codigo_error for f in result.hallazgos])
    return f"Validación de {context}: FALLÓ con los siguientes códigos: {error_codes}"
