# app/pipelines/builtins/generate_items.py

from __future__ import annotations
import json
import time
from typing import List
from pydantic import ValidationError

from ..registry import register
from app.schemas.models import Item, ItemStatus
from app.schemas.item_schemas import ItemPayloadSchema
from app.pipelines.abstractions import BaseStage
from app.pipelines.utils.stage_helpers import add_revision_log_entry
from app.pipelines.utils.llm_utils import call_llm_and_parse_json_result

@register("generate_items")
class GenerateItemsStage(BaseStage):
    """
    Etapa inicial del pipeline que genera un lote de ítems.
    Hereda de BaseStage por su lógica única de "uno a muchos".
    """

    async def execute(self, items: List[Item]) -> List[Item]:
        if not items:
            return items

        start_time = time.monotonic()
        representative_item = items[0]
        tokens_used = 0

        # --- CORRECCIÓN: Se añade una validación para el nombre del prompt ---
        prompt_name = self.params.get("prompt")
        if not prompt_name:
            error_msg = "Error de configuración: No se especificó el parámetro 'prompt' para la etapa 'generate_items' en pipeline.yml."
            self._set_status_for_all(items, ItemStatus.FATAL, error_msg, 0, 0)
            return items

        try:
            llm_input = self._prepare_llm_input(representative_item)
        except ValueError as e:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            self._set_status_for_all(items, ItemStatus.FATAL, str(e), duration_ms, tokens_used)
            return items

        result_str, llm_errors, tokens_used = await call_llm_and_parse_json_result(
            prompt_name=prompt_name, # Ahora usamos la variable validada
            user_input_content=llm_input,
            stage_name=self.stage_name,
            item=representative_item,
            ctx=self.ctx,
            expected_schema=None,  # Esperamos una lista JSON en un string
            **self.params
        )

        duration_ms = int((time.monotonic() - start_time) * 1000)

        if llm_errors:
            error_summary = f"Fallo en la utilidad LLM: {llm_errors[0].descripcion_hallazgo}"
            self._set_status_for_all(items, ItemStatus.FATAL, error_summary, duration_ms, tokens_used)
        elif result_str:
            await self._process_llm_result(items, result_str, duration_ms, tokens_used)
        else:
            summary = "El LLM no devolvió un resultado válido para la generación."
            self._set_status_for_all(items, ItemStatus.FATAL, summary, duration_ms, tokens_used)

        return items

    def _prepare_llm_input(self, item: Item) -> str:
        """Prepara el input JSON para el LLM."""
        if not item.generation_params:
            raise ValueError(f"Ítem {item.temp_id} no tiene parámetros de generación.")
        return json.dumps(item.generation_params, ensure_ascii=False)

    async def _process_llm_result(self, items: List[Item], result_str: str, duration_ms: int, tokens_used: int):
        """Procesa la respuesta del LLM, validando y asignando cada payload."""
        try:
            cleaned_json_str = result_str.strip().removeprefix("```json").removesuffix("```").strip()
            if not cleaned_json_str:
                raise ValueError("La respuesta del LLM estaba vacía después de la limpieza.")

            generated_payloads = json.loads(cleaned_json_str)

            if not isinstance(generated_payloads, list):
                raise TypeError(f"La respuesta del LLM no es una lista. Tipo: {type(generated_payloads).__name__}")

        except (json.JSONDecodeError, TypeError, ValueError) as e:
            summary = f"Error procesando la respuesta del LLM: {e}. Respuesta: {result_str[:500]}..."
            self._set_status_for_all(items, ItemStatus.FATAL, summary, duration_ms, tokens_used)
            return

        if len(generated_payloads) != len(items):
            summary = f"El LLM generó {len(generated_payloads)} ítems, pero se esperaban {len(items)}."
            self._set_status_for_all(items, ItemStatus.FATAL, summary, duration_ms, tokens_used)
            return

        avg_duration = duration_ms // len(items) if items else 0
        avg_tokens = tokens_used // len(items) if items else 0

        for i, payload_dict in enumerate(generated_payloads):
            target_item = items[i]
            try:
                validated_payload = ItemPayloadSchema.model_validate(payload_dict)
                target_item.payload = validated_payload

                add_revision_log_entry(
                    item=target_item, stage_name=self.stage_name,
                    status=ItemStatus.GENERATION_SUCCESS,
                    comment="Ítem generado y validado exitosamente.",
                    duration_ms=avg_duration, tokens_used=avg_tokens
                )
            except ValidationError as e:
                error_summary = f"Error de validación Pydantic para el ítem {i+1}: {e.errors()}"
                add_revision_log_entry(
                    item=target_item, stage_name=self.stage_name,
                    status=ItemStatus.FATAL, comment=error_summary,
                    duration_ms=avg_duration, tokens_used=avg_tokens
                )

    def _set_status_for_all(self, items: List[Item], status: ItemStatus, summary: str, duration_ms: int, tokens_used: int):
        """Helper para establecer el mismo estado de error para todo el lote."""
        avg_duration = duration_ms // len(items) if items else 0
        avg_tokens = tokens_used // len(items) if items else 0
        for item_in_batch in items:
            add_revision_log_entry(
                item=item_in_batch,
                stage_name=self.stage_name,
                status=status,
                comment=summary,
                duration_ms=avg_duration, tokens_used=avg_tokens
            )
