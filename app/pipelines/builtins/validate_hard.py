# app/pipelines/builtins/validate_hard.py

from __future__ import annotations
import logging
from typing import List, Dict, Any
from pydantic import ValidationError, HttpUrl
import re

from ..registry import register
from app.schemas.models import Item, ItemStatus # Ensure ItemStatus is imported
from app.schemas.item_schemas import ReportEntrySchema, ItemPayloadSchema, TipoReactivo, RetroalimentacionOpcionSchema
from app.pipelines.abstractions import BaseStage


logger = logging.getLogger(__name__)

# MOCK: En un sistema real, este catálogo se cargaría desde sigie_error_codes.yaml
MOCK_ERROR_CATALOG_HARD = {
    "E001_SCHEMA": {"message": "El JSON del ítem no cumple el esquema.", "fix_hint": "Regenerar el ítem siguiendo el esquema."},
    "E010_NUM_OPTIONS": {"message": "El número de opciones debe ser 3 o 4.", "fix_hint": "Ajustar la cantidad de opciones."},
    "E011_DUP_ID": {"message": "IDs de opciones duplicados.", "fix_hint": "Usar IDs únicos."},
    "E012_CORRECT_COUNT": {"message": "Debe haber exactamente una opción correcta.", "fix_hint": "Dejar solo una opción con es_correcta: true."},
    "E013_ID_NO_MATCH": {"message": "respuesta_correcta_id no coincide con la opción correcta.", "fix_hint": "Sincronizar respuesta_correcta_id con el id de la opción correcta."},
    "E030_COMPLET_SEGMENTS": {"message": "Segmentos de opciones no coinciden con huecos del enunciado.", "fix_hint": "Alinear segmentos con huecos."},
    "E050_BAD_URL": {"message": "URL no válida o inaccesible.", "fix_hint": "Proveer URL accesible o dejar recurso_visual en null."},
    "E060_MULTI_TESTLET": {"message": "testlet_id y estimulo_compartido desincronizados.", "fix_hint": "Sincronizarlos o eliminarlos."},
    "E952_NO_PAYLOAD": {"message": "Ítem sin payload para procesar.", "fix_hint": "Revisar etapas anteriores."},
    "E959_PIPELINE_FATAL_ERROR": {"message": "Error fatal inesperado en la etapa.", "fix_hint": "Revisar log para más detalles."},
    "E101_KEY_NO_EXIST": {"message": "El ID de la respuesta correcta no existe en las opciones del cuerpo del ítem.", "fix_hint": "Asegurar que el ID de la respuesta correcta esté presente en las opciones."},
    "E104_OPTIONS_CONSISTENCY": {"message": "Las opciones en el cuerpo del ítem y las de retroalimentación no coinciden en IDs o cantidad.", "fix_hint": "Asegurar que todas las opciones del cuerpo tienen una entrada en retroalimentación y viceversa."},
}

def get_error_info_hard(code: str) -> dict:
    """Helper to get message and fix_hint from the mock catalog for hard validation."""
    return MOCK_ERROR_CATALOG_HARD.get(code, {"message": f"Unknown hard error code: {code}.", "fix_hint": None})


@register("validate_hard")
class ValidateHardStage(BaseStage):
    """
    Etapa de validación "dura" de los ítems basada en reglas programáticas.
    Implementada como una clase Stage.
    """

    async def execute(self, items: List[Item]) -> List[Item]:
        self.logger.info(f"Starting hard validation for {len(items)} items.")

        for item in items:
            current_findings: List[ReportEntrySchema] = []
            is_valid = True # Indica si pasa las validaciones de esta etapa

            outcome_status = ItemStatus.SUCCESS # Usar Enum
            summary_message = "Validación dura: OK."

            if self.ctx.get("skip_fatal_items", True) and item.status == ItemStatus.FATAL:
                self._set_status(item, ItemStatus.SKIPPED, "Item saltado: ya en estado fatal.") # Usar Enum
                self.logger.debug(f"Skipping item {item.temp_id} in {self.stage_name} due to prior fatal status.")
                continue

            if not item.payload:
                code = "E952_NO_PAYLOAD"
                info = get_error_info_hard(code)
                current_findings.append(
                    ReportEntrySchema(
                        code=code,
                        message=info["message"],
                        severity=ItemStatus.FATAL.value, # Severity as string value of Enum
                        fix_hint=info["fix_hint"]
                    )
                )
                is_valid = False
                outcome_status = ItemStatus.FATAL # Usar Enum
                summary_message = info["message"]
                self._set_status(item, outcome_status, summary_message)
                continue

            try:
                # Primero, intentar validar el payload completo contra el esquema Pydantic.
                validated_payload = ItemPayloadSchema.model_validate(item.payload)
                item.payload = validated_payload # Asegurar que el payload esté validado y tipado.

                # Acceso a las opciones del cuerpo del ítem (id y texto)
                body_options_ids = {opt.id for opt in item.payload.cuerpo_item.opciones}

                # Acceso a la retroalimentación de opciones (id, es_correcta, justificacion)
                # Mapeamos para fácil acceso por ID
                feedback_options_map: Dict[str, RetroalimentacionOpcionSchema] = {
                    f_opt.id: f_opt for f_opt in item.payload.clave_y_diagnostico.retroalimentacion_opciones
                }

                # --- VALIDACIONES LÓGICAS ---

                # 1. Comprobar que hay exactamente 1 opción correcta
                # La 'correctitud' se define en clave_y_diagnostico.retroalimentacion_opciones
                correct_feedback_options = [
                    f_opt for f_opt in item.payload.clave_y_diagnostico.retroalimentacion_opciones
                    if f_opt.es_correcta
                ]
                if len(correct_feedback_options) == 0:
                    code = "E012_CORRECT_COUNT"
                    info = get_error_info_hard(code)
                    current_findings.append(
                        ReportEntrySchema(
                            code=code,
                            message=info["message"],
                            field="clave_y_diagnostico.retroalimentacion_opciones",
                            severity=ItemStatus.FATAL.value,
                            fix_hint=info["fix_hint"]
                        )
                    )
                    is_valid = False
                elif len(correct_feedback_options) > 1:
                    code = "E012_CORRECT_COUNT"
                    info = get_error_info_hard(code)
                    current_findings.append(
                        ReportEntrySchema(
                            code=code,
                            message=info["message"],
                            field="clave_y_diagnostico.retroalimentacion_opciones",
                            severity=ItemStatus.FATAL.value,
                            fix_hint=info["fix_hint"]
                        )
                    )
                    is_valid = False

                # 2. Comprobar que respuesta_correcta_id (en clave_y_diagnostico)
                #    a) exista como ID en cuerpo_item.opciones
                #    b) coincida con el ID de la opción marcada como correcta en retroalimentacion_opciones
                expected_correct_id = item.payload.clave_y_diagnostico.respuesta_correcta_id

                # a) Verificar que respuesta_correcta_id exista en las opciones del cuerpo
                if expected_correct_id not in body_options_ids:
                    code = "E101_KEY_NO_EXIST" # Código para clave que no existe en opciones
                    info = get_error_info_hard(code)
                    current_findings.append(
                        ReportEntrySchema(
                            code=code,
                            message=info["message"],
                            field="clave_y_diagnostico.respuesta_correcta_id",
                            severity=ItemStatus.FATAL.value,
                            fix_hint=info["fix_hint"]
                        )
                    )
                    is_valid = False

                # b) Verificar que el ID de la opción marcada como correcta en feedback_options_map
                #    coincida con respuesta_correcta_id
                if len(correct_feedback_options) == 1: # Solo si hay una opción marcada como correcta
                    if expected_correct_id != correct_feedback_options[0].id:
                        code = "E013_ID_NO_MATCH"
                        info = get_error_info_hard(code)
                        current_findings.append(
                            ReportEntrySchema(
                                code=code,
                                message=info["message"],
                                field="clave_y_diagnostico.respuesta_correcta_id / retroalimentacion_opciones.es_correcta",
                                severity=ItemStatus.FATAL.value,
                                fix_hint=info["fix_hint"]
                            )
                        )
                        is_valid = False

                # 3. Verificar unicidad de IDs de opciones (en cuerpo_item.opciones)
                # Esta validación ya se asegura si `body_options_ids` es un set.
                # Re-iterar para encontrar y reportar duplicados si los hubiera.
                seen_option_ids = set()
                for i, opcion in enumerate(item.payload.cuerpo_item.opciones):
                    if opcion.id in seen_option_ids:
                        code = "E011_DUP_ID"
                        info = get_error_info_hard(code)
                        current_findings.append(
                            ReportEntrySchema(
                                code=code,
                                message=info["message"],
                                field=f"cuerpo_item.opciones[{i}].id",
                                severity=ItemStatus.FATAL.value,
                                fix_hint=info["fix_hint"]
                            )
                        )
                        is_valid = False
                    seen_option_ids.add(opcion.id)

                # 4. Consistencia de Opciones (E104): IDs y cantidad entre cuerpo_item.opciones y retroalimentacion_opciones
                feedback_option_ids = set(feedback_options_map.keys())
                if body_options_ids != feedback_option_ids or len(body_options_ids) != len(feedback_option_ids):
                    code = "E104_OPTIONS_CONSISTENCY"
                    info = get_error_info_hard(code)
                    current_findings.append(
                        ReportEntrySchema(
                            code=code,
                            message=info["message"],
                            field="cuerpo_item.opciones / clave_y_diagnostico.retroalimentacion_opciones",
                            severity=ItemStatus.FATAL.value,
                            fix_hint=info["fix_hint"]
                        )
                    )
                    is_valid = False

                # 5. Validación específica para tipo_reactivo "completamiento"
                if item.payload.arquitectura.formato.tipo_reactivo == TipoReactivo.COMPLETAMIENTO:
                    holes = item.payload.cuerpo_item.enunciado_pregunta.count("___")
                    if holes > 0:
                        for i, opt in enumerate(item.payload.cuerpo_item.opciones):
                            segs = re.split(r"\s*[-,yY]\s*|\s+y\s+", opt.texto)
                            if len(segs) != holes:
                                code = "E030_COMPLET_SEGMENTS"
                                info = get_error_info_hard(code)
                                current_findings.append(
                                    ReportEntrySchema(
                                        code=code,
                                        message=info["message"],
                                        field=f"cuerpo_item.opciones[{i}].texto",
                                        severity=ItemStatus.FATAL.value,
                                        fix_hint=info["fix_hint"]
                                    )
                                )
                                is_valid = False

                # --- VALIDACIÓN ELIMINADA: E060_MULTI_TESTLET ---
                # Esta validación se elimina porque 'estimulo_compartido' no es un campo directo en ItemPayloadSchema.
                # Si es necesario validar este campo, debe ser añadido a ItemPayloadSchema o sus sub-esquemas relevantes.

            except ValidationError as e:
                # Captura errores de validación de esquema Pydantic detallados
                for error in e.errors():
                    code = "E001_SCHEMA"
                    info = get_error_info_hard(code)
                    current_findings.append(
                        ReportEntrySchema(
                            code=code,
                            message=f"{info['message']} Detalles: {error['msg']} en campo: {'.'.join(map(str, error['loc']))}",
                            field=".".join(map(str, error['loc'])) if error['loc'] else 'payload',
                            severity=ItemStatus.FATAL.value,
                            fix_hint=info["fix_hint"]
                        )
                    )
                is_valid = False
                self.logger.error(f"Schema validation error in ValidateHardStage for item {item.temp_id}: {e}", exc_info=True)
            except Exception as e:
                # Captura cualquier otra excepción inesperada y proporciona detalles
                code = "E959_PIPELINE_FATAL_ERROR"
                info = get_error_info_hard(code)
                current_findings.append(
                    ReportEntrySchema(
                        code=code,
                        message=f"{info['message']} Detalles: {str(e)}",
                        field=None,
                        severity=ItemStatus.FATAL.value,
                        fix_hint=info["fix_hint"]
                    )
                )
                is_valid = False
                self.logger.error(f"Unexpected error in ValidateHardStage for item {item.temp_id}: {e}", exc_info=True)

            item.findings.extend(current_findings)

            if any(f.severity == ItemStatus.FATAL.value for f in current_findings):
                outcome_status = ItemStatus.FATAL
                summary_message = f"Validación dura: Error fatal. {len(current_findings)} errores críticos encontrados."
            elif not is_valid:
                # --- FIX: Use ItemStatus.FAIL for non-fatal hard validation failures ---
                outcome_status = ItemStatus.FAIL # Now using ItemStatus.FAIL
                # --- END FIX ---
                summary_message = "Validación dura: Falló (errores detectados)."
            else:
                outcome_status = ItemStatus.SUCCESS
                summary_message = "Validación dura: OK."

            self._set_status(item, outcome_status, summary_message)

            if outcome_status == ItemStatus.FATAL:
                self.logger.error(f"Item {item.temp_id} failed hard validation with FATAL errors. Findings: {current_findings}")
            elif outcome_status == ItemStatus.FAIL: # Correctly check for FAIL status
                self.logger.error(f"Item {item.temp_id} failed hard validation. Findings: {current_findings}")
            else:
                self.logger.info(f"Item {item.temp_id} passed hard validation.")

        self.logger.info(f"Hard validation completed for {len(items)} items.")
        return items
