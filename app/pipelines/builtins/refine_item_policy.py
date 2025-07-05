# app/pipelines/builtins/refine_item_policy.py

from __future__ import annotations
import json
from typing import Type, Optional, List
from pydantic import BaseModel

from ..registry import register
from app.schemas.models import Item
from app.schemas.item_schemas import (
    RefinementResultSchema,
    ReportEntrySchema,
)
from app.pipelines.abstractions import LLMStage
from app.pipelines.utils.stage_helpers import (
    clean_specific_errors,
    handle_item_id_mismatch_refinement,
)

@register("refine_item_policy")
class RefineItemPolicyStage(LLMStage):
    """
    Etapa de refinamiento que corrige un ítem basándose en hallazgos de políticas.
    Actualizado para ser compatible con la nueva arquitectura de payload.
    """

    def _get_expected_schema(self) -> Type[BaseModel]:
        """Espera recibir un payload de ítem refinado del LLM."""
        return RefinementResultSchema

    def _prepare_llm_input(self, item: Item) -> str:
        """
        Prepara el string de input para el LLM.
        Incluye el ítem original (con la nueva estructura) y los hallazgos a corregir.
        """
        if not item.payload or not item.findings:
            return json.dumps({"error": "Item payload or findings are missing."})

        # Serializa el payload del ítem con la nueva estructura anidada.
        item_payload_dict = item.payload.model_dump(mode="json")

        # Filtra solo los hallazgos de políticas (ej. errores 'E3xx').
        relevant_problems: List[ReportEntrySchema] = [
            f for f in item.findings if f.code.startswith('E3')
        ]

        input_payload = {
            "item_original": item_payload_dict,
            "hallazgos_a_corregir": [p.model_dump(mode="json") for p in relevant_problems]
        }
        return json.dumps(input_payload, indent=2, ensure_ascii=False)

    async def _process_llm_result(self, item: Item, result: Optional[BaseModel]):
        """
        Procesa el resultado, reemplazando el payload del ítem con la
        versión corregida por el LLM.
        """
        if not isinstance(result, RefinementResultSchema):
            msg = "Error interno: el esquema de la respuesta del LLM no es RefinementResultSchema."
            self._set_status(item, "fatal", msg)
            return

        # Valida que el ID del ítem en la respuesta coincida.
        if handle_item_id_mismatch_refinement(
            item, self.stage_name, str(item.payload.item_id), str(result.item_id)
        ):
            return

        # Asigna el nuevo payload corregido y ya validado por Pydantic.
        item.payload = result.item_refinado

        # Limpia los errores que el LLM reporta haber corregido.
        fixed_codes = {correction.error_code for correction in result.correcciones_realizadas}
        if fixed_codes:
            clean_specific_errors(item, fixed_codes)

        summary = f"Refinamiento de políticas aplicado. {len(result.correcciones_realizadas)} correcciones realizadas."
        self._set_status(item, "success", summary, corrections=result.correcciones_realizadas)
