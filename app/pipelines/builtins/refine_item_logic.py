# app/pipelines/builtins/refine_item_logic.py

from __future__ import annotations
import json
from typing import Optional, Set

from pydantic import BaseModel

from ..registry import register
from app.schemas.models import Item, ItemStatus
from app.schemas.item_schemas import RefinementResultSchema
from app.pipelines.abstractions import LLMStage
from app.pipelines.utils.stage_helpers import (
    add_revision_log_entry,
    handle_item_id_mismatch,
)

@register("refine_item_logic")
class RefineItemLogicStage(LLMStage):
    """
    Etapa de refinamiento que corrige un ítem basándose en hallazgos de
    coherencia argumental detectados por el validador experto.
    """
    prompt_file = "03_agente_refinador_razonamiento.md"
    pydantic_schema = RefinementResultSchema

    # 1. (CAMBIO) Se define un conjunto con los códigos de error específicos
    #    que este agente está capacitado para corregir.
    LOGIC_ERROR_CODES: Set[str] = {
        "E092_JUSTIFICA_INCONGRUENTE",
        "E076_DISTRACTOR_RATIONALE_MISMATCH",
        "E073_CONTRADICCION_INTERNA"
    }


    def _prepare_llm_input(self, item: Item) -> str:
        """
        Prepara el string de input para el LLM, filtrando solo los hallazgos
        de coherencia argumental.
        """
        if not item.payload:
            return json.dumps({"error": "Item payload is missing."})

        # 2. (CAMBIO) Se actualiza el filtro para usar el conjunto de códigos definido.
        #    Ahora solo seleccionará los errores lógicos relevantes.
        relevant_findings = [
            f for f in item.findings if f.codigo_error in self.LOGIC_ERROR_CODES
        ]

        if not relevant_findings:
             # 3. (CAMBIO) Se actualiza el mensaje de error para mayor claridad.
             raise ValueError(
                 "La etapa de refinamiento lógico se ejecutó, pero no se encontraron hallazgos de "
                 f"coherencia argumental pertinentes {list(self.LOGIC_ERROR_CODES)} en el ítem."
            )

        input_payload = {
            "temp_id": str(item.temp_id),
            "item_original": item.payload.model_dump(mode="json"),
            "hallazgos_a_corregir": [p.model_dump(mode="json") for p in relevant_findings]
        }
        return json.dumps(input_payload, ensure_ascii=False)


    async def _process_llm_result(self, item: Item, result: Optional[BaseModel]):
        """
        Procesa el resultado, reemplazando el payload del ítem con la
        versión corregida y actualizando el estado. La lógica aquí es robusta
        y no requiere cambios.
        """
        if not result or not isinstance(result, RefinementResultSchema):
            comment = f"No se recibió una estructura de refinamiento válida del LLM. Se recibió: {type(result).__name__}."
            add_revision_log_entry(item, self.stage_name, ItemStatus.FATAL, comment)
            return

        if handle_item_id_mismatch(item, self.stage_name, str(item.temp_id), str(result.temp_id)):
            return

        item.payload = result.item_refinado

        # Se persiste el historial detallado de cambios en el nuevo log.
        if result.correcciones_realizadas:
            item.change_log.extend(result.correcciones_realizadas)

        # Se limpian los hallazgos que ya fueron corregidos.
        fixed_codes = {correction.codigo_error for correction in result.correcciones_realizadas}
        item.findings = [f for f in item.findings if f.codigo_error not in fixed_codes]

        # Se actualiza el comentario para ser más informativo.
        num_corrections = len(result.correcciones_realizadas)
        comment = f"Refinamiento lógico aplicado. {num_corrections} correcciones documentadas en el change_log."
        add_revision_log_entry(item, self.stage_name, ItemStatus.LOGIC_REFINEMENT_SUCCESS, comment)
