# Archivo actualizado: app/pipelines/builtins/generate_items.py

from __future__ import annotations
import logging
import asyncio
from typing import List, Dict, Any, Optional

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
    basándose en los parámetros proporcionados por el usuario.
    """

    async def _process_one_generation(self, item_index: int) -> Optional[Item]:
        """
        Lógica para generar un único ítem. Es llamada de forma concurrente.
        """
        # Los parámetros de la etapa y del usuario están en self.params y self.ctx
        user_params = self.ctx.get("user_params", {})
        prompt_name = self.params.get("prompt") # El prompt se define en pipeline.yml

        # El input para el LLM son los parámetros del usuario en formato JSON
        llm_input = UserGenerateParams(**user_params).model_dump_json(indent=2)

        payload_result, llm_errors, _ = await call_llm_and_parse_json_result(
            prompt_name=prompt_name,
            user_input_content=llm_input,
            stage_name=self.stage_name,
            item=Item(), # Pasamos un ítem temporal para la auditoría de tokens
            ctx=self.ctx,
            expected_schema=ItemPayloadSchema,
            **self.params
        )

        if llm_errors or not payload_result:
            error_msg = llm_errors[0].message if llm_errors else "LLM did not return a valid payload."
            self.logger.error(f"Failed to generate item #{item_index}: {error_msg}")
            # En una política de fallo temprano, simplemente no devolvemos el ítem.
            return None

        # Si la generación es exitosa, creamos el objeto Item
        new_item = Item(payload=payload_result)
        summary = f"Item generated successfully with temp_id {new_item.temp_id}."
        self.logger.info(summary)
        self._set_status(new_item, "success", summary)

        return new_item

    async def execute(self, items: List[Item]) -> List[Item]:
        """
        Punto de entrada. Orquesta la generación de `n_items` en paralelo.
        Ignora la lista de 'items' de entrada.
        """
        user_params = self.ctx.get("user_params", {})
        n_items = user_params.get("n_items", 1)
        self.logger.info(f"Starting generation of {n_items} items.")

        tasks = [self._process_one_generation(i) for i in range(n_items)]
        generation_results = await asyncio.gather(*tasks)

        # Filtramos los resultados nulos (fallos de generación) y devolvemos la nueva lista
        new_items = [item for item in generation_results if item is not None]

        self.logger.info(f"Successfully generated {len(new_items)} out of {n_items} requested items.")
        return new_items
