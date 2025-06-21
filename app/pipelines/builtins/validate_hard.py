# app/pipelines/builtins/validate_hard.py

from __future__ import annotations
import logging
from typing import List, Dict, Any
from pydantic import ValidationError, HttpUrl
import re

from ..registry import register
from app.schemas.models import Item
from app.schemas.item_schemas import ReportEntrySchema, ItemPayloadSchema, TipoReactivo
from ..utils.stage_helpers import skip_if_terminal_error, handle_missing_payload, update_item_status_and_audit # Importar las nuevas funciones


logger = logging.getLogger(__name__)

@register("validate_hard")
async def validate_hard_stage(items: List[Item], ctx: Dict[str, Any]) -> List[Item]:
    """
    Realiza una validación "dura" de los ítems.
    Refactorizado para usar stage_helpers.
    """
    stage_name = "validate_hard"

    logger.info(f"Starting hard validation for {len(items)} items.")

    for item in items:
        if skip_if_terminal_error(item, stage_name):
            continue

        if not item.payload:
            handle_missing_payload(
                item,
                stage_name,
                "E_NO_PAYLOAD",
                "El ítem no tiene un payload.",
                "failed_hard_validation",
                "Saltado: no hay payload para validación dura."
            )
            continue

        current_errors: List[ReportEntrySchema] = []
        is_valid_hard = True

        try:
            validated_payload = ItemPayloadSchema.model_validate(item.payload)
            item.payload = validated_payload

            correct_options = [opt for opt in item.payload.opciones if opt.es_correcta]
            if len(correct_options) == 0:
                current_errors.append(
                    ReportEntrySchema(
                        code="E_NO_CORRECTA",
                        message="El ítem debe tener al menos una opción marcada como correcta.",
                        field="opciones",
                        severity="error"
                    )
                )
                is_valid_hard = False
            elif len(correct_options) > 1:
                current_errors.append(
                    ReportEntrySchema(
                        code="E_MULTIPLES_CORRECTAS_HARD",
                        message="El ítem tiene más de una opción marcada como correcta (violación de unicidad).",
                        field="opciones",
                        severity="error"
                    )
                )
                is_valid_hard = False

            if item.payload.respuesta_correcta_id:
                matching_correct_options_by_id = [
                    opt for opt in correct_options
                    if opt.id == item.payload.respuesta_correcta_id
                ]
                if not matching_correct_options_by_id:
                    current_errors.append(
                        ReportEntrySchema(
                            code="E_ID_CORRECTA_NO_COINCIDE",
                            message="El 'respuesta_correcta_id' no coincide con la opción marcada como correcta.",
                            field="respuesta_correcta_id",
                            severity="error"
                        )
                    )
                    is_valid_hard = False

            option_ids = set()
            for i, opcion in enumerate(item.payload.opciones):
                if opcion.id in option_ids:
                    current_errors.append(
                        ReportEntrySchema(
                            code="E_OPCION_ID_DUPLICADO",
                            message=f"ID de opción duplicado: '{opcion.id}'.",
                            field=f"opciones[{i}].id",
                            severity="error"
                        )
                    )
                    is_valid_hard = False
                option_ids.add(opcion.id)

            if item.payload.tipo_reactivo == TipoReactivo.COMPLETAMIENTO:
                holes = item.payload.enunciado_pregunta.count("___")
                if holes == 0:
                    current_errors.append(
                        ReportEntrySchema(
                            code="E_COMPLETAMIENTO_SIN_HUECOS",
                            message="El tipo de reactivo 'completamiento' requiere al menos un hueco ('___') en el enunciado.",
                            field="enunciado_pregunta",
                            severity="error"
                        )
                    )
                    is_valid_hard = False

                for i, opt in enumerate(item.payload.opciones):
                    segs = re.split(r"\s*[-,yY]\s*|\s+y\s+", opt.texto)
                    if len(segs) != holes:
                        current_errors.append(
                            ReportEntrySchema(
                                code="E_COMPLETAMIENTO_SEGMENTOS_NO_COINCIDEN",
                                message=f"La opción {opt.id} tiene {len(segs)} segmentos, pero el enunciado tiene {holes} huecos.",
                                field=f"opciones[{i}].texto",
                                severity="error"
                            )
                        )
                        is_valid_hard = False

            if item.payload.recurso_visual and not isinstance(item.payload.recurso_visual.referencia, HttpUrl):
                current_errors.append(
                    ReportEntrySchema(
                        code="E_RECURSO_VISUAL_URL_INVALIDA",
                        message=f"La URL de referencia del recurso visual es inválida: {item.payload.recurso_visual.referencia}.",
                        field="recurso_visual.referencia",
                        severity="error"
                    )
                )
                is_valid_hard = False

        except ValidationError as e:
            for error in e.errors():
                current_errors.append(
                    ReportEntrySchema(
                        code=f"E_SCHEMA_VALIDATION_{error['type'].upper()}",
                        message=f"Fallo de validación del esquema Pydantic del payload: {error['msg']}",
                        field=error['loc'][0] if error['loc'] else 'payload',
                        severity="error"
                    )
                )
            is_valid_hard = False
        except Exception as e:
            current_errors.append(
                ReportEntrySchema(
                    code="E_UNEXPECTED_VALIDATION_ERROR",
                    message=f"Error inesperado durante la validación dura: {e}",
                    severity="error"
                )
            )
            is_valid_hard = False

        item.errors.extend(current_errors)

        if not is_valid_hard:
            update_item_status_and_audit(
                item=item,
                stage_name=stage_name,
                new_status="failed_hard_validation",
                summary_msg=f"Validación dura: Falló. {len(current_errors)} errores."
            )
            logger.error(f"Item {item.temp_id} failed hard validation. Errors: {current_errors}")
        elif item.status == "generated":
            update_item_status_and_audit(
                item=item,
                stage_name=stage_name,
                new_status="hard_validated",
                summary_msg="Validación dura: OK."
            )
            logger.debug(f"Item {item.temp_id} hard validation result: {item.status}")

    logger.info(f"Hard validation completed for {len(items)} items.")
    return items
