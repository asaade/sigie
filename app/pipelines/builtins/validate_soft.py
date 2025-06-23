# Archivo actualizado: app/pipelines/builtins/validate_soft.py

from __future__ import annotations
import logging
from typing import List, Dict, Any

from ..registry import register
from app.schemas.models import Item
from app.schemas.item_schemas import ReportEntrySchema
from app.validators.soft import soft_validate # Llama a la lógica en el otro archivo
from ..utils.stage_helpers import skip_if_terminal_error, handle_missing_payload, add_audit_entry

logger = logging.getLogger(__name__)

@register("validate_soft")
async def validate_soft_stage(items: List[Item], ctx: Dict[str, Any]) -> List[Item]:
    """
    Realiza una validación "suave" (estilística) de los ítems.
    """
    stage_name = "validate_soft"
    logger.info(f"Starting soft validation for {len(items)} items.")

    for item in items:
        # Se omite si ya falló en una etapa crítica anterior.
        if item.status.endswith('.fail'):
            logger.debug(f"Skipping item {item.temp_id} in {stage_name} due to prior failure status: {item.status}")
            continue

        if not item.payload:
            # Usamos add_audit_entry porque la falta de payload no es un fallo crítico aquí
            add_audit_entry(item, stage_name, "Skipped: No payload for soft validation.")
            continue

        item_dict_payload = item.payload.model_dump()

        # La lógica de validación real está en app/validators/soft.py
        soft_findings_raw = soft_validate(item_dict_payload)

        current_findings: List[ReportEntrySchema] = [
            ReportEntrySchema(
                code=finding.get("warning_code", "UNKNOWN_SOFT_FINDING"),
                message=finding.get("message", "Advertencia de estilo no especificada."),
                field=finding.get("field"),
                severity="warning" # Todos los hallazgos de esta etapa son advertencias
            )
            for finding in soft_findings_raw
        ]

        # ▼▼▼ LÓGICA DE ACTUALIZACIÓN ALINEADA ▼▼▼
        if current_findings:
            item.findings.extend(current_findings)
            summary = f"Soft validation completed. {len(current_findings)} warnings issued."
            add_audit_entry(item, stage_name, summary)
            logger.info(f"Item {item.temp_id} received {len(current_findings)} style warnings.")
        else:
            add_audit_entry(item, stage_name, "Soft validation completed. No issues found.")

    logger.info("Soft validation completed for all items.")
    return items
