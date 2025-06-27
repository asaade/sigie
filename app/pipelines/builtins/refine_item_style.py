# app/pipelines/builtins/refine_item_style.py

from __future__ import annotations
import logging
import json

from typing import Type, Optional, List # Asegurar que List esté importado
from pydantic import BaseModel

from ..registry import register
from app.schemas.models import Item
from app.schemas.item_schemas import RefinementResultSchema, ReportEntrySchema # Importar ReportEntrySchema

from app.pipelines.abstractions import LLMStage

from ..utils.stage_helpers import (
    clean_specific_errors,
    handle_item_id_mismatch_refinement,
)


logger = logging.getLogger(__name__)

@register("refine_item_style")
class RefineStyleStage(LLMStage):
    def _get_expected_schema(self) -> Type[BaseModel]:
        return RefinementResultSchema

    def _prepare_llm_input(self, item: Item) -> str: # Siempre devuelve str
        """
        Prepara el string de input para el LLM.
        Incluye los warnings de estilo relevantes, o una lista vacía de problemas si no hay.
        Siempre devuelve un JSON, incluso si no hay problemas explícitos, para permitir la revisión proactiva del LLM.
        """
        # Filtrar los findings de severidad 'warning' para esta etapa de refinamiento de estilo.
        # Esto incluye warnings generados por validate_soft o cualquier otro warning acumulado.
        relevant_problems_to_fix: List[ReportEntrySchema] = [
            f for f in item.findings if f.severity == 'warning'
        ]

        # Asegurarse de que el payload del ítem exista antes de intentar serializarlo
        if not item.payload:
            self.logger.error(f"Item {item.temp_id} has no payload for _prepare_llm_input in {self.stage_name}.")
            # Devolver un JSON de error para que sea capturado por el manejo de errores de LLMStage
            return json.dumps({"error": "No item payload available."})

        input_payload = {
            "item_id": str(item.payload.item_id),
            "item_payload": item.payload.model_dump(mode="json"),
            "problems": [p.model_dump(mode="json") for p in relevant_problems_to_fix] # 'problems' puede ser una lista vacía
        }
        return json.dumps(input_payload, indent=2, ensure_ascii=False)

    async def _process_llm_result(self, item: Item, result: RefinementResultSchema): # result es siempre RefinementResultSchema
        """
        Procesa el resultado del LLM: reemplaza el payload del ítem por la
        versión refinada y limpia los hallazgos.
        """
        # Ya no hay necesidad de 'if result is None:' porque _prepare_llm_input siempre devuelve un string.

        if result.item_id != item.payload.item_id:
            handle_item_id_mismatch_refinement(
                item, self.stage_name, item.payload.item_id, result.item_id,
                f"{self.stage_name}.fail.id_mismatch",
                "Item ID mismatched in style correction response."
            )
            return

        item.payload = result.item_refinado

        fixed_codes = {correction.error_code for correction in result.correcciones_realizadas if correction.error_code}
        if fixed_codes:
            clean_specific_errors(item, fixed_codes)

        summary = f"Refinamiento de estilo aplicado. {len(result.correcciones_realizadas)} correcciones reportadas."
        self._set_status(item, "success", summary, corrections=result.correcciones_realizadas)
