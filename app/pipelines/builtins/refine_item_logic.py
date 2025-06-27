# app/pipelines/builtins/refine_item_logic.py

from __future__ import annotations
import json
from typing import Type
from pydantic import BaseModel

from ..registry import register
from app.schemas.models import Item
from app.schemas.item_schemas import RefinementResultSchema
from app.pipelines.abstractions import LLMStage
from ..utils.stage_helpers import clean_specific_errors, handle_item_id_mismatch_refinement

@register("refine_item_logic")
class RefineLogicStage(LLMStage):
    """
    Etapa de refinamiento lógico que corrige ítems basándose en los hallazgos
    (findings) detectados por una etapa de validación previa.
    """

    def _get_expected_schema(self) -> Type[BaseModel]:
        """
        Define que esperamos un objeto de refinamiento del LLM, que contiene
        el payload del ítem corregido.
        """
        return RefinementResultSchema

    def _prepare_llm_input(self, item: Item) -> str:
        """
        Prepara el string de input para el LLM.
        """
        logic_problems_to_fix = [f for f in item.findings if f.severity == 'error'] # O el criterio que uses para filtrar para el LLM

        input_payload = {
            "item_id": str(item.payload.item_id), # CAMBIO CRÍTICO: Convertir UUID a string
            "item_payload": item.payload.model_dump(mode="json"),
            "problems": [p.model_dump(mode="json") for p in logic_problems_to_fix]
        }
        return json.dumps(input_payload, indent=2, ensure_ascii=False)

    async def _process_llm_result(self, item: Item, result: RefinementResultSchema):
        """
        Procesa el resultado del LLM: reemplaza el payload del ítem por la
        versión refinada y limpia los errores que fueron corregidos.
        """
        # Verificación de seguridad para asegurar que el LLM corrigió el ítem correcto.
        if result.item_id != item.payload.item_id:
            handle_item_id_mismatch_refinement(
                item, self.stage_name, item.payload.item_id, result.item_id,
                f"{self.stage_name}.fail.id_mismatch",
                "Item ID mismatched in refinement response."
            )
            return

        # El corazón del refinamiento: reemplazar el payload antiguo por el nuevo.
        item.payload = result.item_refinado

        # Limpiar los errores específicos que el LLM reporta haber corregido.
        fixed_codes = {correction.error_code for correction in result.correcciones_realizadas if correction.error_code}
        if fixed_codes:
            clean_specific_errors(item, fixed_codes) # Ahora usa la versión actualizada del helper

        summary = f"Refinement applied. {len(fixed_codes)} issues reported as fixed."
        self._set_status(item, "success", summary)
