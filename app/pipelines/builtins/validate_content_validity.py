# app/pipelines/builtins/validate_content_validity.py

from __future__ import annotations
import logging
import json
from typing import List, Type
from pydantic import BaseModel # BaseModel se mantiene para el tipo de retorno de _get_expected_schema

from ..registry import register
from app.schemas.models import Item
from app.schemas.item_schemas import ReportEntrySchema, ValidationResultSchema # Mantener estos, ya que se usan directamente
from app.pipelines.abstractions import LLMStage
from app.core.error_metadata import get_error_info

logger = logging.getLogger(__name__)

@register("validate_content_validity")
class ValidateContentValidityStage(LLMStage):
    """
    Etapa de validación de la validez de contenido que utiliza un LLM para identificar errores
    de alineación curricular, precisión conceptual, unidimensionalidad y plausibilidad pedagógica de distractores.
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

        llm_input_payload = {
            "item_id": str(item.temp_id),
            "item_payload": item_dict,
        }
        return json.dumps(llm_input_payload, indent=2, ensure_ascii=False)

    async def _process_llm_result(self, item: Item, result: ValidationResultSchema):
        """
        Procesa el resultado del LLM: si el ítem es válido o añade hallazgos.
        Aquí es donde se re-asigna la severidad y se recupera el fix_hint del catálogo centralizado.
        """
        has_fatal_finding = False
        processed_findings: List[ReportEntrySchema] = []

        for llm_finding in result.findings:
            error_info = get_error_info(llm_finding.code)
            true_severity = error_info.get("severity", "error")
            true_fix_hint = error_info.get("fix_hint", None)

            processed_findings.append(
                ReportEntrySchema(
                    code=llm_finding.code,
                    message=llm_finding.message,
                    field=llm_finding.field,
                    severity=true_severity,
                    fix_hint=true_fix_hint
                )
            )
            if true_severity == "fatal":
                has_fatal_finding = True

        if processed_findings:
            item.findings.extend(processed_findings)
            if has_fatal_finding:
                self._set_status(item, "fatal", f"Validación de contenido: Fallo fatal. {len(processed_findings)} errores críticos encontrados.")
            else:
                self._set_status(item, "fail", f"Validación de contenido: Falló. {len(processed_findings)} problemas encontrados.")
        else:
            self._set_status(item, "success", "Validación de contenido: OK.")
