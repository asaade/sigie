# app/pipelines/builtins/refine_item_style.py

from __future__ import annotations
import json
from typing import Optional

from pydantic import BaseModel

from ..registry import register
from app.schemas.models import Item, ItemStatus
from app.schemas.item_schemas import RefinementResultSchema
from app.pipelines.abstractions import LLMStage
from app.pipelines.utils.stage_helpers import (
    add_revision_log_entry,
    handle_item_id_mismatch,
)

@register("refine_item_style")
class RefineItemStyleStage(LLMStage):
    """
    Etapa de refinamiento final que mejora el estilo, redacción y claridad de un ítem.
    Esta etapa no depende de hallazgos previos; siempre se ejecuta para pulir el ítem.
    """

    # Define el prompt y el esquema Pydantic para la clase base LLMStage
    prompt_file = "04_agente_refinador_estilo.md"
    pydantic_schema = RefinementResultSchema

    def _prepare_llm_input(self, item: Item) -> str:
        """
        Prepara el input JSON para el LLM.
        Envía el ítem original para una revisión y mejora de estilo.
        """
        if not item.payload:
            # La clase base LLMStage ya maneja este caso marcando el ítem como FATAL.
            return json.dumps({"error": "Item payload is missing."})

        # Preparamos un objeto que contiene tanto el ítem como su ID temporal.
        input_payload = {
            "temp_id": str(item.temp_id),
            "item_a_mejorar": item.payload.model_dump(mode="json"),
        }
        return json.dumps(input_payload, ensure_ascii=False)

    async def _process_llm_result(self, item: Item, result: Optional[BaseModel]):
        """
        Procesa el resultado del LLM, actualizando el ítem con las mejoras de estilo.
        """
        if not result or not isinstance(result, RefinementResultSchema):
            comment = f"No se recibió una estructura de refinamiento válida del LLM. Se recibió: {type(result).__name__}."
            add_revision_log_entry(item, self.stage_name, ItemStatus.FATAL, comment)
            return

        # Verificación de consistencia del temp_id.
        if handle_item_id_mismatch(item, self.stage_name, str(item.temp_id), str(result.temp_id)):
            return

        # Asigna el nuevo payload con el estilo corregido.
        item.payload = result.item_refinado

        # 1. Se persiste el historial de cambios de estilo en el log.
        if result.correcciones_realizadas:
            item.change_log.extend(result.correcciones_realizadas)

        # 2. Se actualiza el comentario del log para reflejar el registro.
        num_correcciones = len(result.correcciones_realizadas)
        comment = f"Refinamiento de estilo aplicado. {num_correcciones} mejoras registradas en el change_log."
        add_revision_log_entry(item, self.stage_name, ItemStatus.STYLE_REFINEMENT_SUCCESS, comment)
