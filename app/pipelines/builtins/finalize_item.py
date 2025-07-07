# app/pipelines/builtins/finalize_item.py

from __future__ import annotations
import json
from typing import Optional

from pydantic import BaseModel

from ..registry import register
from app.schemas.models import Item, ItemStatus
from app.schemas.item_schemas import FinalEvaluationSchema, ItemPayloadSchema
from app.pipelines.abstractions import LLMStage
from app.pipelines.utils.stage_helpers import (
    add_revision_log_entry,
    handle_item_id_mismatch,
)

@register("finalize_item")
class FinalizeItemStage(LLMStage):
    """
    Etapa final que realiza una evaluación holística de la calidad del ítem
    y le asigna un puntaje estructurado, sin modificar su contenido.
    Utiliza el prompt '07_agent_final.md' y espera una respuesta que se
    ajuste a FinalEvaluationSchema.
    """

    # Define el prompt y el esquema Pydantic para la clase base LLMStage
    prompt_file = "07_agent_final.md"
    pydantic_schema = FinalEvaluationSchema

    def _prepare_llm_input(self, item: Item) -> str:
        """
        Prepara el string de input para el LLM.
        Envía un objeto JSON que contiene el temp_id y el payload completo del
        ítem para el juicio de calidad final.
        """
        if not item.payload or not isinstance(item.payload, ItemPayloadSchema):
            # La clase base LLMStage ya maneja este caso marcando el ítem como FATAL.
            return json.dumps({"error": "Item payload is missing or invalid."})

        # Preparamos un objeto que contiene tanto el ítem como su ID temporal
        # para que el LLM lo devuelva y podamos verificar la consistencia.
        input_data = {
            "temp_id": str(item.temp_id),
            "item_a_evaluar": item.payload.model_dump(mode='json')
        }

        return json.dumps(input_data, ensure_ascii=False)

    async def _process_llm_result(self, item: Item, result: Optional[BaseModel]):
        """
        Procesa el veredicto de calidad del LLM, valida su consistencia
        y lo almacena en el payload del ítem.
        """
        if not result or not isinstance(result, FinalEvaluationSchema):
            comment = f"No se recibió una estructura de evaluación válida del LLM. Se recibió: {type(result).__name__}."
            add_revision_log_entry(item, self.stage_name, ItemStatus.FATAL, comment)
            return

        # Verificación de consistencia: el temp_id en la respuesta del LLM
        # debe coincidir con el del ítem que estamos procesando.
        if handle_item_id_mismatch(item, self.stage_name, str(item.temp_id), str(result.temp_id)):
            return

        # Si todo es correcto, asignamos el resultado de la evaluación
        # al nuevo campo en el payload del ítem.
        if item.payload:
            item.payload.final_evaluation = result

            verdict = "Ready for production" if result.is_ready_for_production else "Needs manual review"
            comment = (
                f"Final evaluation complete. "
                f"Score: {result.score_total}/100. Verdict: {verdict}."
            )
            add_revision_log_entry(item, self.stage_name, ItemStatus.EVALUATION_COMPLETE, comment)
        else:
            # Caso improbable, pero es una buena práctica manejarlo.
            comment = "Item payload was lost before final evaluation could be assigned."
            add_revision_log_entry(item, self.stage_name, ItemStatus.FATAL, comment)
