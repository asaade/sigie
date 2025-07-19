# app/pipelines/builtins/finalize_item.py

from __future__ import annotations
import json
from typing import Optional

from pydantic import BaseModel

from ..registry import register
from app.schemas.models import Item, ItemStatus
from app.schemas.item_schemas import FinalEvaluationSchema
from app.pipelines.abstractions import LLMStage
from app.pipelines.utils.stage_helpers import add_revision_log_entry, handle_item_id_mismatch

@register("finalize_item")
class FinalizeItemStage(LLMStage):
    """
    Etapa final que realiza una evaluación holística de la calidad del ítem
    y le asigna un puntaje estructurado, sin modificar su contenido.
    """
    pydantic_schema = FinalEvaluationSchema

    def _prepare_llm_input(self, item: Item) -> str:
        """
        Prepara el input para el LLM, enviando el payload completo y el
        historial de cambios para un juicio de calidad final informado.
        """
        if not item.payload:
            return json.dumps({"error": "Item payload is missing or invalid."})

        # --- CORRECCIÓN ---
        # Ahora se incluye el 'change_log' en el input para el LLM.
        input_data = {
            "temp_id": str(item.temp_id),
            "item_a_evaluar": item.payload.model_dump(mode='json'),
            "historial_de_cambios": [log.model_dump(mode='json') for log in item.change_log]
        }
        return json.dumps(input_data, ensure_ascii=False)

    async def _process_llm_result(self, item: Item, result: Optional[BaseModel], tokens_used: int):
        """
        Procesa el veredicto de calidad del LLM y lo almacena en el payload del ítem.
        """
        # ... (el resto del método se mantiene igual) ...
        if not result or not isinstance(result, FinalEvaluationSchema):
            comment = f"No se recibió una estructura de evaluación válida del LLM."
            add_revision_log_entry(item, self.stage_name, ItemStatus.FATAL, comment, tokens_used=tokens_used)
            return

        if handle_item_id_mismatch(item, self.stage_name, str(item.temp_id), str(result.temp_id)):
            return

        if item.payload:
            item.payload.final_evaluation = result
            verdict = "Listo para producción" if result.is_ready_for_production else "Requiere revisión manual"
            comment = f"Éxito. Puntuación final: {result.score_total}/100. Veredicto: {verdict}."
            add_revision_log_entry(
                item, self.stage_name, ItemStatus.EVALUATION_COMPLETE,
                comment, tokens_used=tokens_used
            )
