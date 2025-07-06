# app/pipelines/utils/stage_helpers.py

from datetime import datetime
from typing import List, Dict, Any, Optional
import uuid
import logging

from app.schemas.models import Item, ItemStatus
from app.schemas.item_schemas import (
    AuditEntrySchema,
    ReportEntrySchema,
    CorrectionSchema, # Still refers to the schema type
    ItemGenerationParams,
    ValidationResultSchema,
)
from app.core.log import logger


# ---------------------------------------------------------------------------
# Funciones Helper Esenciales para el Pipeline
# ---------------------------------------------------------------------------


def skip_if_terminal_error(item: Item, stage_name: str) -> bool:
    """
    Verifica si un ítem ya está en un estado fatal y, si es así,
    añade una entrada de auditoría y retorna True para omitirlo.
    """
    # Compare string values of ItemStatus.value
    if item.status == ItemStatus.FATAL.value or item.status == ItemStatus.SKIPPED_DUE_TO_FATAL_PRIOR.value:
        summary = f"Saltado: Ítem ya en estado terminal ('{item.status}')."
        add_audit_entry(
            item=item, stage_name=stage_name, status=ItemStatus.FATAL, summary=summary
        )
        return True
    return False


def handle_missing_payload(item: Item, stage_name: str):
    """
    Maneja el caso donde el payload del ítem está ausente, marcándolo como fatal.
    """
    summary = "Error Crítico: El payload del ítem está ausente y es requerido para esta etapa."
    finding = ReportEntrySchema(
        code="E952_NO_PAYLOAD", message=summary, severity=ItemStatus.FATAL.value
    )
    item.findings.append(finding)
    update_item_status_and_audit(item, stage_name, ItemStatus.FATAL, summary)
    logger.warning(f"Item {item.temp_id} marcado como FATAL en {stage_name}: {summary}")


def initialize_items_for_pipeline(params: Dict[str, Any]) -> List[Item]:
    """
    Inicializa una lista de objetos Item para ser procesados por el pipeline.
    Asegura que cada Item nuevo tenga un item_id único generado por la aplicación.
    """
    try:
        gen_params = ItemGenerationParams.model_validate(params)
    except Exception as e:
        logger.error(
            f"Error al validar los parámetros de generación: {e}", exc_info=True
        )
        return []

    items_to_process: List[Item] = []
    batch_id = str(uuid.uuid4())

    for i in range(gen_params.n_items):
        new_item = Item(
            batch_id=batch_id,
            status=ItemStatus.PENDING.value,
            generation_params=gen_params.model_dump(mode="json"),
            payload=None,
            findings=[],
            audits=[],
        )
        items_to_process.append(new_item)

    logger.info(f"Initialized {len(items_to_process)} items for pipeline, batch_id: {batch_id}.")
    return items_to_process


def add_audit_entry(
    item: Item,
    stage_name: str,
    status: ItemStatus, # Status is an Enum member
    summary: str,
    # --- FIX: Change parameter name to correcciones ---
    correcciones: Optional[List[CorrectionSchema]] = None,
    # --- END FIX ---
):
    """Añade una entrada de auditoría al log del ítem."""
    audit_entry = AuditEntrySchema(
        stage=stage_name,
        timestamp=datetime.utcnow(),
        summary=summary,
        correcciones=correcciones or [],
    )
    item.audits.append(audit_entry)


def update_item_status_and_audit(
    item: Item,
    stage_name: str,
    status: ItemStatus, # This 'status' is an ItemStatus Enum member
    summary: str,
    # --- FIX: Change parameter name to correcciones ---
    correcciones: Optional[List[CorrectionSchema]] = None,
    # --- END FIX ---
):
    """
    Actualiza el estado de un ítem y registra una entrada en su log de auditoría.
    """
    # Ensure item.status (string field) gets the string value of the Enum
    item.status = status.value
    audit_entry = AuditEntrySchema(
        stage=stage_name,
        timestamp=datetime.now(),
        summary=summary,
        correcciones=correcciones or [],
    )
    item.audits.append(audit_entry)

    # Log the summary message to the console if the item status is FATAL
    if status == ItemStatus.FATAL: # This comparison is Enum to Enum
        logger.error(f"Item {item.temp_id} in stage '{stage_name}' FAILED: {summary}")


def create_report_entry(
    code: str,
    severity: str,
    message: str,
    component_id: Optional[str] = None,
) -> ReportEntrySchema:
    """Crea una entrada de reporte estandarizada."""
    return ReportEntrySchema(
        code=code, severity=severity, message=message, component_id=component_id
    )


def clean_specific_errors(item: Item, error_codes_to_remove: set[str]):
    """Elimina findings específicos de un ítem."""
    item.findings = [f for f in item.findings if f.code not in error_codes_to_remove]


def get_error_message_from_validation_result(
    result: ValidationResultSchema, context: str
) -> str:
    """Genera un mensaje de resumen a partir de un resultado de validación."""
    error_codes = ", ".join([f.code for f in result.findings])
    return f"Validación de {context}: FALLÓ con los siguientes códigos: {error_codes}"


def handle_item_id_mismatch_refinement(
    item: Item, stage_name: str, expected_id: str, actual_id: str
) -> bool:
    """Maneja el caso de un mismatch de ID en una etapa de refinamiento."""
    if actual_id != expected_id:
        msg = f"Error Crítico: El ID del ítem en la respuesta del LLM ('{actual_id}') no coincide con el esperado ('{expected_id}')."
        update_item_status_and_audit(item, stage_name, ItemStatus.FATAL, msg)
        return True
    return False
