# Archivo actualizado: app/pipelines/builtins/generate_items.py

from __future__ import annotations
import logging
from typing import List, Dict, Any, Type
from pydantic import BaseModel, TypeAdapter

from ..registry import register
from app.schemas.models import Item
from app.schemas.item_schemas import ItemPayloadSchema, UserGenerateParams
from app.pipelines.abstractions import BaseStage
from ..utils.llm_utils import call_llm_and_parse_json_result

logger = logging.getLogger(__name__)

@register("generate_items")
class GenerateItemsStage(BaseStage):
    """
    Etapa inicial del pipeline que genera un lote de nuevos ítems desde cero
    en una única llamada al LLM.
    """

    async def execute(self, items: List[Item]) -> List[Item]:
        """
        Punto de entrada. Orquesta la generación por lotes.
        Ignora la lista de 'items' de entrada.
        """
        user_params_dict = self.ctx.get("user_params", {})
        user_params = UserGenerateParams(**user_params_dict)
        n_items = user_params.n_items
        self.logger.info(f"Starting batch generation of {n_items} items.")

        # 1. Pre-crear ítems con IDs temporales
        temp_items = [Item() for _ in range(n_items)]
        ids_to_use = [str(item.temp_id) for item in temp_items]

        # 2. Preparar el input para el LLM, incluyendo los IDs a usar
        llm_input_data = user_params.model_dump()
        llm_input_data["item_ids_a_usar"] = ids_to_use
        llm_input_content = json.dumps(llm_input_data)

        # 3. Hacer una única llamada al LLM esperando una lista de payloads
        # Usamos un ítem representativo solo para el tracking de tokens de esta llamada
        representative_item = temp_items[0]

        # Esperamos una lista de payloads, usamos TypeAdapter para validar
        PayloadListAdapter = TypeAdapter(List[ItemPayloadSchema])

        payloads_list, llm_errors, _ = await call_llm_and_parse_json_result(
            prompt_name=self.params.get("prompt"),
            user_input_content=llm_input_content,
            stage_name=self.stage_name,
            item=representative_item,
            ctx=self.ctx,
            expected_schema=PayloadListAdapter,
            **self.params
        )

        if llm_errors or not payloads_list:
            error_msg = llm_errors[0].message if llm_errors else "LLM did not return a valid list of payloads."
            self.logger.error(f"Batch generation failed: {error_msg}")
            # Marcamos todos los ítems temporales como fallidos
            for item in temp_items:
                self._set_status(item, "fail.llm_error", error_msg)
            return temp_items

        # 4. Mapear los payloads recibidos a los ítems temporales
        payloads_map = {str(p.item_id): p for p in payloads_list}

        final_items = []
        for item in temp_items:
            if str(item.temp_id) in payloads_map:
                item.payload = payloads_map[str(item.temp_id)]
                summary = f"Item {item.temp_id} generated successfully in batch."
                self._set_status(item, "success", summary)
                final_items.append(item)
            else:
                summary = f"LLM did not return a payload for requested id {item.temp_id} in batch."
                self._set_status(item, "fail.missing_payload", summary)
                final_items.append(item) # Añadimos el ítem fallido para trazabilidad

        self.logger.info(f"Successfully processed batch. Generated {len(payloads_map)} payloads.")
        return final_items
