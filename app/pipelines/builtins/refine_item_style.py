# app/pipelines/builtins/refine_item_style.py

from __future__ import annotations
import json
from typing import Type
from pydantic import BaseModel

from ..registry import register
from app.schemas.models import Item
from app.schemas.item_schemas import RefinementResultSchema
from app.pipelines.abstractions import LLMStage
from ..utils.stage_helpers import clean_specific_errors, handle_item_id_mismatch_refinement

@register("correct_item_style")
class CorrectStyleStage(LLMStage):
    """
    Aplica correcciones de estilo y formato a un ítem en un solo paso.
    Esta etapa no depende de una validación previa; el LLM debe
    identificar y aplicar las mejoras directamente.
    """

    def _get_expected_schema(self) -> Type[BaseModel]:
        """
        Espera recibir un payload de ítem refinado, por lo que reutiliza
        el esquema de refinamiento estándar.
        """
        return RefinementResultSchema

    def _prepare_llm_input(self, item: Item) -> str:
        """
        Prepara el input para el LLM. Envía el ítem actual sin una lista
        de problemas preexistentes, ya que el LLM debe realizar la revisión.
        """
        # Se envía un array de 'problems' vacío para mantener una estructura
        # de input consistente con el refinador lógico si el prompt lo requiere.
        input_payload = {
            "item": item.payload.model_dump(),
            "problems": []
        }
        return json.dumps(input_payload, indent=2, ensure_ascii=False)

    async def _process_llm_result(self, item: Item, result: RefinementResultSchema):
        """
        Procesa el resultado reemplazando el payload del ítem por la
        versión con el estilo corregido.
        """
        # Verificación de seguridad
        if result.item_id != item.payload.item_id:
            handle_item_id_mismatch_refinement(
                item, self.stage_name, item.payload.item_id, result.item_id,
                f"{self.stage_name}.fail.id_mismatch",
                "Item ID mismatched in style correction response."
            )
            return

        # Aplica la corrección
        item.payload = result.item_refinado

        # Limpia errores que el LLM pudo haber corregido incidentalmente
        fixed_codes = {correction.error_code for correction in result.correcciones_realizadas}
        if fixed_codes:
            clean_specific_errors(item, fixed_codes)

        summary = f"Style correction applied. {len(fixed_codes)} issues reported as fixed."
        self._set_status(item, "success", summary)
