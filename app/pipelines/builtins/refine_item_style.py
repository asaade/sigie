# app/pipelines/builtins/refine_item_style.py

from __future__ import annotations
import logging
from typing import List, Dict, Any

from ..registry import register
from app.prompts import load_prompt
from app.schemas.models import Item
from app.schemas.item_schemas import ReportEntrySchema, RefinementResultSchema

from ..utils.llm_utils import call_llm_and_parse_json_result
from ..utils.stage_helpers import ( # Importar las nuevas funciones helper
    skip_if_terminal_error,
    handle_prompt_not_found_error,
    handle_missing_payload,
    clean_item_llm_errors,
    clean_specific_errors,
    update_item_status_and_audit,
    handle_llm_call_and_parse_errors
)

logger = logging.getLogger(__name__)

@register("refine_item_style")
async def refine_item_style_stage(items: List[Item], ctx: Dict[str, Any]) -> List[Item]:
    """
    Etapa de refinamiento de estilo de ítems mediante un LLM (Agente Refinador de Estilo).
    Refactorizado para usar llm_utils y stage_helpers.
    """
    stage_name = "refine_item_style"

    params = ctx.get("params", {}).get(stage_name, {})
    prompt_name = params.get("prompt", "04_agente_refinador_estilo.md")

    try:
        _ = load_prompt(prompt_name)
    except FileNotFoundError as e:
        return handle_prompt_not_found_error(items, stage_name, prompt_name, e)

    for item in items:
        if skip_if_terminal_error(item, stage_name):
            continue

        if not item.payload:
            handle_missing_payload(
                item,
                stage_name,
                "NO_PAYLOAD_FOR_REFINEMENT",
                "El ítem no tiene un payload para refinar el estilo.",
                "refinement_skipped_no_payload",
                "Saltado: no hay payload de ítem para refinar el estilo."
            )
            continue

        logger.info(f"Refining style for item {item.temp_id} using prompt '{prompt_name}'.")

        llm_input_content = item.payload.model_dump_json(indent=2)

        refinement_result_raw, llm_errors, _ = await call_llm_and_parse_json_result(
            prompt_name=prompt_name,
            user_input_content=llm_input_content,
            stage_name=stage_name,
            item=item,
            ctx=ctx,
            expected_schema=RefinementResultSchema
        )

        if await handle_llm_call_and_parse_errors(
            item=item,
            stage_name=stage_name,
            llm_errors_from_call_parse=llm_errors,
            llm_fail_status="refinement_failed",
            summary_prefix="Fallo en llamada/parseo del LLM para refinamiento de estilo"
        ):
            continue

        if not refinement_result_raw:
             update_item_status_and_audit(
                 item=item,
                 stage_name=stage_name,
                 new_status="refinement_failed_no_result",
                 summary_msg="Error interno: La utilidad LLM no devolvió resultado de refinamiento."
             )
             item.errors.append(
                 ReportEntrySchema(
                     code="NO_REFINEMENT_RESULT",
                     message="La utilidad de LLM no devolvió un resultado de refinamiento válido.",
                     severity="error"
                 )
             )
             logger.error(f"Internal error: LLM utility returned no result for item {item.temp_id} in {stage_name}.")
             continue

        if refinement_result_raw.item_id != item.temp_id:
            error_msg = f"Mismatched item_id in LLM style refinement response. Expected {item.temp_id}, got {refinement_result_raw.item_id}."
            item.errors.append(
                ReportEntrySchema(
                    code="ITEM_ID_MISMATCH_REFINEMENT",
                    message=error_msg,
                    field="item_id",
                    severity="error"
                )
            )
            update_item_status_and_audit(
                item=item,
                stage_name=stage_name,
                new_status="refinement_failed_mismatch",
                summary_msg="Item ID mismatched en respuesta de refinamiento de estilo."
            )
            logger.error(error_msg)
            continue

        item.payload = refinement_result_raw.item_refinado

        # Limpiar warnings y errores que este refinador debería haber corregido
        fixed_codes = {c.error_code for c in refinement_result_raw.correcciones_realizadas if c.error_code}
        clean_specific_errors(item, fixed_codes)
        clean_item_llm_errors(item) # Limpiar también errores LLM que pueden haberse añadido

        update_item_status_and_audit(
            item=item,
            stage_name=stage_name,
            new_status="refining_style_applied", # Actualizado a un estado más específico
            summary_msg="Refinamiento de estilo aplicado.",
            correcciones=refinement_result_raw.correcciones_realizadas
        )
        logger.info(f"Item {item.temp_id} style refinement applied. Status: {item.status}")

    logger.info("Style refinement stage completed for all items.")
    return items
