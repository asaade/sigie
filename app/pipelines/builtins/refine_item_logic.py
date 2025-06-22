# Archivo actualizado: app/pipelines/builtins/refine_item_logic.py

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
    Etapa de refinamiento lógico que corrige ítems basándose en los errores
    detectados por una etapa de validación previa.
    """

    def _get_expected_schema(self) -> Type[BaseModel]:
        """
        Define que esperamos un objeto de refinamiento del LLM, que contiene
        el payload del ítem corregido.
        """
        return RefinementResultSchema

    def _prepare_llm_input(self, item: Item) -> str:
        """
        Prepara el input para el LLM. Es crucial enviar no solo el ítem,
        sino también la lista de problemas que el LLM debe solucionar.
        """
        # Filtramos para enviar solo los errores, no las advertencias.
        logic_errors_to_fix = [err for err in item.errors if err.severity == 'error']

        input_payload = {
            "item": item.payload.model_dump(),
            "problems": [err.model_dump() for err in logic_errors_to_fix]
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
        fixed_codes = {correction.error_code for correction in result.correcciones_realizadas}
        clean_specific_errors(item, fixed_codes)

        summary = f"Refinement applied. {len(fixed_codes)} issues reported as fixed."
        self._set_status(item, "success", summary)
