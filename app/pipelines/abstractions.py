# Archivo nuevo: app/pipelines/abstractions.py

import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Type
from pydantic import BaseModel
import asyncio

from app.schemas.models import Item
from app.pipelines.utils.stage_helpers import (
    update_item_status_and_audit,
    skip_if_terminal_error,
    handle_missing_payload
)
# La utilidad clave que usará nuestra abstracción
from app.pipelines.utils.llm_utils import call_llm_and_parse_json_result
from app.prompts import load_prompt

logger = logging.getLogger(__name__)

class BaseStage(ABC):
    """Clase base abstracta para cualquier etapa del pipeline."""
    def __init__(self, stage_name: str, ctx: Dict[str, Any], params: Dict[str, Any]):
        self.stage_name = stage_name
        self.ctx = ctx
        self.params = params
        self.logger = logging.getLogger(f"app.pipelines.{self.stage_name}")

    @abstractmethod
    async def execute(self, items: List[Item]) -> List[Item]:
        """El punto de entrada que el runner llamará para ejecutar la etapa."""
        raise NotImplementedError

    def _set_status(self, item: Item, outcome: str, summary: str = ""):
        """
        Helper para estandarizar la actualización de estado y la auditoría.
        Genera un estado como 'validate_logic.success' o 'refine_policy.fail'.
        """
        new_status = f"{self.stage_name}.{outcome}"
        final_summary = summary or f"Stage completed with outcome '{outcome}'."
        update_item_status_and_audit(item, self.stage_name, new_status, final_summary)


class LLMStage(BaseStage):
    """
    Clase base para etapas que utilizan un LLM.
    Maneja el boilerplate de carga de prompt, concurrencia y llamada a la API.
    """
    def __init__(self, stage_name: str, ctx: Dict[str, Any], params: Dict[str, Any]):
        super().__init__(stage_name, ctx, params)
        self.prompt_name = self.params.get("prompt")
        if not self.prompt_name:
            raise ValueError(f"Stage '{self.stage_name}' requires a 'prompt' in its params.")
        load_prompt(self.prompt_name) # Valida la existencia del prompt en la inicialización

    async def execute(self, items: List[Item]) -> List[Item]:
        """
        Punto de entrada principal. Filtra ítems y ejecuta el procesamiento.
        NUEVO: Ahora maneja 'listen_to_status' para etapas de refinamiento.
        """
        listen_status = self.params.get("listen_to_status")

        if listen_status:
            # Etapa de refinamiento: solo procesa ítems con el estado específico.
            items_to_process = [item for item in items if item.status == listen_status]
            self.logger.info(f"Found {len(items_to_process)} items with status '{listen_status}' to process.")
        else:
            # Etapa de validación/corrección: procesa todos los que no hayan fallado.
            items_to_process = [item for item in items if not item.status.endswith(('.fail', '.error'))]

        tasks = [self._process_one_item(item) for item in items_to_process]
        if tasks:
            await asyncio.gather(*tasks)
        return items

    async def _process_one_item(self, item: Item):
        """Orquesta la lógica de procesamiento para un único ítem."""
        if skip_if_terminal_error(item, self.stage_name):
            return

        if not item.payload:
            handle_missing_payload(
                item, self.stage_name, "NO_PAYLOAD", "Item has no payload for processing.",
                f"{self.stage_name}.fail.no_payload", "Skipped: No payload to process."
            )
            return

        try:
            llm_input = self._prepare_llm_input(item)
            schema = self._get_expected_schema()

            result, llm_errors, _ = await call_llm_and_parse_json_result(
                prompt_name=self.prompt_name,
                user_input_content=llm_input,
                stage_name=self.stage_name,
                item=item,
                ctx=self.ctx,
                expected_schema=schema,
            )

            if llm_errors:
                item.errors.extend(llm_errors)
                self._set_status(item, "fail.utility_error", f"LLM util failed: {llm_errors[0].message}")
            elif result:
                await self._process_llm_result(item, result)
            else:
                self._set_status(item, "fail.no_result", "LLM did not return a valid result.")

        except Exception as e:
            self.logger.error(f"Unexpected error in stage {self.stage_name} for item {item.temp_id}: {e}", exc_info=True)
            self._set_status(item, "fail.unexpected_error", str(e))

    # --- MÉTODOS ABSTRACTOS QUE LAS CLASES HIJAS DEBEN IMPLEMENTAR ---

    @abstractmethod
    def _get_expected_schema(self) -> Type[BaseModel]:
        """Devuelve el esquema Pydantic para la respuesta del LLM."""
        raise NotImplementedError

    @abstractmethod
    def _prepare_llm_input(self, item: Item) -> str:
        """Prepara el string de input para el LLM."""
        raise NotImplementedError

    @abstractmethod
    async def _process_llm_result(self, item: Item, result: BaseModel):
        """Define la lógica de negocio para procesar un resultado exitoso del LLM."""
        raise NotImplementedError
