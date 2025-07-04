# app/pipelines/builtins/validate_logic.py

from __future__ import annotations
import logging
import json
from typing import List, Type
from uuid import UUID
from pydantic import BaseModel

from ..registry import register
from app.schemas.models import Item
from app.schemas.item_schemas import ReportEntrySchema, ValidationResultSchema
from app.pipelines.abstractions import LLMStage
from app.core.error_metadata import get_error_info # Importar la función get_error_info del catálogo centralizado

logger = logging.getLogger(__name__)

@register("validate_logic")
class ValidateLogicStage(LLMStage):
    """
    Etapa de validación lógica que utiliza un LLM para identificar errores
    de coherencia, precisión y nivel cognitivo en los ítems.
    """

    def _get_expected_schema(self) -> Type[BaseModel]:
        """Define que esperamos un objeto de validación del LLM."""
        return ValidationResultSchema

    def _prepare_llm_input(self, item: Item) -> str:
        """Prepara el string de input para el LLM."""
        if not item.payload:
            self.logger.error(f"Item {item.temp_id} has no payload for _prepare_llm_input in {self.stage_name}.")
            return json.dumps({"error": "No item payload available."})

        item_dict = item.payload.model_dump(mode='json')
        # Asegurarse de que los UUIDs se conviertan a string para el LLM (aunque model_dump(mode='json') ya lo hace)
        # Esto es una salvaguarda si el campo llega en otro formato binario.
        if isinstance(item_dict.get("item_id"), UUID): # Cambiado de (bytes, bytearray) a UUID para Pydantic v2
             item_dict["item_id"] = str(item.payload.item_id)

        if isinstance(item_dict.get("respuesta_correcta_id"), UUID): # Cambiado de (bytes, bytearray) a UUID
            item_dict["respuesta_correcta_id"] = str(item.payload.respuesta_correcta_id)

        for opcion in item_dict.get("opciones", []):
            if isinstance(opcion.get("id"), UUID): # Cambiado de (bytes, bytearray) a UUID
                opcion["id"] = str(opcion["id"])

        llm_input_payload = {
            "item_id": str(item.temp_id), # Usar temp_id como ID de sesión
            "item_payload": item_dict, # Pasar el payload completo para el análisis del LLM
            "metadata_context": { # Pasar contexto específico de metadata
                "nivel_cognitivo": item.payload.metadata.nivel_cognitivo
            }
        }
        return json.dumps(llm_input_payload, indent=2, ensure_ascii=False)


    async def _process_llm_result(self, item: Item, result: ValidationResultSchema):
        """
        Procesa el resultado del LLM: si el ítem es válido o añade hallazgos.
        Aquí es donde re-asignamos la severidad y recuperamos el fix_hint del catálogo.
        """
        has_fatal_finding = False
        processed_findings: List[ReportEntrySchema] = []

        for llm_finding in result.findings:
            # Obtener toda la información del error, incluyendo fix_hint, del catálogo centralizado
            error_info = get_error_info(llm_finding.code)
            true_severity = error_info.get("severity", "error")
            true_fix_hint = error_info.get("fix_hint", None) # Recuperar el fix_hint

            processed_findings.append(
                ReportEntrySchema(
                    code=llm_finding.code,
                    message=llm_finding.message,
                    field=llm_finding.field,
                    severity=true_severity,
                    fix_hint=true_fix_hint # Asignar el fix_hint recuperado
                )
            )
            if true_severity == "fatal":
                has_fatal_finding = True

        if processed_findings:
            item.findings.extend(processed_findings) # Añadir los hallazgos al ítem
            if has_fatal_finding:
                # Si hay algún finding fatal, el estado global del ítem es fatal_error
                self._set_status(item, "fatal", f"Validación lógica: Fallo fatal. {len(processed_findings)} errores críticos encontrados.")
            else:
                # Si hay findings pero ninguno es fatal, el estado es fail
                self._set_status(item, "fail", f"Validación lógica: Falló. {len(processed_findings)} errores encontrados.")
        else:
            # Si no hay findings, la validación fue exitosa
            self._set_status(item, "success", "Validación lógica: OK.")
