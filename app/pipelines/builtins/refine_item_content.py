# app/pipelines/builtins/refine_item_content.py

from __future__ import annotations
import json
from typing import Optional

from pydantic import BaseModel

from ..registry import register
from app.schemas.models import Item, ItemStatus
from app.schemas.item_schemas import RefinementResultSchema
from app.pipelines.abstractions import LLMStage
from app.pipelines.utils.stage_helpers import (
    add_revision_log_entry,
    handle_item_id_mismatch,
)

@register("refine_item_content")
class RefineItemContentStage(LLMStage):
    """
    Etapa de refinamiento que corrige un ítem basándose en hallazgos
    de validez de contenido (ej. errores E2xx).
    """
    prompt_file = "03B_agente_refinador_contenido.md"
    pydantic_schema = RefinementResultSchema

    def _prepare_llm_input(self, item: Item) -> str:
        """
        Prepara el string de input para el LLM.
        Incluye el ítem original y los hallazgos de contenido a corregir.
        """
        if not item.payload:
            return json.dumps({"error": "Item payload is missing."})

        # --- REFACTORIZACIÓN ---
        # Se accede directamente a item.findings, que ahora es un campo oficial.
        relevant_findings = [f for f in item.findings if f.codigo_error.startswith('E2')]

        if not relevant_findings:
             raise ValueError("Refine stage was run, but no relevant content findings (E2xx) were found on the Item.")

        input_payload = {
            "temp_id": str(item.temp_id),
            "item_original": item.payload.model_dump(mode="json"),
            "hallazgos_a_corregir": [p.model_dump(mode="json") for p in relevant_findings]
        }
        return json.dumps(input_payload, ensure_ascii=False)

    async def _process_llm_result(self, item: Item, result: Optional[BaseModel]):
        """
        Procesa el resultado, reemplazando el payload del ítem con la
        versión corregida y actualizando el estado.
        """
        if not result or not isinstance(result, RefinementResultSchema):
            comment = f"No se recibió una estructura de refinamiento válida del LLM. Se recibió: {type(result).__name__}."
            add_revision_log_entry(item, self.stage_name, ItemStatus.FATAL, comment)
            return

        if handle_item_id_mismatch(item, self.stage_name, str(item.temp_id), str(result.temp_id)):
            return

        item.payload = result.item_refinado

        # 1. Se persiste el historial detallado de cambios en el nuevo log.
        if result.correcciones_realizadas:
            item.change_log.extend(result.correcciones_realizadas)

        # 2. Se limpian los hallazgos que ya fueron corregidos.
        fixed_codes = {correction.codigo_error for correction in result.correcciones_realizadas}
        item.findings = [f for f in item.findings if f.codigo_error not in fixed_codes]

        # 3. Se actualiza el comentario para ser más informativo.
        num_corrections = len(result.correcciones_realizadas)
        comment = f"Refinamiento de contenido aplicado. {num_corrections} correcciones registradas en el change_log."
        add_revision_log_entry(item, self.stage_name, ItemStatus.CONTENT_REFINEMENT_SUCCESS, comment)
