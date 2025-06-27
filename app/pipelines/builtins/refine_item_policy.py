# app/pipelines/builtins/refine_item_policy.py

from __future__ import annotations
import json # Necesario para json.dumps en _prepare_llm_input
from typing import Type # Necesario para Type[BaseModel]
from pydantic import BaseModel # Necesario para Type[BaseModel]

from ..registry import register
from app.schemas.models import Item
from app.schemas.item_schemas import RefinementResultSchema
from app.pipelines.abstractions import LLMStage
from app.pipelines.utils.stage_helpers import clean_specific_errors, handle_item_id_mismatch_refinement # handle_item_id_mismatch_refinement se mantiene como helper por ahora

@register("refine_item_policy")
class RefinePolicyStage(LLMStage):
    """
    Etapa de refinamiento que corrige un ítem basándose en los hallazgos
    de políticas (con severidad 'warning') detectados previamente.
    """

    def _get_expected_schema(self) -> Type[BaseModel]:
        """Espera recibir un payload de ítem refinado del LLM."""
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
        Procesa el resultado, reemplazando el payload del ítem por la
        versión con las políticas corregidas y limpiando los hallazgos.
        """
        # Verificación de seguridad: asegurar que el LLM corrigió el ítem correcto.
        if result.item_id != item.payload.item_id:
            # Usamos el helper de stage_helpers
            handle_item_id_mismatch_refinement(
                item, self.stage_name, item.payload.item_id, result.item_id,
                f"{self.stage_name}.fail.id_mismatch",
                "Item ID mismatched in policy refinement response."
            )
            return

        # Aplica la corrección: reemplaza el payload del ítem
        item.payload = result.item_refinado

        # Limpia los hallazgos (errores/advertencias) que el LLM reporta haber corregido.
        # Esto incluye limpiar hallazgos LLM genéricos de fallo de llamada/parseo si esta etapa corrigió el problema.
        fixed_codes = {correction.error_code for correction in result.correcciones_realizadas if correction.error_code}
        if fixed_codes:
            clean_specific_errors(item, fixed_codes) # Usamos el helper de stage_helpers

        # Marcar el estado de éxito y registrar la auditoría.
        summary = f"Policy refinement applied. {len(fixed_codes)} issues reported as fixed."
        self._set_status(item, "success", summary, corrections=result.correcciones_realizadas)
