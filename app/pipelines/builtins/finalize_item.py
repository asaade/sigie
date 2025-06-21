# app/pipelines/builtins/finalize_item.py

from __future__ import annotations
import logging
from typing import List, Dict, Any

from ..registry import register
# Eliminadas generate_response, LLMResponse, load_prompt (encapsulados en llm_utils)
from app.prompts import load_prompt # Mantenemos para verificación inicial de prompt_name
from app.schemas.models import Item
from app.schemas.item_schemas import ReportEntrySchema, FinalizationResultSchema

# Importar las nuevas utilidades
from ..utils.llm_utils import call_llm_and_parse_json_result
from ..utils.stage_helpers import skip_if_terminal_error, add_audit_entry

logger = logging.getLogger(__name__)

@register("finalize_item")
async def finalize_item_stage(items: List[Item], ctx: Dict[str, Any]) -> List[Item]:
    """
    Etapa de finalización de ítems mediante un LLM (Agente Final).
    Realiza una revisión final de coherencia global y aplica micro-correcciones.
    Refactorizado para usar llm_utils y stage_helpers.
    """
    stage_name = "finalize_item"

    params = ctx.get("params", {}).get(stage_name, {})
    prompt_name = params.get("prompt", "07_agent_final.md") # Se mantiene un default, pero pipeline.yml debería definirlo

    try:
        _ = load_prompt(prompt_name)
    except FileNotFoundError as e:
        for item in items:
            item.status = "fatal_error"
            item.errors.append(
                ReportEntrySchema(
                    code="PROMPT_NOT_FOUND",
                    message=f"Prompt '{prompt_name}' not found for finalization stage: {e}",
                    field="prompt_name",
                    severity="error"
                )
            )
            add_audit_entry(
                item=item,
                stage_name=stage_name,
                summary=f"Error fatal: El archivo de prompt '{prompt_name}' no fue encontrado."
            )
        logger.error(f"Failed to load prompt '{prompt_name}': {e}")
        return items

    for item in items:
        # 1. Saltar ítems ya en estado de error terminal
        if skip_if_terminal_error(item, stage_name):
            continue

        # Asegurarse de que el ítem tenga un payload para finalizar
        if not item.payload:
            item.status = "finalization_skipped_no_payload"
            item.errors.append(
                ReportEntrySchema(
                    code="NO_PAYLOAD_FOR_FINALIZATION",
                    message="El ítem no tiene un payload para la etapa de finalización.",
                    severity="error"
                )
            )
            add_audit_entry(
                item=item,
                stage_name=stage_name,
                summary="Saltado: no hay payload de ítem para la finalización."
            )
            logger.warning(f"Item {item.temp_id} skipped in {stage_name}: no payload.")
            continue

        logger.info(f"Finalizing item {item.temp_id} using prompt '{prompt_name}'.")

        # 2. Preparar input para el LLM: Ítem completo para revisión global
        llm_input_content = item.payload.model_dump_json(indent=2)

        # 3. Llamada al LLM y parseo usando la utilidad
        final_result_from_llm, llm_errors, _ = await call_llm_and_parse_json_result( # No necesitamos el raw_llm_text aquí
            prompt_name=prompt_name,
            user_input_content=llm_input_content,
            stage_name=stage_name,
            item=item,
            ctx=ctx,
            expected_schema=FinalizationResultSchema # Esperamos la estructura de resultado de finalización
        )

        if llm_errors: # Si hubo errores de llamada o parseo del LLM
            item.status = "llm_finalization_failed"
            item.errors.extend(llm_errors)
            add_audit_entry(
                item=item,
                stage_name=stage_name,
                summary=f"Fallo en llamada/parseo del LLM para finalización. Errores: {', '.join([e.code for e in llm_errors])}"
            )
            logger.error(f"LLM call or parsing failed for item {item.temp_id} in {stage_name}. Errors: {llm_errors}")
            continue

        if not final_result_from_llm: # Error interno de la utilidad
             item.status = "finalization_failed_no_result"
             item.errors.append(
                 ReportEntrySchema(
                     code="NO_FINALIZATION_RESULT",
                     message="La utilidad de LLM no devolvió un resultado de finalización válido.",
                     severity="error"
                 )
             )
             add_audit_entry(
                 item=item,
                 stage_name=stage_name,
                 summary="Error interno: La utilidad LLM no devolvió resultado de finalización."
             )
             logger.error(f"Internal error: LLM utility returned no finalization result for item {item.temp_id} in {stage_name}.")
             continue

        # Validar que el item_id del resultado final coincide
        if final_result_from_llm.item_id != item.temp_id:
            item.status = "finalization_failed_mismatch"
            error_msg = f"Mismatched item_id in LLM finalization response. Expected {item.temp_id}, got {final_result_from_llm.item_id}."
            item.errors.append(
                ReportEntrySchema(
                    code="ITEM_ID_MISMATCH_FINALIZATION",
                    message=error_msg,
                    field="item_id",
                    severity="error"
                )
            )
            add_audit_entry(
                item=item,
                stage_name=stage_name,
                summary="Item ID mismatched en respuesta de finalización."
            )
            logger.error(error_msg)
            continue

        # Aplicar las correcciones finales si existen
        if final_result_from_llm.item_final:
            item.payload = final_result_from_llm.item_final # Reemplazamos el payload con el final
            # Limpiar errores/advertencias relacionados con campos que pudieron ser corregidos
            fixed_codes = {c.error_code for c in final_result_from_llm.correcciones_finales if c.error_code}
            item.errors = [err for err in item.errors if err.code not in fixed_codes]
            item.warnings = [warn for warn in item.warnings if warn.code not in fixed_codes]

        # Añadir correcciones finales y advertencias finales al ítem
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

        # Añadir observaciones finales del agente (si las hay)
        if final_result_from_llm.observaciones_finales:
            add_audit_entry(
                item=item,
                stage_name=stage_name,
                summary=f"Observaciones finales del Agente: {final_result_from_llm.observaciones_finales}"
            )

        # Determinar el estado final basado en si el Agente Final reporta que el chequeo fue OK y no hay nuevos errores críticos.
        # Limpiar errores de LLM/parseo de esta etapa si los hubo antes del proceso
        item.errors = [
            err for err in item.errors
            if not (err.code.startswith("LLM_CALL_FAILED") or err.code.startswith("LLM_PARSE_VALIDATION_ERROR") or err.code.startswith("UNEXPECTED_LLM_PROCESSING_ERROR"))
        ]

        # El ítem se considera finalizado si el LLM dice que está OK y no quedan errores de severidad "error".
        if final_result_from_llm.final_check_ok and not any(err.severity == "error" for err in item.errors):
            item.status = "finalized"
            final_summary_msg = "Ítem finalizado y listo para persistir."
        else:
            item.status = "final_failed_validation"
            final_summary_msg = "Ítem no pasó la validación final o tiene errores persistentes."
            logger.warning(f"Item {item.temp_id} not finalized: {final_summary_msg}. Final check OK: {final_result_from_llm.final_check_ok}. Current Errors: {item.errors}")

        add_audit_entry(item=item, stage_name=stage_name, summary=final_summary_msg)
        logger.info(f"Item {item.temp_id} finalization result: {item.status}")

    logger.info("Finalize item stage completed for all items.")
    return items
