# app/pipelines/builtins/validate_hard.py

from __future__ import annotations
import logging
from typing import List
from pydantic import ValidationError, HttpUrl
import re

from ..registry import register
from app.schemas.models import Item
from app.schemas.item_schemas import ReportEntrySchema, ItemPayloadSchema, TipoReactivo
from app.pipelines.abstractions import BaseStage


logger = logging.getLogger(__name__)

@register("validate_hard")
class ValidateHardStage(BaseStage):
    """
    Etapa de validación "dura" de los ítems basada en reglas programáticas.
    Implementada como una clase Stage.
    """

    async def execute(self, items: List[Item]) -> List[Item]:
        """
        Punto de entrada principal de la etapa de validación dura.
        Filtra ítems no procesables y aplica validaciones estructurales.
        """
        self.logger.info(f"Starting hard validation for {len(items)} items.")

        for item in items:
            current_findings: List[ReportEntrySchema] = []
            is_valid = True # Indica si pasa las validaciones de esta etapa

            outcome_status = "success"
            summary_message = "Validación dura: OK."

            try:
                validated_payload = ItemPayloadSchema.model_validate(item.payload)
                item.payload = validated_payload

                # 1. Comprobar que hay exactamente 1 opción correcta
                correct_options = [opt for opt in item.payload.opciones if opt.es_correcta]
                if len(correct_options) == 0:
                    current_findings.append(
                        ReportEntrySchema(
                            code="E_NO_CORRECTA",
                            message="El ítem debe tener al menos una opción marcada como correcta.",
                            field="opciones",
                            severity="fatal" # MODIFICADO: A fatal
                        )
                    )
                    is_valid = False
                elif len(correct_options) > 1:
                    current_findings.append(
                        ReportEntrySchema(
                            code="E_MULTIPLES_CORRECTAS_HARD",
                            message="El ítem tiene más de una opción marcada como correcta (violación de unicidad).",
                            field="opciones",
                            severity="fatal" # MODIFICADO: A fatal
                        )
                    )
                    is_valid = False

                # 2. Comprobar que respuesta_correcta_id coincide con la opción marcada como correcta
                if item.payload.respuesta_correcta_id:
                    matching_correct_options_by_id = [
                        opt for opt in correct_options
                        if opt.id == item.payload.respuesta_correcta_id
                    ]
                    if not matching_correct_options_by_id:
                        current_findings.append(
                            ReportEntrySchema(
                                code="E_ID_CORRECTA_NO_COINCIDE",
                                message="El 'respuesta_correcta_id' no coincide con la opción marcada como correcta.",
                                field="respuesta_correcta_id",
                                severity="fatal" # MODIFICADO: A fatal
                            )
                        )
                        is_valid = False

                # 3. Verificar unicidad de IDs de opciones
                option_ids = set()
                for i, opcion in enumerate(item.payload.opciones):
                    if opcion.id in option_ids:
                        current_findings.append(
                            ReportEntrySchema(
                                code="E_OPCION_ID_DUPLICADO",
                                message=f"ID de opción duplicado: '{opcion.id}'.",
                                field=f"opciones[{i}].id",
                                severity="fatal" # MODIFICADO: A fatal
                            )
                        )
                        is_valid = False
                    option_ids.add(opcion.id)

                # 4. Validación específica para tipo_reactivo "completamiento"
                if item.payload.tipo_reactivo == TipoReactivo.COMPLETAMIENTO:
                    holes = item.payload.enunciado_pregunta.count("___")
                    if holes == 0:
                        current_findings.append(
                            ReportEntrySchema(
                                code="E_COMPLETAMIENTO_SIN_HUECOS",
                                message="El tipo de reactivo 'completamiento' requiere al menos un hueco ('___') en el enunciado.",
                                field="enunciado_pregunta",
                                severity="fatal" # MODIFICADO: A fatal
                            )
                        )
                        is_valid = False

                    for i, opt in enumerate(item.payload.opciones):
                        segs = re.split(r"\s*[-,yY]\s*|\s+y\s+", opt.texto)
                        if len(segs) != holes:
                            current_findings.append(
                                ReportEntrySchema(
                                    code="E_COMPLETAMIENTO_SEGMENTOS_NO_COINCIDEN",
                                    message=f"La opción {opt.id} tiene {len(segs)} segmentos, pero el enunciado tiene {holes} huecos.",
                                    field=f"opciones[{i}].texto",
                                    severity="fatal" # MODIFICADO: A fatal
                                )
                            )
                            is_valid = False

                # 5. Validaciones de URL para recurso_visual
                if item.payload.recurso_visual and not isinstance(item.payload.recurso_visual.referencia, HttpUrl):
                    current_findings.append(
                        ReportEntrySchema(
                            code="E_RECURSO_VISUAL_URL_INVALIDA",
                            message=f"La URL de referencia del recurso visual es inválida: {item.payload.recurso_visual.referencia}.",
                            field="recurso_visual.referencia",
                            severity="fatal" # MODIFICADO: A fatal
                        )
                    )
                    is_valid = False

            except ValidationError as e:
                for error in e.errors():
                    current_findings.append(
                        ReportEntrySchema(
                            code=f"E_SCHEMA_VALIDATION_{error['type'].upper()}",
                            message=f"Fallo de validación de esquema Pydantic: {error['msg']}",
                            field=".".join(map(str, error['loc'])) if error['loc'] else 'payload',
                            severity="fatal" # MODIFICADO: A fatal
                        )
                    )
                is_valid = False
            except Exception as e:
                current_findings.append(
                    ReportEntrySchema(
                        code="E_UNEXPECTED_VALIDATION_ERROR",
                        message=f"Error inesperado durante la validación dura: {e}",
                        severity="fatal" # MODIFICADO: A fatal
                    )
                )
                is_valid = False

            item.findings.extend(current_findings)

            if any(f.severity == "fatal" for f in current_findings):
                outcome_status = "fatal"
                summary_message = f"Validación dura: Error fatal. {len(current_findings)} errores críticos encontrados."
            elif not is_valid:
                outcome_status = "error"
                summary_message = f"Validación dura: Falló. {len(current_findings)} errores encontrados."
            else:
                outcome_status = "success"
                summary_message = "Validación dura: OK."

            self._set_status(item, outcome_status, summary_message)

            if outcome_status == "fatal":
                self.logger.error(f"Item {item.temp_id} failed hard validation with FATAL errors. Findings: {current_findings}")
            elif not is_valid:
                self.logger.error(f"Item {item.temp_id} failed hard validation. Findings: {current_findings}")
            else:
                 self.logger.info(f"Item {item.temp_id} passed hard validation.")

        self.logger.info(f"Hard validation completed for {len(items)} items.")
        return items
