# app/pipelines/utils/stage_helpers.py

import logging
from typing import List, Optional

from app.schemas.models import Item
from app.schemas.item_schemas import AuditEntrySchema, ReportEntrySchema, CorrectionEntrySchema

logger = logging.getLogger(__name__)

def skip_if_terminal_error(item: Item, stage_name: str) -> bool:
    """
    Verifica si un ítem ya está en un estado de error terminal y, si es así,
    añade una entrada de auditoría y retorna True (indica que debe ser saltado).
    """
    terminal_statuses = [
        "fatal_error",
        "generation_failed",
        "llm_generation_failed",
        "generation_validation_failed",
        "generation_failed_mismatch",
        "failed_hard_validation",
        "failed_logic_validation_after_retries",
        "failed_policy_validation_after_retries",
        "refinement_failed", # Errores genéricos de refinamiento
        "refinement_parsing_failed",
        "refinement_unexpected_error",
        "final_failed_validation", # Errores de la etapa final (finalize_item)
    ]
    if item.status in terminal_statuses:
        item.audits.append(
            AuditEntrySchema(
                stage=stage_name,
                summary=f"Saltado: ítem ya en estado de error terminal previo ({item.status})."
            )
        )
        logger.debug(f"Skipping item {item.temp_id} in {stage_name} due to prior terminal error status: {item.status}")
        return True
    return False

def add_audit_entry(
    item: Item,
    stage_name: str,
    summary: str,
    corrections: Optional[List[CorrectionEntrySchema]] = None,
    errors_reported: Optional[List[ReportEntrySchema]] = None # Opcional: errores que la etapa detectó
) -> None:
    """
    Añade una entrada de auditoría al ítem.
    """
    if corrections is None:
        corrections = []
    if errors_reported is None:
        errors_reported = []

    # Se podría añadir más detalles al summary si hay errores_reported
    # o si se quiere diferenciar el summary para una etapa con/sin correcciones.

    item.audits.append(
        AuditEntrySchema(
            stage=stage_name,
            summary=summary,
            corrections=corrections
            # Podríamos añadir 'errors_reported' aquí si el esquema de AuditEntrySchema lo soporta.
            # Por ahora, los errores se añaden directamente a item.errors.
        )
    )
    logger.debug(f"Audit for item {item.temp_id} in {stage_name}: {summary}")
