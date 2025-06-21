# app/pipelines/builtins/validate_hard.py

import logging
from typing import List, Dict, Any

from ..registry import register
from app.schemas.models import Item
# Eliminadas MetadataSchema y OpcionSchema: no se usan directamente
from app.schemas.item_schemas import ReportEntrySchema, AuditEntrySchema, ItemPayloadSchema, TipoReactivo
# Eliminado TypeAdapter: no se usa
from pydantic import ValidationError, HttpUrl # Añadido HttpUrl
import re # Import re for regex checks

logger = logging.getLogger(__name__)

@register("validate_hard")
async def validate_hard_stage(items: List[Item], ctx: Dict[str, Any]) -> List[Item]:
    """
    Realiza una validación "dura" de los ítems.
    Verifica la estructura, campos obligatorios, conteo y unicidad de opciones,
    y coherencia de la respuesta correcta. No usa LLM.
    """
    stage_name = "validate_hard"

    logger.info(f"Starting hard validation for {len(items)} items.")

    for item in items:
        # Saltar ítems ya en estado de error fatal o similares que no deben ser procesados
        if item.status in ["fatal_error", "generation_failed", "llm_generation_failed", "generation_validation_failed", "generation_failed_mismatch"]:
            item.audits.append(
                AuditEntrySchema(
                    stage=stage_name,
                    summary="Saltado: ítem ya en estado de error fatal previo."
                )
            )
            continue

        current_errors: List[ReportEntrySchema] = []
        current_warnings: List[ReportEntrySchema] = []
        is_valid_hard = True
        validation_summary = "Validación dura: OK."

        # 1. Validar la estructura general del payload usando ItemPayloadSchema (Pydantic)
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
                # Intenta validar el payload contra el esquema Pydantic.
                # 'by_alias=True' es importante si usas 'alias' en tus Fields.
                # 'exclude_none=True' para limpiar nulos si es necesario.
                validated_payload = ItemPayloadSchema.model_validate(item.payload)
                item.payload = validated_payload # Asegura que el payload sea un objeto Pydantic válido y actualizado

                # A partir de aquí, el item.payload ya es un objeto ItemPayloadSchema validado por Pydantic
                # y podemos asumir que campos básicos existen y tienen el tipo correcto, y que
                # las longitudes/conteos básicos de la lista de opciones son correctos.

                # 2. Validaciones específicas de lógica "dura" no cubiertas por Pydantic directamente:

                # 2.1. Comprobar que hay exactamente 1 opción correcta
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

                # 2.2. Comprobar que respuesta_correcta_id coincide con la opción marcada como correcta
                # Ya sabemos que respuesta_correcta_id es válido (a,b,c,d) por Pydantic.
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

                # 2.3. Verificar unicidad de IDs de opciones
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

                    # Las justificaciones vacías ahora son un error de Pydantic (min_length=1)
                    # La longitud de texto y justificación también las maneja Pydantic (max_length)


                # 2.4. Validación específica para tipo_reactivo "completamiento"
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

                # 2.5. Validaciones de URL para recurso_visual
                # Pydantic HttpUrl ya valida el formato. Esta comprobación es redundante si el payload
                # ya ha pasado ItemPayloadSchema.model_validate. Se mantiene solo como un
                # "doble chequeo" muy defensivo, pero idealmente HttpUrl haría el trabajo.
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
                # Errores de validación Pydantic más profundos que el model_validate inicial podría no haber capturado
                # (ej. si item.payload no era un dict y se pasó directamente, o errores inesperados de Pydantic).
                # Aunque model_validate(item.payload) ya debería capturar la mayoría.
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
                validation_summary = f"Validación dura: Falló (error de esquema Pydantic: {e})."
            except Exception as e:
                # Otros errores inesperados durante la validación
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
            logger.error(f"Item {item.temp_id} failed hard validation: {validation_summary}. Errors: {current_errors}")
        elif item.status == "generated": # Si no hay errores y venía de generado, ahora es validado
            item.status = "hard_validated"
            validation_summary = "Validación dura: OK."
            logger.debug(f"Item {item.temp_id} hard validation result: {item.status}")
        # Si ya tenía otro status (ej. 'ok' de una etapa de refinamiento o 'soft_validated'), lo dejamos si no falló aquí.


        # Añadir entrada de auditoría
        item.audits.append(
            AuditEntrySchema(
                stage=stage_name,
                summary=validation_summary,
                corrections=[] # Esta etapa no hace correcciones, solo reporta
            )
        )

    logger.info(f"Hard validation completed for {len(items)} items.")
    return items
