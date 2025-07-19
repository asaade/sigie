# app/pipelines/stages/validate_user_request.py

from __future__ import annotations
import json
import time
from typing import List, Dict, Any

from pydantic import BaseModel, ValidationError

from ..registry import register
from app.schemas.models import Item, ItemStatus
from app.schemas.item_schemas import ItemGenerationParams
from app.pipelines.abstractions import BaseStage
from app.pipelines.utils.stage_helpers import add_revision_log_entry
from app.pipelines.utils.llm_utils import call_llm_and_parse_json_result

class ValidatorResponse(BaseModel):
    is_valid: bool
    issues_found: List[Dict[str, Any]] = []

@register("validate_user_request")
class ValidateRequestStage(BaseStage):
    """
    Etapa inicial que valida la solicitud de generación de un usuario.
    """

    async def execute(self, items: List[Item]) -> List[Item]:
        if not items: return []

        self.logger.info(f"Starting user request validation for batch {items[0].batch_id}...")
        start_time = time.monotonic()

        representative_item = items[0]
        tokens_used = 0

        # --- CORRECCIÓN: Se añade una validación para el nombre del prompt ---
        prompt_name = self.params.get("prompt")
        if not prompt_name:
            error_msg = "Error de configuración: No se especificó el parámetro 'prompt' para la etapa en pipeline.yml."
            self._apply_result_to_batch(items, ItemStatus.FATAL, error_msg, 0, 0)
            return items

        try:
            if not representative_item.generation_params:
                raise ValueError("El campo 'generation_params' está ausente.")

            request_params = ItemGenerationParams.model_validate(representative_item.generation_params)

            llm_input = json.dumps(
                {"input_request": request_params.model_dump(mode='json')},
                ensure_ascii=False
            )

            result_obj, llm_errors, tokens_used = await call_llm_and_parse_json_result(
                prompt_name=prompt_name, # Ahora usamos la variable validada
                user_input_content=llm_input,
                stage_name=self.stage_name,
                item=representative_item,
                ctx=self.ctx,
                expected_schema=ValidatorResponse,
                **self.params,
            )

            duration_ms = int((time.monotonic() - start_time) * 1000)

            if llm_errors:
                summary = f"Fallo en la utilidad LLM: {llm_errors[0].descripcion_hallazgo}"
                self._apply_result_to_batch(items, ItemStatus.FATAL, summary, duration_ms, tokens_used)
                return items

            if not isinstance(result_obj, ValidatorResponse):
                summary = "El LLM no devolvió un objeto de respuesta válido ni errores específicos."
                self._apply_result_to_batch(items, ItemStatus.FATAL, summary, duration_ms, tokens_used)
                return items

            if result_obj.is_valid:
                comment = "La solicitud del usuario es coherente y viable. Lote aprobado para generación."
                self._apply_result_to_batch(items, ItemStatus.REQUEST_VALIDATION_SUCCESS, comment, duration_ms, tokens_used)
            else:
                error_summary = "; ".join(
                    f"'{issue.get('validation_type', 'Desconocido')}': {issue.get('problem_description', 'N/A')}"
                    for issue in result_obj.issues_found
                )
                full_comment = f"La solicitud del usuario es inválida. Razones: {error_summary}"
                self._apply_result_to_batch(items, ItemStatus.FATAL, full_comment, duration_ms, tokens_used)

        except (ValidationError, ValueError) as e:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            error_msg = f"Error al procesar los parámetros de generación: {e}"
            self._apply_result_to_batch(items, ItemStatus.FATAL, error_msg, duration_ms, tokens_used)

        return items

    def _apply_result_to_batch(self, items: List[Item], status: ItemStatus, comment: str, duration_ms: int, tokens_used: int):
        """Aplica el mismo estado y comentario a todos los ítems del lote."""
        avg_duration = duration_ms // len(items) if items else 0
        avg_tokens = tokens_used // len(items) if items else 0

        for item in items:
            add_revision_log_entry(
                item, self.stage_name, status, comment,
                tokens_used=avg_tokens, duration_ms=avg_duration
            )

        log_message = f"Batch {items[0].batch_id} update: {comment}"
        if status == ItemStatus.FATAL:
            self.logger.error(log_message)
        else:
            self.logger.info(log_message)
