# app/pipelines/builtins/validate_soft.py

import logging
from typing import List, Dict, Any

from ..registry import register
from app.schemas.models import Item
from app.schemas.item_schemas import ReportEntrySchema
from app.validators.soft import soft_validate # Importamos la función de validación suave local
from ..utils.stage_helpers import skip_if_terminal_error, add_audit_entry # Importamos helpers

logger = logging.getLogger(__name__)

@register("validate_soft")
async def validate_soft_stage(items: List[Item], ctx: Dict[str, Any]) -> List[Item]:
    """
    Etapa de validación "suave" de ítems.
    Aplica reglas de estilo y formato localmente, generando advertencias. No usa LLM.
    """
    stage_name = "validate_soft"

    logger.info(f"Starting soft validation for {len(items)} items.")

    for item in items:
        # Saltar ítems que ya están en un estado de error terminal
        if skip_if_terminal_error(item, stage_name):
            continue

        # Asegurarse de que el ítem tenga un payload para validar
        if not item.payload:
            # Aunque la validación dura debería haber capturado esto, es un chequeo defensivo.
            item.status = "soft_validation_skipped_no_payload"
            item.errors.append( # Esto sería un error, no una advertencia, si no hay payload
                ReportEntrySchema(
                    code="NO_PAYLOAD_FOR_SOFT_VALIDATION",
                    message="El ítem no tiene un payload para validar el estilo.",
                    severity="error"
                )
            )
            add_audit_entry(
                item=item,
                stage_name=stage_name,
                summary="Saltado: no hay payload de ítem para validar el estilo."
            )
            logger.warning(f"Item {item.temp_id} skipped in {stage_name}: no payload.")
            continue

        # Las validaciones suaves de soft.py esperan un dict, no un objeto Pydantic
        # Convertimos el payload a dict para pasarlo a soft_validate
        item_dict_payload = item.payload.model_dump(by_alias=True)

        # Ejecutar las validaciones suaves locales
        soft_warnings_raw = soft_validate(item_dict_payload)

        current_warnings: List[ReportEntrySchema] = []
        for warning_data in soft_warnings_raw:
            # Convertir los diccionarios de soft_validate a ReportEntrySchema
            current_warnings.append(
                ReportEntrySchema(
                    code=warning_data.get("warning_code", "UNKNOWN_SOFT_WARNING"),
                    message=warning_data.get("message", "Advertencia de estilo no especificada."),
                    field=warning_data.get("field"), # soft.py no siempre da 'field', pero lo incluimos
                    severity="warning" # Por definición, son advertencias
                )
            )

        # Añadir las advertencias al ítem
        item.warnings.extend(current_warnings)

        # Actualizar el estado del ítem y la auditoría
        summary_msg = f"Validación suave: OK. {len(current_warnings)} advertencias detectadas."

        # La validación suave NO cambia el estado a "fallido" si solo hay advertencias.
        # Si el ítem ya está en un estado de éxito (ej. logic_validated), lo mantenemos.
        # Si tiene errores previos más graves, su estado no debería cambiar.
        if item.status not in ["failed_logic_validation", "failed_hard_validation"]: # No sobrescribir fallos graves
             item.status = "soft_validated" # Nuevo estado para indicar que pasó por esta etapa

        add_audit_entry(
            item=item,
            stage_name=stage_name,
            summary=summary_msg
        )
        logger.info(f"Item {item.temp_id} soft validation result: {item.status}, {len(current_warnings)} warnings.")

    logger.info(f"Soft validation completed for {len(items)} items.")
    return items
