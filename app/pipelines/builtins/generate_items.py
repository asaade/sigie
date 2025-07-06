# app/pipelines/builtins/generate_items.py

from __future__ import annotations
import json
from typing import Type, List, Optional
from pydantic import BaseModel, ValidationError

from ..registry import register
from app.schemas.models import Item, ItemStatus
from app.schemas.item_schemas import ItemPayloadSchema
from app.pipelines.abstractions import LLMStage
from app.pipelines.utils.stage_helpers import update_item_status_and_audit
from app.pipelines.utils.llm_utils import call_llm_and_parse_json_result

@register("generate_items")
class GenerateItemsStage(LLMStage):
    """
    Etapa inicial del pipeline que genera un lote de ítems.
    Crea el payload inicial del ítem usando un LLM.
    """

    async def execute(self, items: List[Item]) -> List[Item]:
        if not items:
            return items

        representative_item = items[0]
        llm_input = self._prepare_llm_input(representative_item)
        schema = self._get_expected_schema()

        try:
            result_str, llm_errors, _ = await call_llm_and_parse_json_result(
                prompt_name=self.prompt_name,
                user_input_content=llm_input,
                stage_name=self.stage_name,
                item=representative_item,
                ctx=self.ctx,
                expected_schema=schema,
                **self.params
            )

            if llm_errors:
                error_summary = f"Fallo en la utilidad LLM durante la generación: {llm_errors[0].message}"
                self._set_status_for_all(items, ItemStatus.FATAL, error_summary)
            elif result_str:
                await self._process_llm_result(items, result_str)
            else:
                summary = "El LLM no devolvió un resultado válido para la generación."
                self._set_status_for_all(items, ItemStatus.FATAL, summary)

        except Exception as e:
            self.logger.error(f"Error inesperado en la etapa de generación: {e}", exc_info=True)
            self._set_status_for_all(items, ItemStatus.FATAL, str(e))

        return items

    def _get_expected_schema(self) -> Optional[Type[BaseModel]]:
        return None

    def _prepare_llm_input(self, item: Item) -> str:
        """
        Prepara el input JSON para el LLM.
        Ya no se inyecta item_id, el LLM no lo necesita.
        """
        if not item.generation_params:
            raise ValueError(f"Ítem {item.temp_id} no tiene parámetros de generación.")

        llm_input_params = item.generation_params.copy()

        # El item_id ya no se inyecta aquí. La base de datos lo generará.
        # La instrucción en el prompt 01_agent_dominio.md también se ha eliminado.

        return json.dumps(llm_input_params, indent=2, ensure_ascii=False)

    async def _process_llm_result(self, items: List[Item], result_str: str):
        """
        Procesa el resultado del LLM, validando el payload y asignándolo al ítem.
        """
        try:
            generated_payloads = json.loads(result_str)
            if not isinstance(generated_payloads, list):
                error_summary = f"La respuesta del LLM no es una lista de ítems. Respuesta inesperada: {result_str[:500]}..."
                self._set_status_for_all(items, ItemStatus.FATAL, error_summary)
                return
        except (json.JSONDecodeError, TypeError) as e:
            error_summary = f"Respuesta del LLM no es JSON válido: {e}. Respuesta recibida: {result_str[:500]}..."
            self._set_status_for_all(items, ItemStatus.FATAL, error_summary)
            return

        if len(generated_payloads) != len(items):
            msg = f"El LLM generó {len(generated_payloads)} ítems, pero se esperaban {len(items)}. Respuesta: {result_str[:500]}..."
            self._set_status_for_all(items, ItemStatus.FATAL, msg)
            return

        for i, payload_dict in enumerate(generated_payloads):
            target_item = items[i]
            try:
                # El item_id ya no se sobrescribe aquí.
                # ItemPayloadSchema ahora permite item_id=None, y la DB lo generará.
                validated_payload = ItemPayloadSchema.model_validate(payload_dict)
                target_item.payload = validated_payload
                self._set_status(target_item, ItemStatus.SUCCESS, "Ítem generado y validado exitosamente.")
            except ValidationError as e:
                payload_preview = json.dumps(payload_dict, indent=2, ensure_ascii=False)[:500]
                error_summary = f"Error de validación Pydantic en el ítem generado (índice {i}): {e.errors()}. Payload problemático: {payload_preview}..."
                self.logger.error(f"ValidationError capturado para el ítem {target_item.temp_id}: {error_summary}", exc_info=True)
                self._set_status(target_item, ItemStatus.FATAL, error_summary)
            except Exception as e:
                payload_preview = json.dumps(payload_dict, indent=2, ensure_ascii=False)[:500]
                error_summary = f"Error inesperado procesando el ítem generado (índice {i}): {e}. Payload problemático: {payload_preview}..."
                self.logger.error(f"Excepción inesperada capturada para el ítem {target_item.temp_id}: {error_summary}", exc_info=True)
                self._set_status(target_item, ItemStatus.FATAL, error_summary)

    def _set_status(self, item: Item, status: ItemStatus, summary: str):
        update_item_status_and_audit(item, self.stage_name, status, summary)

    def _set_status_for_all(self, items: List[Item], status: ItemStatus, summary: str):
        for item_in_batch in items:
            self._set_status(item_in_batch, status, summary)
