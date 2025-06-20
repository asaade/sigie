# app/pipelines/builtins/validate_hard.py

import logging
from typing import List, Dict, Any
from uuid import UUID

from ..registry import register
from app.schemas.models import Item
from app.schemas.item_schemas import ReportEntrySchema, AuditEntrySchema, ItemPayloadSchema, OpcionSchema, MetadataSchema

logger = logging.getLogger(__name__)

@register("validate_hard")
async def validate_hard_stage(items: List[Item], ctx: Dict[str, Any]) -> List[Item]:
    """
    Realiza una validación "dura" de los ítems, verificando la estructura básica
    y la presencia de campos obligatorios de acuerdo con ItemPayloadSchema.
    No usa LLM.
    """
    stage_name = "validate_hard"

    logger.info(f"Starting hard validation for {len(items)} items.")

    for item in items:
        # Saltar ítems ya en estado de error fatal o similares que no deben ser procesados
        if item.status in ["fatal_error", "generation_failed"]:
            item.audits.append(
                AuditEntrySchema(
                    stage=stage_name,
                    summary="Saltado: ítem ya en estado de error fatal previo."
                )
            )
            continue

        current_errors = []
        current_warnings = []
        is_valid_hard = True
        validation_summary = "Validación dura: OK."

        # Validar la estructura general del payload
        if not item.payload:
            current_errors.append(
                ReportEntrySchema(
                    code="E_NO_PAYLOAD",
                    message="El ítem no tiene un payload.",
                    severity="error"
                )
            )
            is_valid_hard = False
            validation_summary = "Validación dura: Falló (no hay payload)."
        else:
            try:
                # Intenta revalidar el payload contra el esquema Pydantic.
                # Esto captura cualquier inconsistencia que el LLM pudiera haber introducido
                # después de la generación inicial (aunque generate_items.py ya valida,
                # esto es una capa de seguridad para la estructura fundamental).
                validated_payload = ItemPayloadSchema.model_validate(item.payload.model_dump())
                item.payload = validated_payload # Asegura que el payload sea un objeto Pydantic válido

                # Validaciones específicas de lógica "dura" (no requiere LLM)
                # 1. Comprobar que hay al menos 2 opciones
                if not item.payload.opciones or len(item.payload.opciones) < 2:
                    current_errors.append(
                        ReportEntrySchema(
                            code="E_MIN_OPCIONES",
                            message="El ítem debe tener al menos 2 opciones.",
                            field="opciones",
                            severity="error"
                        )
                    )
                    is_valid_hard = False

                # 2. Comprobar que hay al menos 1 opción correcta
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
                    # Esto podría ser un error "duro" o un warning, dependiendo de la política exacta.
                    # Para "dura", lo marcamos como error por ahora.
                    current_errors.append(
                        ReportEntrySchema(
                            code="E_MULTIPLES_CORRECTAS_HARD",
                            message="El ítem tiene más de una opción marcada como correcta (violación de unicidad).",
                            field="opciones",
                            severity="error"
                        )
                    )
                    is_valid_hard = False

                # 3. Comprobar que respuesta_correcta_id coincide con una opción marcada como correcta
                if item.payload.respuesta_correcta_id:
                    matching_correct_options = [
                        opt for opt in correct_options
                        if str(opt.id) == str(item.payload.respuesta_correcta_id)
                    ]
                    if not matching_correct_options and correct_options: # Si hay correctas, pero ninguna coincide con el ID
                         current_errors.append(
                            ReportEntrySchema(
                                code="E_ID_CORRECTA_NO_COINCIDE",
                                message="El 'respuesta_correcta_id' no coincide con ninguna opción marcada como correcta.",
                                field="respuesta_correcta_id",
                                severity="error"
                            )
                        )
                         is_valid_hard = False
                    elif not item.payload.opciones: # Si no hay opciones, tampoco puede haber un ID correcto
                         current_errors.append(
                            ReportEntrySchema(
                                code="E_ID_CORRECTA_SIN_OPCIONES",
                                message="Existe 'respuesta_correcta_id' pero no hay opciones definidas.",
                                field="respuesta_correcta_id",
                                severity="error"
                            )
                        )
                         is_valid_hard = False
                elif correct_options: # Si hay opción correcta marcada, pero no hay respuesta_correcta_id
                    current_warnings.append(
                        ReportEntrySchema(
                            code="W_MISSING_CORRECT_ID",
                            message="Hay una opción correcta, pero 'respuesta_correcta_id' está ausente o vacío.",
                            field="respuesta_correcta_id",
                            severity="warning"
                        )
                    )

                # 4. Verificar que el texto del enunciado y opciones no estén vacíos
                if not item.payload.enunciado_pregunta.strip():
                    current_errors.append(
                        ReportEntrySchema(
                            code="E_ENUNCIADO_VACIO",
                            message="El enunciado de la pregunta no puede estar vacío.",
                            field="enunciado_pregunta",
                            severity="error"
                        )
                    )
                    is_valid_hard = False

                for i, opcion in enumerate(item.payload.opciones):
                    if not opcion.texto.strip():
                        current_errors.append(
                            ReportEntrySchema(
                                code="E_OPCION_TEXTO_VACIO",
                                message=f"El texto de la opción {opcion.id or i} no puede estar vacío.",
                                field=f"opciones[{i}].texto",
                                severity="error"
                            )
                        )
                        is_valid_hard = False
                    if not opcion.justificacion.strip():
                        current_warnings.append(
                            ReportEntrySchema(
                                code="W_JUSTIFICACION_VACIA",
                                message=f"La justificación de la opción {opcion.id or i} no puede estar vacía.",
                                field=f"opciones[{i}].justificacion",
                                severity="warning"
                            )
                        )

            except ValidationError as e:
                # Error de validación Pydantic más profunda
                current_errors.append(
                    ReportEntrySchema(
                        code="E_SCHEMA_VALIDATION",
                        message=f"Fallo de validación del esquema Pydantic del payload: {e}",
                        field="payload",
                        severity="error"
                    )
                )
                is_valid_hard = False
                validation_summary = f"Validación dura: Falló (error de esquema: {e})."
            except Exception as e:
                current_errors.append(
                    ReportEntrySchema(
                        code="E_UNEXPECTED_VALIDATION_ERROR",
                        message=f"Error inesperado durante la validación dura: {e}",
                        severity="error"
                    )
                )
                is_valid_hard = False
                validation_summary = f"Validación dura: Falló (error inesperado: {e})."


        # Actualizar el estado y los reportes del ítem
        item.errors.extend(current_errors)
        item.warnings.extend(current_warnings)

        if not is_valid_hard:
            item.status = "failed_hard_validation"
            validation_summary = f"Validación dura: Falló. Errores: {len(current_errors)}, Advertencias: {len(current_warnings)}."
        elif item.status == "generated": # Si no hay errores y venía de generado, ahora es validado
            item.status = "hard_validated"
            validation_summary = "Validación dura: OK."
        # Si ya tenía otro status (ej. ok de otra etapa), lo dejamos si no falló aquí.

        # Añadir entrada de auditoría
        item.audits.append(
            AuditEntrySchema(
                stage=stage_name,
                summary=validation_summary,
                corrections=[] # Esta etapa no hace correcciones, solo reporta
            )
        )

        logger.debug(f"Item {item.temp_id} hard validation result: {item.status}")

    logger.info(f"Hard validation completed for {len(items)} items.")
    return items
