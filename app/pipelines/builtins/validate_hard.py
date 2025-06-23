# Archivo actualizado: app/pipelines/builtins/validate_hard.py

from __future__ import annotations
import logging
import re
from typing import List, Dict, Any
from pydantic import ValidationError, HttpUrl

from ..registry import register
from app.schemas.models import Item
from app.schemas.item_schemas import ReportEntrySchema, ItemPayloadSchema, TipoReactivo
from ..utils.stage_helpers import skip_if_terminal_error, handle_missing_payload, update_item_status_and_audit

logger = logging.getLogger(__name__)

@register("validate_hard")
async def validate_hard_stage(items: List[Item], ctx: Dict[str, Any]) -> List[Item]:
    """
    Realiza una validación "dura" de los ítems basada en reglas programáticas.
    """
    stage_name = "validate_hard"
    logger.info(f"Starting hard validation for {len(items)} items.")

    for item in items:
        # Se omite si ya falló en una etapa crítica anterior.
        if item.status.endswith('.fail'):
            logger.debug(f"Skipping item {item.temp_id} in {stage_name} due to prior failure status: {item.status}")
            continue

        if not item.payload:
            handle_missing_payload(
                item, stage_name, "E_NO_PAYLOAD", "El ítem no tiene un payload.",
                f"{stage_name}.fail", "Saltado: no hay payload para validación dura."
            )
            continue

        current_findings: List[ReportEntrySchema] = []
        is_valid = True

        try:
            # La validación Pydantic del payload sigue siendo un primer paso crucial.
            validated_payload = ItemPayloadSchema.model_validate(item.payload.model_dump())
            item.payload = validated_payload

            # ... (Toda la lógica de validación como la tenías: correct_options, option_ids, etc.) ...
            # Por ejemplo, una de las validaciones:
            if len([opt for opt in item.payload.opciones if opt.es_correcta]) != 1:
                current_findings.append(
                    ReportEntrySchema(
                        code="E_CORRECT_COUNT",
                        message="El ítem debe tener exactamente una opción marcada como correcta.",
                        field="opciones",
                        severity="error"
                    )
                )
                is_valid = False

        except ValidationError as e:
            for error in e.errors():
                current_findings.append(
                    ReportEntrySchema(
                        code=f"E_SCHEMA_{error['type'].upper()}",
                        message=f"Fallo de validación de esquema: {error['msg']}",
                        field=".".join(map(str, error['loc'])) if error['loc'] else 'payload',
                        severity="error"
                    )
                )
            is_valid = False

        # ▼▼▼ LÓGICA DE ACTUALIZACIÓN ALINEADA ▼▼▼
        if not is_valid:
            item.findings.extend(current_findings)
            summary = f"Hard validation failed. {len(current_findings)} critical errors found."
            update_item_status_and_audit(item, stage_name, f"{stage_name}.fail", summary)
            logger.warning(f"Item {item.temp_id} failed hard validation. Findings: {current_findings}")
        else:
            summary = "Hard validation passed."
            update_item_status_and_audit(item, stage_name, f"{stage_name}.success", summary)
            logger.info(f"Item {item.temp_id} passed hard validation.")

    logger.info("Hard validation stage completed for all items.")
    return items
