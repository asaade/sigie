# app/pipelines/builtins/finalize_item.py

from __future__ import annotations
from typing import Type
from pydantic import BaseModel

from ..registry import register
from app.schemas.models import Item
from app.schemas.item_schemas import FinalEvaluationSchema
from app.pipelines.abstractions import LLMStage

@register("finalize_item")
class FinalizeItemStage(LLMStage):
    """
    Etapa final de evaluación cualitativa de un ítem.
    Un LLM emite un juicio final sobre la calidad del ítem sin modificarlo.
    """

    def _get_expected_schema(self) -> Type[BaseModel]:
        """
        Espera recibir un objeto con la evaluación final del ítem.
        """
        return FinalEvaluationSchema

    def _prepare_llm_input(self, item: Item) -> str:
        """
        Prepara el input para el LLM enviando el payload completo del ítem
        final para su evaluación.
        """
        return item.payload.model_dump_json(indent=2)

    async def _process_llm_result(self, item: Item, result: FinalEvaluationSchema):
        """
        Procesa el resultado de la evaluación, adjuntándolo al ítem y
        actualizando el estado a 'finalized'.
        """
        # Adjunta la evaluación completa al objeto Item.
        item.final_evaluation = result

        # El estado final del ítem dependerá del veredicto del evaluador.
        if result.is_publishable:
            summary = f"Final evaluation completed. Score: {result.score}. Verdict: Publishable."
            self._set_status(item, "success", summary)
        else:
            summary = f"Final evaluation completed. Score: {result.score}. Verdict: Not Publishable. Reason: {result.justification}"
            # Se marca como fallo para que pueda ser filtrado fácilmente.
            self._set_status(item, "fail", summary)
