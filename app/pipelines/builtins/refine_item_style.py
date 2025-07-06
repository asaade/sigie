# app/pipelines/builtins/refine_item_style.py

from __future__ import annotations
import json
from typing import Type, Optional
from pydantic import BaseModel

from ..registry import register
from app.schemas.models import Item, ItemStatus
from app.schemas.item_schemas import (
    RefinementResultSchema,
)
from app.pipelines.abstractions import LLMStage
from app.pipelines.utils.stage_helpers import handle_item_id_mismatch_refinement

@register("refine_item_style")
class RefineItemStyleStage(LLMStage):
    """
    Etapa de refinamiento que mejora el estilo, redacción y claridad de un ítem.
    """

    def _get_expected_schema(self) -> Type[BaseModel]:
        """Define el esquema de la respuesta esperada del LLM."""
        return RefinementResultSchema

    def _prepare_llm_input(self, item: Item) -> str:
        """
        Prepara el input JSON para el LLM.
        Envía el ítem original para revisión de estilo.
        """
        if not item.payload:
            return json.dumps({"error": "Item payload is missing."})

        item_payload_dict = item.payload.model_dump(mode="json")

        input_payload = {
            "item_original": item_payload_dict
        }
        return json.dumps(input_payload, indent=2, ensure_ascii=False)

    async def _process_llm_result(self, item: Item, result: Optional[BaseModel]):
        """
        Procesa el resultado del LLM, actualizando el ítem con las mejoras de estilo.
        """
        if not isinstance(result, RefinementResultSchema):
            msg = "Error interno: el esquema de respuesta del LLM no es RefinementResultSchema."
            self._set_status(item, ItemStatus.FATAL, msg)
            return

        # Valida que el ID del ítem en la respuesta coincida con el original.
        if handle_item_id_mismatch_refinement(
            item, self.stage_name, str(item.item_id), str(result.item_id)
        ):
            return

        # Asigna el nuevo payload con el estilo corregido.
        item.payload = result.item_refinado

        num_correcciones = len(result.correcciones_realizadas)
        summary = f"Refinamiento de estilo aplicado. {num_correcciones} correcciones reportadas."
        self._set_status(item, ItemStatus.SUCCESS, summary, correcciones=result.correcciones_realizadas)
