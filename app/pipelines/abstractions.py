# app/pipelines/abstractions.py

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
from app.pipelines.utils.llm_utils import call_llm_and_parse_json_result
from app.prompts import load_prompt

logger = logging.getLogger(__name__)

MAX_AUDIT_SUMMARY_LENGTH = 900

class BaseStage(ABC):
    """Clase base abstracta para cualquier etapa del pipeline."""
    def __init__(self, stage_name: str, ctx: Dict[str, Any], params: Dict[str, Any]):
        self.stage_name = stage_name
        self.ctx = ctx
        self.params = params
        self.logger = logging.getLogger(f"app.pipelines.{self.stage_name}")

        # Asegurarse de que el nombre del proveedor LLM esté en el contexto desde el inicio
        if "provider" in self.params:
            self.ctx["llm_provider_name"] = self.params["provider"]

    @abstractmethod
    async def execute(self, items: List[Item]) -> List[Item]:
        """El punto de entrada que el runner llamará para ejecutar la etapa."""
        raise NotImplementedError

    def _set_status(self, item: Item, outcome: str, summary: str = ""): # ¡ESTE MÉTODO DEBE ESTAR PRESENTE!
        """
        Helper para estandarizar la actualización de estado y la auditoría.
        Genera un estado como 'validate_logic.success' o 'refine_policy.fail'.
        """
        new_status = f"{self.stage_name}.{outcome}"
        final_summary = summary or f"Stage completed with outcome '{outcome}'."
        final_summary = final_summary[:MAX_AUDIT_SUMMARY_LENGTH]

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
        # Valida la existencia del prompt en la inicialización para un fallo temprano
        load_prompt(self.prompt_name)

    async def execute(self, items: List[Item]) -> List[Item]:
        """
        Punto de entrada principal. Filtra ítems no procesables y ejecuta
        el procesamiento de los demás de forma concurrente.
        """
        listen_status = self.params.get("listen_to_status_pattern")

        items_to_process = []
        if listen_status:
            items_to_process = [item for item in items if item.status.endswith(listen_status)]
            if items_to_process:
                self.logger.info(f"Found {len(items_to_process)} items with status matching '{listen_status}' to process.")
        else:
            items_to_process = [item for item in items if item.status != "fatal_error" and not item.status.endswith((".fail", ".error"))]

        if items_to_process:
            tasks = [self._process_one_item(item) for item in items_to_process]
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

            # Extraer parámetros de configuración del LLM de self.params
            # y pasarlos explícitamente a call_llm_and_parse_json_result
            model_param = self.params.get("model")
            temperature_param = self.params.get("temperature")
            max_tokens_param = self.params.get("max_tokens")
            top_k_param = self.params.get("top_k")
            top_p_param = self.params.get("top_p")
            stop_sequences_param = self.params.get("stop_sequences")
            seed_param = self.params.get("seed")

            result, llm_errors, _ = await call_llm_and_parse_json_result(
                prompt_name=self.prompt_name,
                user_input_content=llm_input,
                stage_name=self.stage_name,
                item=item,
                ctx=self.ctx,
                expected_schema=schema,
                model=model_param,
                temperature=temperature_param,
                max_tokens=max_tokens_param,
                top_k=top_k_param,
                top_p=top_p_param,
                stop_sequences=stop_sequences_param,
                seed=seed_param
            )

            if llm_errors:
                item.findings.extend(llm_errors)
                error_summary = f"LLM utility failed: {llm_errors[0].message}"
                self.logger.warning(f"For item {item.temp_id}, {error_summary}")
                self._set_status(item, "fail.utility_error", error_summary)
            elif result:
                await self._process_llm_result(item, result)
                self._clean_llm_findings_on_success(item)
            else:
                summary = "LLM did not return a valid result. This strongly suggests the prompt's output format does not match the expected Pydantic schema."
                self.logger.error(f"CRITICAL FAILURE for item {item.temp_id} in stage {self.stage_name}: {summary}")
                self._set_status(item, "fail.no_result", summary)

        except Exception as e:
            self.logger.error(f"Unexpected error in stage {self.stage_name} for item {item.temp_id}: {e}", exc_info=True)
            self._set_status(item, "fail.unexpected_error", str(e))

    def _clean_llm_findings_on_success(self, item: Item) -> None:
        """
        Limpia los hallazgos del ítem que son generados por fallos de la utilidad LLM/parseo,
        una vez que el _process_llm_result de la etapa fue exitoso.
        """
        item.findings = [
            f for f in item.findings
            if not (
                f.code.startswith("LLM_CALL_FAILED") or
                f.code.startswith("LLM_PARSE_VALIDATION_ERROR") == "true" or # Note: Changed to == "true" for strict comparison
                f.code.startswith("UNEXPECTED_LLM_PROCESSING_ERROR") or
                f.code.startswith("NO_LLM_")
            )
        ]

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
