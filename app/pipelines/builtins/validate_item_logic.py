# app/pipelines/builtins/validate_item_logic.py

from __future__ import annotations
import json
from typing import Optional

from pydantic import BaseModel

from ..registry import register
from app.schemas.models import Item, ItemStatus
from app.schemas.item_schemas import ValidationResultSchema
from app.pipelines.abstractions import LLMStage
from app.pipelines.utils.stage_helpers import (
    add_revision_log_entry,
    get_error_message_from_validation_result,
    handle_item_id_mismatch,
)

@register("validate_item_logic")
class ValidateItemLogicStage(LLMStage):
    """
    Etapa de validación que revisa la consistencia lógica interna de un ítem
    usando el prompt '02_agent_razonamiento.md'.
    """
    prompt_file = "02_agent_razonamiento.md"
    pydantic_schema = ValidationResultSchema

    def _prepare_llm_input(self, item: Item) -> str:
        """
        Prepara el string de input para el LLM.
        """
        if not item.payload:
            return json.dumps({"error": "Item payload is missing."})

        input_data = {
            "temp_id": str(item.temp_id),
            "item_a_validar": item.payload.model_dump(mode='json')
        }
        return json.dumps(input_data, ensure_ascii=False)

    async def _process_llm_result(self, item: Item, result: Optional[BaseModel]):
        """
        Procesa el resultado de la validación lógica y actualiza el estado del ítem.
        """
        if not result or not isinstance(result, ValidationResultSchema):
            comment = f"No se recibió una estructura de validación válida del LLM. Se recibió: {type(result).__name__}."
            add_revision_log_entry(item, self.stage_name, ItemStatus.FATAL, comment)
            return

        if handle_item_id_mismatch(item, self.stage_name, str(item.temp_id), str(result.temp_id)):
            return

        if not result.hallazgos:
            comment = "Validación lógica: OK."
            add_revision_log_entry(item, self.stage_name, ItemStatus.LOGIC_VALIDATION_SUCCESS, comment)
        else:
            # --- CORRECCIÓN CRÍTICA ---
            # Si hay hallazgos, DEBEN adjuntarse al ítem para que la
            # siguiente etapa de refinamiento pueda usarlos.
            item.findings.extend(result.hallazgos)

            summary = get_error_message_from_validation_result(result, "Lógica")
            add_revision_log_entry(item, self.stage_name, ItemStatus.LOGIC_VALIDATION_NEEDS_REVISION, summary)
            self.logger.warning(f"Item {item.temp_id} needs logic revision. Findings: {summary}")
