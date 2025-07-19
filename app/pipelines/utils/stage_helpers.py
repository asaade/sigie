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
    tokens_used: Optional[int] = None, # NUEVO: Parámetro para tokens
    duration_ms: Optional[int] = None, # NUEVO: Parámetro para duración
    codes_found: Optional[List[str]] = None,
):
    """
    Función centralizada para actualizar el estado de un ítem y añadir una
    entrada a su 'revision_log', ahora con metadatos completos.
    """
    # Si no se pasa una duración explícita, se intenta calcular desde el log anterior.
    calculated_duration = duration_ms
    if calculated_duration is None and item.audits:
        last_timestamp = item.audits[-1].timestamp
        # Se usa .replace(tzinfo=None) para evitar errores de timezone awareness
        calculated_duration = int((datetime.utcnow() - last_timestamp.replace(tzinfo=None)).total_seconds() * 1000)

    log_entry = RevisionLogEntry(
        stage_name=stage_name,
        timestamp=datetime.utcnow(),
        status=status,
        comment=comment,
        duration_ms=calculated_duration,
        tokens_used=tokens_used,
        codes_found=codes_found,
    )

    item.status = status
    item.status_comment = f"[{stage_name}]: {status.value}"
    item.audits.append(log_entry)

    if item.payload and hasattr(item.payload, 'revision_log'):
        item.payload.revision_log.append(log_entry)

    # El log del servidor ahora es más informativo
    log_message_for_server = f"Item {item.temp_id}: {status.value} en '{stage_name}'. Dur: {calculated_duration}ms, Tokens: {tokens_used}, Códigos: {codes_found}. Detalle: {comment}"
    if status == ItemStatus.FATAL:
        logger.error(log_message_for_server)
    else:
        logger.info(log_message_for_server)


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
