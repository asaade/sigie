# app/pipelines/builtins/validate_hard.py

from __future__ import annotations
import logging # Mantener, ya que se usa logger directamente
from typing import List # Mantener para la firma de execute
from pydantic import ValidationError, HttpUrl # Necesarias para la lógica de validación
import re # Necesario para la lógica de validación de 'completamiento'

from ..registry import register
from app.schemas.models import Item
from app.schemas.item_schemas import ReportEntrySchema, ItemPayloadSchema, TipoReactivo # Aseguradas las imports. OpcionSchema se usa en la lista de comprensión.
from app.pipelines.abstractions import BaseStage # CRÍTICO: Importamos BaseStage

# from ..utils.stage_helpers import ( # Importar solo las helpers que NO son métodos de BaseStage
#     # skip_if_terminal_error, # Gestionado por BaseStage.execute
#     # add_audit_entry, # Gestionado por _set_status
#     # handle_missing_payload, # Gestionado por BaseStage.execute
#     # update_item_status_and_audit, # Gestionado por _set_status
# )


logger = logging.getLogger(__name__) # Definir logger para este módulo

@register("validate_hard")
class ValidateHardStage(BaseStage): # CRÍTICO: Convertido a clase que hereda de BaseStage
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

        # Los checks de skip_if_terminal_error y handle_missing_payload
        # están en BaseStage.execute. Aquí la etapa ya recibe ítems listos para procesar.

        for item in items: # Iteramos sobre los ítems ya filtrados por BaseStage.execute
            current_findings: List[ReportEntrySchema] = [] # Lista para acumular hallazgos
            is_valid = True

            try:
                # La validación Pydantic del payload. No es necesario .model_dump()
                validated_payload = ItemPayloadSchema.model_validate(item.payload)
                item.payload = validated_payload # Asegura que el payload sea un objeto Pydantic válido y actualizado

                # 1. Comprobar que hay exactamente 1 opción correcta
                correct_options = [opt for opt in item.payload.opciones if opt.es_correcta]
                if len(correct_options) == 0:
                    current_findings.append(
                        ReportEntrySchema(
                            code="E_NO_CORRECTA",
                            message="El ítem debe tener al menos una opción marcada como correcta.",
                            field="opciones",
                            severity="error"
                        )
                    )
                    is_valid = False
                elif len(correct_options) > 1:
                    current_findings.append(
                        ReportEntrySchema(
                            code="E_MULTIPLES_CORRECTAS_HARD",
                            message="El ítem tiene más de una opción marcada como correcta (violación de unicidad).",
                            field="opciones",
                            severity="error"
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
                                severity="error"
                            )
                        )
                        is_valid = False

                # 3. Verificar unicidad de IDs de opciones
                option_ids = set()
                for i, opcion in enumerate(item.payload.opciones): # OpcionSchema se usa aquí
                    if opcion.id in option_ids:
                        current_findings.append(
                            ReportEntrySchema(
                                code="E_OPCION_ID_DUPLICADO",
                                message=f"ID de opción duplicado: '{opcion.id}'.",
                                field=f"opciones[{i}].id",
                                severity="error"
                            )
                        )
                        is_valid = False
                    option_ids.add(opcion.id)

                # 4. Validación específica para tipo_reactivo "completamiento"
                if item.payload.tipo_reactivo == TipoReactivo.COMPLETAMIENTO: # TipoReactivo es necesario
                    holes = item.payload.enunciado_pregunta.count("___")
                    if holes == 0:
                        current_findings.append(
                            ReportEntrySchema(
                                code="E_COMPLETAMIENTO_SIN_HUECOS",
                                message="El tipo de reactivo 'completamiento' requiere al menos un hueco ('___') en el enunciado.",
                                field="enunciado_pregunta",
                                severity="error"
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
                                    severity="error"
                                )
                            )
                            is_valid = False

                # 5. Validaciones de URL para recurso_visual
                if item.payload.recurso_visual and not isinstance(item.payload.recurso_visual.referencia, HttpUrl): # HttpUrl es necesario
                    current_findings.append(
                        ReportEntrySchema(
                            code="E_RECURSO_VISUAL_URL_INVALIDA",
                            message=f"La URL de referencia del recurso visual es inválida: {item.payload.recurso_visual.referencia}.",
                            field="recurso_visual.referencia",
                            severity="error"
                        )
                    )
                    is_valid = False

            except ValidationError as e: # Captura errores específicos de Pydantic
                for error in e.errors():
                    current_findings.append(
                        ReportEntrySchema(
                            code=f"E_SCHEMA_VALIDATION_{error['type'].upper()}",
                            message=f"Fallo de validación de esquema Pydantic: {error['msg']}",
                            field=".".join(map(str, error['loc'])) if error['loc'] else 'payload',
                            severity="error"
                        )
                    )
                is_valid = False
            except Exception as e: # Captura cualquier otro error inesperado
                current_findings.append(
                    ReportEntrySchema(
                        code="E_UNEXPECTED_VALIDATION_ERROR",
                        message=f"Error inesperado durante la validación dura: {e}",
                        severity="error"
                    )
                )
                is_valid = False

            item.findings.extend(current_findings) # Extiende a findings

            if not is_valid:
                self._set_status(item, "fail", f"Validación dura: Falló. {len(current_findings)} errores críticos encontrados.")
                self.logger.error(f"Item {item.temp_id} failed hard validation. Findings: {current_findings}")
            else:
                 self._set_status(item, "success", "Validación dura: OK.")
                 self.logger.info(f"Item {item.temp_id} passed hard validation.")

        self.logger.info(f"Hard validation completed for {len(items)} items.")
        return items
