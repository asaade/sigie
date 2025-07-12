# app/pipelines/stages/validate_user_request.py

from __future__ import annotations
import json
from typing import List, Dict, Any

from pydantic import BaseModel, ValidationError

# Importaciones del proyecto
from ..registry import register
from app.schemas.models import Item, ItemStatus
from app.schemas.item_schemas import ItemGenerationParams
from app.pipelines.abstractions import BaseStage
from app.pipelines.utils.stage_helpers import add_revision_log_entry
from app.pipelines.utils.llm_utils import call_llm_and_parse_json_result

# Esquema para la Respuesta del LLM Validador
class ValidatorResponse(BaseModel):
    is_valid: bool
    issues_found: List[Dict[str, Any]] = []


@register("validate_user_request")
class ValidateRequestStage(BaseStage):
    """
    Etapa inicial que valida la solicitud de generación de un usuario.
    Se ejecuta una sola vez por lote para validar los parámetros de generación
    y luego aplica el resultado a todos los ítems del lote.
    """
    prompt_name = "00_agent_request_validator.md"

    async def execute(self, items: List[Item]) -> List[Item]:
        """
        Ejecuta la validación una vez para el lote completo.
        """
        if not items:
            return []

        self.logger.info(f"Starting user request validation for batch {items[0].batch_id} ({len(items)} items).")

        representative_item = items[0]

        try:
            if not representative_item.generation_params:
                raise ValueError("El campo 'generation_params' está ausente en el ítem representativo.")

            # Se usa `model_validate` para validar un diccionario, en lugar de `model_validate_json` que espera un string.
            request_params = ItemGenerationParams.model_validate(representative_item.generation_params)

            # Se prepara el input para la utilidad LLM.
            llm_input = json.dumps(
                {"input_request": request_params.model_dump(mode='json')},
                ensure_ascii=False,
                indent=2
            )

            result_obj, llm_errors, _ = await call_llm_and_parse_json_result(
                prompt_name=self.prompt_name,
                user_input_content=llm_input,
                stage_name=self.stage_name,
                item=representative_item,
                ctx=self.ctx,
                expected_schema=ValidatorResponse,
                **self.params,
            )

            if llm_errors:
                summary = f"Fallo en la utilidad LLM: {llm_errors[0].descripcion_hallazgo}"
                self._apply_result_to_batch(items, ItemStatus.FATAL, summary)
                return items

            if not result_obj:
                summary = "El LLM no devolvió un resultado válido ni errores específicos."
                self._apply_result_to_batch(items, ItemStatus.FATAL, summary)
                return items

            # Se procesa el resultado y se aplica a todo el lote
            if result_obj.is_valid:
                comment = "La solicitud del usuario es coherente y viable. Lote aprobado para generación."
                self._apply_result_to_batch(items, ItemStatus.REQUEST_VALIDATION_SUCCESS, comment)
            else:
                error_summary = "; ".join(
                    f"'{issue.get('validation_type', 'Desconocido')}': {issue.get('problem_description', 'N/A')}"
                    for issue in result_obj.issues_found
                )
                full_comment = f"La solicitud del usuario es inválida. Razones: {error_summary}"
                self._apply_result_to_batch(items, ItemStatus.FATAL, full_comment)

        except (ValidationError, ValueError) as e:
            self.logger.error(f"Error crítico procesando los parámetros de solicitud para el lote {items[0].batch_id}: {e}", exc_info=True)
            error_msg = f"Error al procesar los parámetros de generación: {e}"
            self._apply_result_to_batch(items, ItemStatus.FATAL, error_msg)

        return items

    def _apply_result_to_batch(self, items: List[Item], status: ItemStatus, comment: str):
        """Aplica el mismo estado y comentario a todos los ítems del lote."""
        for item in items:
            add_revision_log_entry(item, self.stage_name, status, comment)

        log_message = f"Batch {items[0].batch_id} update: {comment}"
        if status == ItemStatus.FATAL:
            self.logger.error(log_message)
        else:
            self.logger.info(log_message)
