# app/pipelines/builtins/generate_items.py

from __future__ import annotations
import logging
import json
from typing import List
from uuid import UUID, uuid4

from ..registry import register
from app.prompts import load_prompt
from app.schemas.models import Item
from app.schemas.item_schemas import ItemPayloadSchema, UserGenerateParams, ReportEntrySchema, MetadataSchema
from app.pipelines.abstractions import BaseStage

from ..utils.llm_utils import call_llm_and_parse_json_result
from ..utils.stage_helpers import (
    handle_prompt_not_found_error,
    handle_item_id_mismatch_refinement,
)


logger = logging.getLogger(__name__)

@register("generate_items")
class GenerateItemsStage(BaseStage):
    """
    Etapa inicial del pipeline que genera un lote de nuevos ítems desde cero
    en una única y eficiente llamada al LLM.
    """

    async def execute(self, items: List[Item]) -> List[Item]:
        """
        Punto de entrada. Orquesta la generación por lotes y rellena los ítems de entrada.
        """
        user_params_dict = self.ctx.get("user_params", {})
        user_params = UserGenerateParams(**user_params_dict)
        n_items = user_params.n_items

        try:
            _ = load_prompt(self.params.get("prompt", "01_agent_dominio.md"))
        except FileNotFoundError as e:
            return handle_prompt_not_found_error(items, self.stage_name, self.params.get("prompt", "01_agent_dominio.md"), e)


        self.logger.info(f"Starting batch generation of {n_items} items.")

        if len(items) != n_items:
            summary = f"Desalineación crítica: Esperaba {n_items} ítems pre-inicializados, pero recibí {len(items)}. Abortando generación."
            self.logger.critical(summary)
            for item in items:
                self._set_status(item, "fatal_error", summary)
                item.findings.append(ReportEntrySchema(code="GEN_INIT_MISMATCH", message=summary, severity="error"))
            if not items:
                dummy_item = Item(payload=ItemPayloadSchema(item_id=uuid4(), metadata=MetadataSchema(idioma_item="es", area="General", asignatura="General", tema="Conceptos Generales", nivel_destinatario="Todos", nivel_cognitivo="recordar", dificultad_prevista="facil")))
                self._set_status(dummy_item, "fatal_error", summary)
                return [dummy_item]
            return items


        llm_input_payload = user_params.model_dump()
        llm_input_payload["n_items"] = n_items

        item_ids_for_llm = [str(item.temp_id) for item in items]

        if len(item_ids_for_llm) < n_items:
            for _ in range(n_items - len(item_ids_for_llm)):
                item_ids_for_llm.append(str(uuid4()))
        llm_input_payload["item_ids_a_usar"] = item_ids_for_llm

        user_input_content_json = json.dumps(llm_input_payload, ensure_ascii=False, indent=2)

        self.logger.info(f"Calling LLM for batch generation of {n_items} items.")

        payloads_list_raw, llm_errors, _ = await call_llm_and_parse_json_result(
            prompt_name=self.params.get("prompt", "01_agent_dominio.md"),
            user_input_content=user_input_content_json,
            stage_name=self.stage_name,
            item=items[0],
            ctx=self.ctx,
            expected_schema=List[ItemPayloadSchema],
            model=self.params.get("model"),
            temperature=self.params.get("temperature"),
            max_tokens=self.params.get("max_tokens"),
            # provider=self.params.get("provider"), # ¡REMOVIDO! Ya se gestiona a través de ctx.
            top_k=self.params.get("top_k"),
            top_p=self.params.get("top_p"),
            stop_sequences=self.params.get("stop_sequences"),
            seed=self.params.get("seed")
        )

        if llm_errors:
            for item in items:
                self._set_status(item, "fail.llm_error", f"LLM call or parse failed: {llm_errors[0].message}")
                item.findings.extend(llm_errors)
            return items

        if not isinstance(payloads_list_raw, list):
            summary = "LLM did not return a list of items as expected."
            for item in items:
                self._set_status(item, "fail.format_error", summary)
                item.findings.append(ReportEntrySchema(code="LLM_RESPONSE_FORMAT_INVALID", message=summary, severity="error"))
            return items

        if len(payloads_list_raw) != n_items:
            summary = f"LLM generated {len(payloads_list_raw)} items, but {n_items} were requested."
            for item in items:
                self._set_status(item, "fail.count_mismatch", summary)
                item.findings.append(ReportEntrySchema(code="LLM_ITEM_COUNT_MISMATCH", message=summary, severity="error"))
            return items

        payloads_map = {str(p.item_id): p for p in payloads_list_raw}

        successful_generation_count = 0
        for item in items:
            payload = payloads_map.get(str(item.temp_id))
            if payload:
                item.payload = payload
                item.prompt_v = self.params.get("prompt")
                item.findings = [
                    f for f in item.findings
                    if not (
                        f.code.startswith("LLM_CALL_FAILED") or
                        f.code.startswith("LLM_PARSE_VALIDATION_ERROR") or
                        f.code.startswith("UNEXPECTED_LLM_PROCESSING_ERROR") or
                        f.code.startswith("NO_LLM_")
                    )
                ]
                successful_generation_count += 1
                self._set_status(item, "success", "Item generated successfully.")
            else:
                summary = f"LLM did not return a payload for expected item_id {item.temp_id}. Mismatch in batch generation."
                handle_item_id_mismatch_refinement(
                    item, self.stage_name, item.temp_id, UUID("00000000-0000-0000-0000-000000000000"),
                    f"{self.stage_name}.fail.id_mismatch",
                    summary
                )

        if successful_generation_count == n_items:
            self.logger.info(f"Batch generation completed successfully for all {n_items} items.")
        else:
            self.logger.warning(f"Batch generation completed with {successful_generation_count}/{n_items} items successfully generated. Some items failed to map.")

        return items
