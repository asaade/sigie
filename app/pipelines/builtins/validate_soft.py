# app/pipelines/builtins/validate_soft.py

from __future__ import annotations
import logging
from typing import List, Dict, Any

from ..registry import register
from app.schemas.models import Item
from app.schemas.item_schemas import ReportEntrySchema
from app.validators.soft import soft_validate
from ..utils.stage_helpers import skip_if_terminal_error, add_audit_entry, handle_missing_payload, update_item_status_and_audit # Importar las nuevas funciones


logger = logging.getLogger(__name__)

@register("validate_soft")
async def validate_soft_stage(items: List[Item], ctx: Dict[str, Any]) -> List[Item]:
    """
    Etapa de validación "suave" de ítems.
    Refactorizado para usar stage_helpers.
    """
    stage_name = "validate_soft"

    logger.info(f"Starting soft validation for {len(items)} items.")

    for item in items:
        if skip_if_terminal_error(item, stage_name):
            continue

        if not item.payload:
            handle_missing_payload(
                item,
                stage_name,
                "NO_PAYLOAD_FOR_SOFT_VALIDATION",
                "El ítem no tiene un payload para validar el estilo.",
                "soft_validation_skipped_no_payload",
                "Saltado: no hay payload de ítem para validar el estilo."
            )
            continue

        item_dict_payload = item.payload.model_dump(by_alias=True)

        soft_warnings_raw = soft_validate(item_dict_payload)

        current_warnings: List[ReportEntrySchema] = []
        for warning_data in soft_warnings_raw:
            current_warnings.append(
                ReportEntrySchema(
                    code=warning_data.get("warning_code", "UNKNOWN_SOFT_WARNING"),
                    message=warning_data.get("message", "Advertencia de estilo no especificada."),
                    field=warning_data.get("field"),
                    severity="warning"
                )
            )

        item.warnings.extend(current_warnings)

        summary_msg = f"Validación suave: OK. {len(current_warnings)} advertencias detectadas."

        if item.status not in ["failed_logic_validation", "failed_hard_validation", "failed_policy_validation"]:
             update_item_status_and_audit(
                 item=item,
                 stage_name=stage_name,
                 new_status="soft_validated",
                 summary_msg=summary_msg
             )
        else: # Si el ítem ya tiene un fallo grave, solo añadir la auditoría.
            add_audit_entry(
                item=item,
                stage_name=stage_name,
                summary=summary_msg
            )
        logger.info(f"Item {item.temp_id} soft validation result: {item.status}, {len(current_warnings)} warnings.")

    logger.info(f"Soft validation completed for {len(items)} items.")
    return items
