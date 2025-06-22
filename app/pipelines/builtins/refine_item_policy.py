# Archivo actualizado: app/pipelines/builtins/refine_item_policy.py

from __future__ import annotations
import json
from typing import Type
from pydantic import BaseModel

from ..registry import register
from app.schemas.models import Item
from app.schemas.item_schemas import RefinementResultSchema
from app.pipelines.abstractions import LLMStage
from ..utils.stage_helpers import clean_specific_errors, handle_item_id_mismatch_refinement

@register("refine_item_policy")
class RefinePolicyStage(LLMStage):
    """
    Etapa de refinamiento que corrige un ítem basándose en las advertencias
    (warnings) de políticas detectadas en la etapa de validación anterior.
    """

    def _get_expected_schema(self) -> Type[BaseModel]:
        """
        Espera recibir un payload de ítem refinado del LLM.
        """
        return RefinementResultSchema

    def _prepare_llm_input(self, item: Item) -> str:
        """
        Prepara el input para el LLM. Envía el ítem junto con la lista
        de advertencias de políticas que el LLM debe solucionar.
        """
        # La lógica de negocio clave: lee desde item.warnings
        policy_warnings_to_fix = [w for w in item.warnings]

        input_payload = {
            "item": item.payload.model_dump(),
            "problems": [w.model_dump() for w in policy_warnings_to_fix]
        }
        return json.dumps(input_payload, indent=2, ensure_ascii=False)

    async def _process_llm_result(self, item: Item, result: RefinementResultSchema):
        """
        Procesa el resultado, reemplazando el payload del ítem y limpiando
        las advertencias que fueron corregidas.
        """
        # Verificación de seguridad
        if result.item_id != item.payload.item_id:
            handle_item_id_mismatch_refinement(
                item, self.stage_name, item.payload.item_id, result.item_id,
                f"{self.stage_name}.fail.id_mismatch",
                "Item ID mismatched in policy refinement response."
            )
            return

        # Aplica la corrección
        item.payload = result.item_refinado

        # Limpia las advertencias específicas que el LLM reporta haber corregido.
        fixed_codes = {correction.error_code for correction in result.correcciones_realizadas}
        if fixed_codes:
            # Reutilizamos el mismo helper, que funciona tanto para errores como para advertencias
            clean_specific_errors(item, fixed_codes)

        summary = f"Policy refinement applied. {len(fixed_codes)} issues reported as fixed."
        self._set_status(item, "success", summary)
