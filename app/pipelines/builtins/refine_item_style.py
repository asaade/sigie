# app/pipelines/builtins/refine_item_style.py

from __future__ import annotations
import logging
import json

from typing import Type
from pydantic import BaseModel

from ..registry import register
from app.schemas.models import Item
from app.schemas.item_schemas import RefinementResultSchema

from app.pipelines.abstractions import LLMStage

from ..utils.stage_helpers import (
    clean_specific_errors,
    handle_item_id_mismatch_refinement,
)


logger = logging.getLogger(__name__)

@register("refine_item_style")
class RefineStyleStage(LLMStage):
    def _get_expected_schema(self) -> Type[BaseModel]:
        return RefinementResultSchema

    def _prepare_llm_input(self, item: Item) -> str:
        """
        Prepara el string de input para el LLM. Envía el payload completo del ítem
        junto con una lista de problemas de estilo (advertencias) para su refinamiento.
        """
        # Filtramos los hallazgos (problemas) con severidad 'warning' para este refinador.
        # Asumimos que validate_soft es la etapa que añade warnings de estilo
        # y que sus findings se distinguen por su 'severity="warning"'.
        style_warnings_to_fix = [f for f in item.findings if f.severity == 'warning']

        input_payload = {
            "item": item.payload.model_dump(mode="json"),
            "problems": [w.model_dump() for w in style_warnings_to_fix]
        }
        return json.dumps(input_payload, indent=2, ensure_ascii=False)

    async def _process_llm_result(self, item: Item, result: RefinementResultSchema):
        if result.item_id != item.payload.item_id:
            handle_item_id_mismatch_refinement(
                item, self.stage_name, item.payload.item_id, result.item_id,
                f"{self.stage_name}.fail.id_mismatch",
                "Item ID mismatched in style correction response."
            )
            return

        item.payload = result.item_refinado

        fixed_codes = {correction.error_code for correction in result.correcciones_realizadas if correction.error_code}
        if fixed_codes:
            clean_specific_errors(item, fixed_codes)

        summary = f"Style correction applied. {len(result.correcciones_realizadas)} corrections reported."
        self._set_status(item, "success", summary, corrections=result.correcciones_realizadas)
