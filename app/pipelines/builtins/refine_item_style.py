# app/pipelines/builtins/refine_item_style.py

from __future__ import annotations
import json
from typing import Type, Optional
from pydantic import BaseModel

from ..registry import register
from app.schemas.models import Item
from app.schemas.item_schemas import (
    RefinementResultSchema,
)
from app.pipelines.abstractions import LLMStage
from app.pipelines.utils.stage_helpers import handle_item_id_mismatch_refinement

@register("refine_item_style")
class RefineItemStyleStage(LLMStage):
    """
    Etapa de refinamiento que mejora el estilo, redacción y claridad de un ítem.
    No depende de hallazgos previos y es compatible con la nueva arquitectura.
    """

    def _get_expected_schema(self) -> Type[BaseModel]:
        """Espera recibir un payload de ítem refinado del LLM."""
        return RefinementResultSchema

    def _prepare_llm_input(self, item: Item) -> str:
        """
        Prepara el string de input para el LLM.
        Envía el ítem original (con la nueva estructura) para una revisión holística.
        """
        if not item.payload:
            return json.dumps({"error": "Item payload is missing."})

        # Serializa el payload completo del ítem. El prompt de estilo
        # está diseñado para tomar el ítem y mejorarlo sin necesidad de
        # una lista de errores.
        item_payload_dict = item.payload.model_dump(mode="json")

        # A diferencia de otros refinadores, no enviamos "hallazgos".
        # El input es simplemente el ítem a mejorar.
        input_payload = {
            "item_original": item_payload_dict
        }
        return json.dumps(input_payload, indent=2, ensure_ascii=False)

    async def _process_llm_result(self, item: Item, result: Optional[BaseModel]):
        """
        Procesa el resultado, reemplazando el payload del ítem con la
        versión estilísticamente mejorada.
        """
        if not isinstance(result, RefinementResultSchema):
            msg = "Error interno: el esquema de respuesta del LLM no es RefinementResultSchema."
            self._set_status(item, "fatal", msg)
            return

        # Valida que el ID del ítem en la respuesta coincida.
        if handle_item_id_mismatch_refinement(
            item, self.stage_name, str(item.payload.item_id), str(result.item_id)
        ):
            return

        # Asigna el nuevo payload con el estilo corregido.
        # El `result.item_refinado` ya es un ItemPayloadSchema validado.
        item.payload = result.item_refinado

        # Aunque este agente no corrige errores específicos, podría reportar
        # las mejoras realizadas.
        num_corrections = len(result.correcciones_realizadas)
        summary = f"Refinamiento de estilo aplicado. {num_corrections} correcciones reportadas."
        self._set_status(item, "success", summary, corrections=result.correcciones_realizadas)
