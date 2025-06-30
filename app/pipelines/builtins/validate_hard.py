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

# MOCK: En un sistema real, este catálogo se cargaría desde sigie_error_codes.yaml
# o a través de un módulo de utilidades centralizado.
# Solo los códigos de la categoría ESTRUCTURAL y relevantes de PIPELINE_CONTROL para validate_hard
MOCK_ERROR_CATALOG_HARD = {
    "E001_SCHEMA": {"message": "El JSON del ítem no cumple el esquema.", "fix_hint": "Regenerar el ítem siguiendo el esquema."},
    "E010_NUM_OPTIONS": {"message": "El número de opciones debe ser 3 o 4.", "fix_hint": "Ajustar la cantidad de opciones."}, # Although not explicitly checked in this code, included for completeness if added later.
    "E011_DUP_ID": {"message": "IDs de opciones duplicados.", "fix_hint": "Usar IDs únicos."},
    "E012_CORRECT_COUNT": {"message": "Debe haber exactamente una opción correcta.", "fix_hint": "Dejar solo una opción con es_correcta: true."},
    "E013_ID_NO_MATCH": {"message": "respuesta_correcta_id no coincide con la opción correcta.", "fix_hint": "Sincronizar respuesta_correcta_id con el id de la opción correcta."},
    "E030_COMPLET_SEGMENTS": {"message": "Segmentos de opciones no coinciden con huecos del enunciado.", "fix_hint": "Alinear segmentos con huecos."},
    "E050_BAD_URL": {"message": "URL no válida o inaccesible.", "fix_hint": "Proveer URL accesible o dejar recurso_visual en null."},
    "E060_MULTI_TESTLET": {"message": "testlet_id y estimulo_compartido desincronizados.", "fix_hint": "Sincronizarlos o eliminarlos."},
    "E952_NO_PAYLOAD": {"message": "Ítem sin payload para procesar.", "fix_hint": "Revisar etapas anteriores."},
    "E959_PIPELINE_FATAL_ERROR": {"message": "Error fatal inesperado en la etapa.", "fix_hint": "Revisar log para más detalles."},
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

            # Antes de proceder, si el ítem ya está en un estado fatal_error, lo saltamos.
            if self.ctx.get("skip_fatal_items", True) and item.status == "fatal_error":
                self._set_status(item, "skipped_due_to_fatal_prior", "Item saltado: ya en estado fatal.")
                self.logger.debug(f"Skipping item {item.temp_id} in {self.stage_name} due to prior fatal status.")
                continue

            # Aunque LLMStage ya lo hace, para BaseStage es bueno tener esta comprobación.
            if not item.payload:
                code = "E952_NO_PAYLOAD"
                info = get_error_info_hard(code)
                current_findings.append(
                    ReportEntrySchema(
                        code=code,
                        message=info["message"],
                        field=None,
                        severity="fatal",
                        fix_hint=info["fix_hint"]
                    )
                )
                is_valid = False
                outcome_status = "fatal"
                summary_message = info["message"]
                self._set_status(item, outcome_status, summary_message)
                continue


            try:
                # Primero, intentar validar el payload completo contra el esquema Pydantic.
                # Cualquier error aquí es un fallo estructural grave.
                validated_payload = ItemPayloadSchema.model_validate(item.payload)
                item.payload = validated_payload # Asegurar que el payload esté validado y tipado.

                # 1. Comprobar que hay exactamente 1 opción correcta
                correct_options = [opt for opt in item.payload.opciones if opt.es_correcta]
                if len(correct_options) == 0:
                    code = "E012_CORRECT_COUNT"
                    info = get_error_info_hard(code)
                    current_findings.append(
                        ReportEntrySchema(
                            code=code,
                            message=info["message"],
                            field="opciones",
                            severity="fatal",
                            fix_hint=info["fix_hint"]
                        )
                    )
                    is_valid = False
                elif len(correct_options) > 1:
                    code = "E012_CORRECT_COUNT"
                    info = get_error_info_hard(code)
                    current_findings.append(
                        ReportEntrySchema(
                            code=code,
                            message=info["message"],
                            field="opciones",
                            severity="fatal",
                            fix_hint=info["fix_hint"]
                        )
                    )
                    is_valid = False

                # 2. Comprobar que respuesta_correcta_id coincide con la opción marcada como correcta
                if item.payload.respuesta_correcta_id:
                    if len(correct_options) == 1:
                        matching_correct_options_by_id = [
                            opt for opt in correct_options
                            if opt.id == item.payload.respuesta_correcta_id
                        ]
                        if not matching_correct_options_by_id:
                            code = "E013_ID_NO_MATCH"
                            info = get_error_info_hard(code)
                            current_findings.append(
                                ReportEntrySchema(
                                    code=code,
                                    message=info["message"],
                                    field="respuesta_correcta_id",
                                    severity="fatal",
                                    fix_hint=info["fix_hint"]
                                )
                            )
                            is_valid = False
                else: # respuesta_correcta_id is null but there is a correct option
                    if len(correct_options) == 1:
                         code = "E013_ID_NO_MATCH"
                         info = get_error_info_hard(code)
                         current_findings.append(
                            ReportEntrySchema(
                                code=code,
                                message=info["message"],
                                field="respuesta_correcta_id",
                                severity="fatal",
                                fix_hint=info["fix_hint"]
                            )
                        )
                         is_valid = False


                # 3. Verificar unicidad de IDs de opciones
                option_ids = set()
                for i, opcion in enumerate(item.payload.opciones):
                    if opcion.id in option_ids:
                        code = "E011_DUP_ID"
                        info = get_error_info_hard(code)
                        current_findings.append(
                            ReportEntrySchema(
                                code=code,
                                message=info["message"],
                                field=f"opciones[{i}].id",
                                severity="fatal",
                                fix_hint=info["fix_hint"]
                            )
                        )
                        is_valid = False
                    option_ids.add(opcion.id)

                # 4. Validación específica para tipo_reactivo "completamiento"
                if item.payload.tipo_reactivo == TipoReactivo.COMPLETAMIENTO:
                    holes = item.payload.enunciado_pregunta.count("___")
                    # Removed check for holes == 0 as E031 is not in YAML and E030 is for segment mismatch
                    if holes > 0: # Only if there are holes, verify segment consistency
                        for i, opt in enumerate(item.payload.opciones):
                            segs = re.split(r"\s*[-,yY]\s*|\s+y\s+", opt.texto)
                            if len(segs) != holes:
                                code = "E030_COMPLET_SEGMENTS"
                                info = get_error_info_hard(code)
                                current_findings.append(
                                    ReportEntrySchema(
                                        code=code,
                                        message=info["message"],
                                        field=f"opciones[{i}].texto",
                                        severity="fatal",
                                        fix_hint=info["fix_hint"]
                                    )
                                )
                                is_valid = False

                # --- VALIDACIÓN: E060_MULTI_TESTLET (Inconsistencia testlet_id y estimulo_compartido) ---
                testlet_id_present = item.payload.testlet_id is not None
                estimulo_compartido_present = (item.payload.estimulo_compartido is not None and
                                               item.payload.estimulo_compartido.strip() != "")

                if testlet_id_present != estimulo_compartido_present:
                    code = "E060_MULTI_TESTLET"
                    info = get_error_info_hard(code)
                    current_findings.append(
                        ReportEntrySchema(
                            code=code,
                            message=info["message"],
                            field="testlet_id / estimulo_compartido",
                            severity="fatal",
                            fix_hint=info["fix_hint"]
                        )
                    )
                    is_valid = False


                # 5. URL Validations for recurso_visual
                if item.payload.recurso_visual and not isinstance(item.payload.recurso_visual.referencia, HttpUrl):
                    code = "E050_BAD_URL"
                    info = get_error_info_hard(code)
                    current_findings.append(
                        ReportEntrySchema(
                            code=code,
                            message=info["message"],
                            field="recurso_visual.referencia",
                            severity="fatal",
                            fix_hint=info["fix_hint"]
                        )
                    )
                    is_valid = False

            except ValidationError as e:
                for error in e.errors():
                    code = "E001_SCHEMA"
                    info = get_error_info_hard(code)
                    current_findings.append(
                        ReportEntrySchema(
                            code=code,
                            message=info["message"],
                            field=".".join(map(str, error['loc'])) if error['loc'] else 'payload',
                            severity="fatal",
                            fix_hint=info["fix_hint"]
                        )
                    )
                is_valid = False
            except Exception as e:
                code = "E959_PIPELINE_FATAL_ERROR"
                info = get_error_info_hard(code)
                current_findings.append(
                    ReportEntrySchema(
                        code=code,
                        message=info["message"],
                        field=None,
                        severity="fatal",
                        fix_hint=info["fix_hint"]
                    )
                )
                is_valid = False

            item.findings.extend(current_findings)

            if any(f.severity == "fatal" for f in current_findings):
                outcome_status = "fatal"
                summary_message = f"Validación dura: Error fatal. {len(current_findings)} errores críticos encontrados."
            elif not is_valid:
                outcome_status = "error"
                summary_message = "Validación dura: Falló (errores no fatales, lo cual es inesperado para esta etapa)."
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
