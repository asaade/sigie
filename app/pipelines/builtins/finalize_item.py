# app/pipelines/builtins/finalize_item.py

from __future__ import annotations
import json
from typing import Type, Optional
from pydantic import BaseModel

from ..registry import register
from app.schemas.models import Item, ItemStatus
# Importar el nuevo schema que acabamos de definir
from app.schemas.item_schemas import FinalEvaluationSchema
from app.pipelines.abstractions import LLMStage

@register("finalize_item")
class FinalizeItemStage(LLMStage):
    """
    Etapa final que realiza una evaluación holística de la calidad del ítem
    y le asigna un puntaje, sin modificar su contenido.
    Compatible con la nueva arquitectura de payload.
    """

    def _get_expected_schema(self) -> Type[BaseModel]:
        """Espera recibir un resultado de evaluación final del LLM."""
        return FinalEvaluationSchema

    def _prepare_llm_input(self, item: Item) -> str:
        """
        Prepara el string de input para el LLM.
        Envía el payload completo del ítem para un juicio de calidad final.
        """
        if not item.payload:
            return json.dumps({"error": "Item payload is missing."})

        # Serializa el payload completo. El prompt del "juez final" necesita
        # ver el ítem en su totalidad para dar un veredicto informado.
        item_payload_dict = item.payload.model_dump(mode='json')
        return json.dumps(item_payload_dict, indent=2, ensure_ascii=False)

    async def _process_llm_result(self, item: Item, result: Optional[BaseModel]):
        """
        Procesa el veredicto de calidad del LLM y lo almacena en el payload del ítem.
        """
        if not isinstance(result, FinalEvaluationSchema):
            msg = "Error interno: el esquema de respuesta del LLM no es FinalEvaluationSchema."
            self._set_status(item, ItemStatus.FATAL, msg)
            return

        # Asigna el resultado de la evaluación al nuevo campo en el payload.
        # Esto enriquece el ítem con su evaluación final sin alterarlo.
        item.payload.final_evaluation = result

        summary = f"Final evaluation completed. Score: {result.score}. Verdict: {'Publishable' if result.is_publishable else 'Not Publishable'}."
        # Marcamos como éxito, ya que la evaluación se completó.
        self._set_status(item, ItemStatus.SUCCESS, summary)
