# app/pipelines/abstractions.py

from __future__ import annotations
from abc import ABC, abstractmethod
import logging
import asyncio
from typing import List, Dict, Any, Type, Optional
from pydantic import BaseModel

from app.schemas.models import Item, ItemStatus
from app.pipelines.utils.stage_helpers import add_revision_log_entry, handle_missing_payload
from app.pipelines.utils.llm_utils import call_llm_and_parse_json_result

class BaseStage(ABC):
    """Clase base abstracta para todas las etapas del pipeline."""

    def __init__(self, stage_name: str, params: Dict[str, Any], ctx: Dict[str, Any]):
        self.stage_name = stage_name
        self.params = params
        self.ctx = ctx
        self.logger = logging.getLogger(f"app.pipelines.{self.stage_name}")

    @abstractmethod
    async def execute(self, items: List[Item]) -> List[Item]:
        """
        El método principal que procesa una lista de ítems.
        Debe ser implementado por cada clase de etapa.
        """
        pass

class LLMStage(BaseStage):
    """
    Clase base abstracta para etapas que interactúan con un LLM.
    Encapsula la lógica común de preparación, llamada y procesamiento del LLM.
    """
    prompt_file: str = ""
    pydantic_schema: Optional[Type[BaseModel]] = None

    async def execute(self, items: List[Item]) -> List[Item]:
        """
        Ejecución genérica para etapas LLM que procesan ítems uno por uno.
        """
        tasks = [self._process_single_item(item) for item in items]
        await asyncio.gather(*tasks)
        return items

    async def _process_single_item(self, item: Item):
        """Procesa un único ítem a través del flujo LLM."""
        if item.status == ItemStatus.FATAL:
            return

        # La etapa 'generate_items' es la única que puede ejecutarse sin payload.
        if self.stage_name != 'generate_items':
            if handle_missing_payload(item, self.stage_name):
                return

        try:
            llm_input = self._prepare_llm_input(item)
        except Exception as e:
            comment = f"Error al preparar el input para el LLM: {e}"
            add_revision_log_entry(item, self.stage_name, ItemStatus.FATAL, comment)
            return

        result_obj, llm_errors, _ = await call_llm_and_parse_json_result(
            prompt_name=self.prompt_file,
            user_input_content=llm_input,
            stage_name=self.stage_name,
            item=item,
            ctx=self.ctx,
            expected_schema=self.pydantic_schema,
            **self.params,
        )

        if llm_errors:
            error_summary = f"Fallo en la utilidad LLM: {llm_errors[0].descripcion_hallazgo}"
            add_revision_log_entry(item, self.stage_name, ItemStatus.FATAL, error_summary)
        elif result_obj:
            await self._process_llm_result(item, result_obj)
        else:
            summary = "El LLM no devolvió un resultado válido ni errores específicos."
            add_revision_log_entry(item, self.stage_name, ItemStatus.FATAL, summary)

    @abstractmethod
    def _prepare_llm_input(self, item: Item) -> str:
        """Prepara el input para el LLM. Debe ser implementado por la subclase."""
        pass

    @abstractmethod
    async def _process_llm_result(self, item: Item, result: Optional[BaseModel]):
        """Procesa el resultado parseado del LLM. Debe ser implementado por la subclase."""
        pass
