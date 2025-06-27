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

            # Antes de proceder, si el ítem ya está en un estado fatal_error, lo saltamos.
            if self.ctx.get("skip_fatal_items", True) and item.status == "fatal_error":
                self._set_status(item, "skipped_due_to_fatal_prior", "Item saltado: ya en estado fatal.")
                self.logger.debug(f"Skipping item {item.temp_id} in {self.stage_name} due to prior fatal status.")
                continue

            # Aunque LLMStage ya lo hace, para BaseStage es bueno tener esta comprobación.
            if not item.payload:
                current_findings.append(
                    ReportEntrySchema(code="E952_NO_PAYLOAD", message="El ítem no tiene un payload para validar.", severity="fatal")
                )
                is_valid = False
                outcome_status = "fatal" # Forzar a fatal
                summary_message = "Validación dura: Error fatal. No hay payload para procesar."
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
                    current_findings.append(
                        ReportEntrySchema(
                            code="E012_CORRECT_COUNT", # Estandarizado
                            message="El ítem debe tener exactamente una opción marcada como correcta (0 encontradas).",
                            field="opciones",
                            severity="fatal"
                        )
                    )
                    is_valid = False
                elif len(correct_options) > 1:
                    current_findings.append(
                        ReportEntrySchema(
                            code="E012_CORRECT_COUNT", # Estandarizado
                            message="El ítem debe tener exactamente una opción marcada como correcta (múltiples encontradas).",
                            field="opciones",
                            severity="fatal"
                        )
                    )
                    is_valid = False

                # 2. Comprobar que respuesta_correcta_id coincide con la opción marcada como correcta
                if item.payload.respuesta_correcta_id:
                    # Solo verificamos si ya se encontró una opción correcta única, para evitar errores en cascada
                    if len(correct_options) == 1:
                        matching_correct_options_by_id = [
                            opt for opt in correct_options
                            if opt.id == item.payload.respuesta_correcta_id
                        ]
                        if not matching_correct_options_by_id:
                            current_findings.append(
                                ReportEntrySchema(
                                    code="E013_ID_NO_MATCH", # Estandarizado
                                    message="El 'respuesta_correcta_id' no coincide con el ID de la única opción marcada como correcta.",
                                    field="respuesta_correcta_id",
                                    severity="fatal"
                                )
                            )
                            is_valid = False
                else: # respuesta_correcta_id no está presente o es nulo, lo cual es un error si hay opciones correctas
                    if len(correct_options) == 1: # Si hay una opción correcta pero no se especifica el ID
                         current_findings.append(
                            ReportEntrySchema(
                                code="E013_ID_NO_MATCH", # Reutilizamos el código
                                message="El 'respuesta_correcta_id' es nulo pero existe una opción marcada como correcta.",
                                field="respuesta_correcta_id",
                                severity="fatal"
                            )
                        )
                         is_valid = False


                # 3. Verificar unicidad de IDs de opciones
                option_ids = set()
                for i, opcion in enumerate(item.payload.opciones):
                    if opcion.id in option_ids:
                        current_findings.append(
                            ReportEntrySchema(
                                code="E011_DUP_ID", # Estandarizado
                                message=f"ID de opción duplicado: '{opcion.id}' en opciones[{i}].",
                                field=f"opciones[{i}].id",
                                severity="fatal"
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
                                code="E031_COMPLETAMIENTO_SIN_HUECOS", # Nuevo código estandarizado
                                message="El tipo de reactivo 'completamiento' requiere al menos un hueco ('___') en el enunciado.",
                                field="enunciado_pregunta",
                                severity="fatal"
                            )
                        )
                        is_valid = False
                    else: # Solo si hay huecos, verificamos la consistencia de segmentos
                        for i, opt in enumerate(item.payload.opciones):
                            # Se asume que los segmentos en la opción están separados por un patrón específico.
                            # Este re.split es específico del diseño actual.
                            segs = re.split(r"\s*[-,yY]\s*|\s+y\s+", opt.texto)
                            if len(segs) != holes:
                                current_findings.append(
                                    ReportEntrySchema(
                                        code="E030_COMPLET_SEGMENTS", # Estandarizado
                                        message=f"La opción {opt.id} tiene {len(segs)} segmentos, pero el enunciado tiene {holes} huecos. Deben coincidir.",
                                        field=f"opciones[{i}].texto",
                                        severity="fatal"
                                    )
                                )
                                is_valid = False

                # --- NUEVA VALIDACIÓN: E060_MULTI_TESTLET (Inconsistencia testlet_id y estimulo_compartido) ---
                testlet_id_present = item.payload.testlet_id is not None
                estimulo_compartido_present = (item.payload.estimulo_compartido is not None and
                                               item.payload.estimulo_compartido.strip() != "")

                if testlet_id_present != estimulo_compartido_present: # Uno está presente y el otro no
                    current_findings.append(
                        ReportEntrySchema(
                            code="E060_MULTI_TESTLET",
                            message="Inconsistencia en los campos 'testlet_id' y 'estimulo_compartido'. Ambos deben estar presentes o ausentes simultáneamente para un testlet.",
                            field="testlet_id / estimulo_compartido",
                            severity="fatal"
                        )
                    )
                    is_valid = False
                # --- FIN NUEVA VALIDACIÓN ---


                # 5. Validaciones de URL para recurso_visual
                # La validación Pydantic de HttpUrl ya se encarga de que sea un formato válido.
                # Aquí solo verificamos que si existe, sea del tipo correcto.
                if item.payload.recurso_visual and not isinstance(item.payload.recurso_visual.referencia, HttpUrl):
                    current_findings.append(
                        ReportEntrySchema(
                            code="E050_BAD_URL", # Estandarizado
                            message=f"La referencia URL del recurso visual es inválida o no es una HttpUrl: {item.payload.recurso_visual.referencia}.",
                            field="recurso_visual.referencia",
                            severity="fatal"
                        )
                    )
                    is_valid = False

            except ValidationError as e:
                # Si la validación Pydantic del modelo completo falló (capturado por model_validate de ItemPayloadSchema)
                for error in e.errors():
                    current_findings.append(
                        ReportEntrySchema(
                            code="E001_SCHEMA", # Estandarizado para fallos de esquema Pydantic
                            message=f"Fallo de validación de esquema Pydantic en campo '{'.'.join(map(str, error['loc']))}': {error['msg']}",
                            field=".".join(map(str, error['loc'])) if error['loc'] else 'payload',
                            severity="fatal"
                        )
                    )
                is_valid = False
            except Exception as e:
                # Captura cualquier otro error inesperado durante las validaciones duras
                current_findings.append(
                    ReportEntrySchema(
                        code="E959_PIPELINE_FATAL_ERROR", # Estandarizado para errores fatales de pipeline
                        message=f"Error inesperado durante la validación dura: {e}",
                        severity="fatal"
                    )
                )
                is_valid = False

            item.findings.extend(current_findings)

            # Determinar el estado final del ítem basado en los findings acumulados
            if any(f.severity == "fatal" for f in current_findings):
                outcome_status = "fatal"
                summary_message = f"Validación dura: Error fatal. {len(current_findings)} errores críticos encontrados."
            elif not is_valid: # Esto es un caso que no debería ocurrir si todos los errores son fatal
                outcome_status = "error" # En validate_hard, todos los errores son fatales, así que esta rama no se alcanzaría si is_valid=False y hay findings.
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
