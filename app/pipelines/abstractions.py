# app/pipelines/abstractions.py

import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Type, Optional
from pydantic import BaseModel
import asyncio

from app.schemas.models import Item, ItemStatus
from app.schemas.item_schemas import CorrectionSchema, ReportEntrySchema # Ensure ReportEntrySchema is imported
from app.pipelines.utils.stage_helpers import (
    update_item_status_and_audit,
    handle_missing_payload,
    skip_if_terminal_error
)
from app.pipelines.utils.llm_utils import call_llm_and_parse_json_result
from app.prompts import load_prompt

logger = logging.getLogger(__name__)

class BaseStage(ABC):
    def __init__(self, stage_name: str, ctx: Dict[str, Any], params: Dict[str, Any]):
        self.stage_name = stage_name
        self.ctx = ctx
        self.params = params
        self.logger = logging.getLogger(f"app.pipelines.{self.stage_name}")

    def _set_status(self, item: Item, status: ItemStatus, summary: str = "", correcciones: Optional[List[CorrectionSchema]] = None): # FIX: parameter name
        # The 'status' argument is an ItemStatus Enum member.
        # update_item_status_and_audit expects ItemStatus Enum for its 'status' parameter.
        # FIX: Pass correcciones (Spanish) to update_item_status_and_audit
        update_item_status_and_audit(item, self.stage_name, status, summary, correcciones=correcciones or [])

    @abstractmethod
    async def execute(self, items: List[Item]) -> List[Item]:
        raise NotImplementedError

class LLMStage(BaseStage):
    def __init__(self, stage_name: str, ctx: Dict[str, Any], params: Dict[str, Any]):
        super().__init__(stage_name, ctx, params)
        self.prompt_name = self.params.get("prompt")
        if not self.prompt_name:
            raise ValueError(f"La etapa '{self.stage_name}' requiere un 'prompt' en sus parámetros.")
        load_prompt(self.prompt_name)

    async def execute(self, items: List[Item]) -> List[Item]:
        listen_status = self.params.get("listen_to_status_pattern")
        items_to_process = []

        # Correctly filter items based on item.status (string value)
        non_processing_statuses = [
            ItemStatus.FATAL.value,
            ItemStatus.FAIL.value,
            ItemStatus.SKIPPED.value,
            ItemStatus.SKIPPED_DUE_TO_FATAL_PRIOR.value
        ]

        if listen_status:
            items_to_process = [
                item for item in items
                if item.status.endswith(listen_status) and
                   item.status not in non_processing_statuses
            ]
        else:
            items_to_process = [
                item for item in items
                if item.status not in non_processing_statuses
            ]

        if items_to_process:
            tasks = [self._process_one_item(item) for item in items_to_process]
            await asyncio.gather(*tasks)
        return items

    async def _process_one_item(self, item: Item):
        llm_errors: Optional[List[ReportEntrySchema]] = None

        if skip_if_terminal_error(item, self.stage_name):
            return

        if not item.payload and self.stage_name != 'generate_items':
            handle_missing_payload(item, self.stage_name)
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
                **self.params
            )

            if llm_errors:
                error_summary = f"LLM utility failed: {llm_errors[0].message}"
                if any(err.severity == "fatal" for err in llm_errors):
                    llm_outcome_enum = ItemStatus.FATAL
                else:
                    llm_outcome_enum = ItemStatus.FAIL
                self._set_status(item, llm_outcome_enum, error_summary)
            elif result:
                await self._process_llm_result(item, result)
            else:
                summary = "LLM no devolvió un resultado válido o el parseo falló."
                self._set_status(item, ItemStatus.FATAL, summary)
        except Exception as e:
            self.logger.error(f"Error inesperado en la etapa {self.stage_name} para el ítem {item.temp_id}: {e}", exc_info=True)
            self._set_status(item, ItemStatus.FATAL, str(e))

    @abstractmethod
    def _get_expected_schema(self) -> Type[BaseModel]:
        raise NotImplementedError

    @abstractmethod
    def _prepare_llm_input(self, item: Item) -> str:
        raise NotImplementedError

    @abstractmethod
    async def _process_llm_result(self, item: Item, result: Optional[BaseModel]):
        raise NotImplementedError
