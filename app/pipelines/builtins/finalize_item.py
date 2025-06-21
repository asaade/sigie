# app/pipelines/builtins/finalize_item.py

from __future__ import annotations
import logging
from typing import List, Dict, Any

from ..registry import register
from app.prompts import load_prompt
from app.schemas.models import Item
from app.schemas.item_schemas import ReportEntrySchema, FinalizationResultSchema

from ..utils.llm_utils import call_llm_and_parse_json_result
from ..utils.stage_helpers import ( # Importar las nuevas funciones helper
    skip_if_terminal_error,
    add_audit_entry,
    handle_prompt_not_found_error,
    handle_missing_payload,
    clean_item_llm_errors,
    clean_specific_errors, # Usada para limpiar errores después de correcciones
    update_item_status_and_audit,
    handle_llm_call_and_parse_errors
)

logger = logging.getLogger(__name__)

@register("finalize_item")
async def finalize_item_stage(items: List[Item], ctx: Dict[str, Any]) -> List[Item]:
    """
    Etapa de finalización de ítems mediante un LLM (Agente Final).
    Refactorizado para usar llm_utils y stage_helpers.
    """
    stage_name = "finalize_item"

    params = ctx.get("params", {}).get(stage_name, {})
    prompt_name = params.get("prompt", "07_agent_final.md")

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
                "NO_PAYLOAD_FOR_FINALIZATION",
                "El ítem no tiene un payload para la etapa de finalización.",
                "finalization_skipped_no_payload",
                "Saltado: no hay payload de ítem para la finalización."
            )
            continue

        logger.info(f"Finalizing item {item.temp_id} using prompt '{prompt_name}'.")

        llm_input_content = item.payload.model_dump_json(indent=2)

        final_result_from_llm, llm_errors, _ = await call_llm_and_parse_json_result(
            prompt_name=prompt_name,
            user_input_content=llm_input_content,
            stage_name=stage_name,
            item=item,
            ctx=ctx,
            expected_schema=FinalizationResultSchema
        )

        if await handle_llm_call_and_parse_errors(
            item=item,
            stage_name=stage_name,
            llm_errors_from_call_parse=llm_errors,
            llm_fail_status="llm_finalization_failed",
            summary_prefix="Fallo en llamada/parseo del LLM para finalización"
        ):
            continue

        if not final_result_from_llm:
             update_item_status_and_audit(
                 item=item,
                 stage_name=stage_name,
                 new_status="finalization_failed_no_result",
                 summary_msg="Error interno: La utilidad LLM no devolvió un resultado de finalización válido."
             )
             item.errors.append(
                 ReportEntrySchema(
                     code="NO_FINALIZATION_RESULT",
                     message="La utilidad de LLM no devolvió un resultado de finalización válido.",
                     severity="error"
                 )
             )
             logger.error(f"Internal error: LLM utility returned no finalization result for item {item.temp_id} in {stage_name}.")
             continue

        if final_result_from_llm.item_id != item.temp_id:
            error_msg = f"Mismatched item_id in LLM finalization response. Expected {item.temp_id}, got {final_result_from_llm.item_id}."
            item.errors.append(
                ReportEntrySchema(
                    code="ITEM_ID_MISMATCH_FINALIZATION",
                    message=error_msg,
                    field="item_id",
                    severity="error"
                )
            )
            update_item_status_and_audit(
                item=item,
                stage_name=stage_name,
                new_status="finalization_failed_mismatch",
                summary_msg="Item ID mismatched en respuesta de finalización."
            )
            logger.error(error_msg)
            continue

        if final_result_from_llm.item_final:
            item.payload = final_result_from_llm.item_final
            fixed_codes = {c.error_code for c in final_result_from_llm.correcciones_finales if c.error_code}
            clean_specific_errors(item, fixed_codes) # Limpiar errores específicos corregidos

        clean_item_llm_errors(item) # Limpiar cualquier error LLM/parseo remanente de esta etapa

        if final_result_from_llm.correcciones_finales:
            add_audit_entry(
                item=item,
                stage_name=stage_name,
                summary="Micro-correcciones finales aplicadas.",
                correcciones=final_result_from_llm.correcciones_finales
            )

        if final_result_from_llm.final_warnings:
            item.warnings.extend(final_result_from_llm.final_warnings)
            add_audit_entry(
                item=item,
                stage_name=stage_name,
                summary=f"Advertencias finales: {len(final_result_from_llm.final_warnings)} detectadas."
            )

        if final_result_from_llm.observaciones_finales:
            add_audit_entry(
                item=item,
                stage_name=stage_name,
                summary=f"Observaciones finales del Agente: {final_result_from_llm.observaciones_finales}"
            )

        # El ítem se considera finalizado si el LLM dice que está OK y no quedan errores de severidad "error".
        if final_result_from_llm.final_check_ok and not any(err.severity == "error" for err in item.errors):
            update_item_status_and_audit(item=item, stage_name=stage_name, new_status="finalized", summary_msg="Ítem finalizado y listo para persistir.")
        else:
            update_item_status_and_audit(
                item=item,
                stage_name=stage_name,
                new_status="final_failed_validation",
                summary_msg=f"Ítem no pasó la validación final o tiene errores persistentes. Final check OK: {final_result_from_llm.final_check_ok}. Current Errors: {item.errors}"
            )
            logger.warning(f"Item {item.temp_id} not finalized: {item.status}. Current Errors: {item.errors}")

    logger.info("Finalize item stage completed for all items.")
    return items
