# app/pipelines/builtins/refine_item_policy.py

from __future__ import annotations
import logging
import json # Necesario para json.dumps
from typing import List, Dict, Any

from ..registry import register
from app.prompts import load_prompt # Mantenemos para verificación inicial de prompt_name
from app.schemas.models import Item
from app.schemas.item_schemas import ReportEntrySchema, AuditEntrySchema, RefinementResultSchema

# Importar las nuevas utilidades
from ..utils.llm_utils import call_llm_and_parse_json_result
from ..utils.stage_helpers import skip_if_terminal_error, add_audit_entry

logger = logging.getLogger(__name__)

@register("refine_item_policy")
async def refine_item_policy_stage(items: List[Item], ctx: Dict[str, Any]) -> List[Item]:
    """
    Etapa de refinamiento de políticas de ítems mediante un LLM (Agente Refinador de Políticas).
    Recibe ítems con problemas de política y modifica el payload para corregirlos.
    Refactorizado para usar llm_utils y stage_helpers.
    """
    stage_name = "refine_item_policy"

    params = ctx.get("params", {}).get(stage_name, {})
    prompt_name = params.get("prompt", "06_agente_refinador_politicas.md") # Se mantiene un default, pero pipeline.yml debería definirlo

    try:
        _ = load_prompt(prompt_name)
    except FileNotFoundError as e:
        for item in items:
            item.status = "fatal_error"
            item.errors.append(
                ReportEntrySchema(
                    code="PROMPT_NOT_FOUND",
                    message=f"Prompt '{prompt_name}' not found for policy refinement: {e}",
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

        # Filtramos los errores y advertencias de política que el refinador debe corregir.
        # Esto incluye errores (severity="error") y advertencias (severity="warning").
        policy_problems_to_fix = [
            err for err in item.errors
            if err.code.startswith("E") and ("POLITICAS" in err.code or err.code == "LLM_PARSE_VALIDATION_ERROR_POLICY") # Errores de política o de parseo de políticas
            or err.code.startswith("W") and ("POLITICAS" in err.code or err.code in ["W102_ABSOL_STEM", "W103_HEDGE_STEM", "W107_COLOR_ALT", "W108_ALT_VAGUE", "W120_SESGO_GENERO", "W121_CULTURAL_EXCL"]) # Advertencias específicas de política/estilo
            or err.code in ["LLM_CALL_FAILED", "UNEXPECTED_LLM_PROCESSING_ERROR"] # Errores de la llamada LLM
            # Si el ítem viene de failed_policy_validation, es porque tiene errores de política
        ]

        if not policy_problems_to_fix and item.status == "failed_policy_validation":
            item.audits.append(
                AuditEntrySchema(
                    stage=stage_name,
                    summary="Saltado: Ítem marcado como 'failed_policy_validation' pero sin problemas de política para refinar. Podría estar corregido."
                )
            )
            item.status = "policy_validated_by_previous_refinement"
            logger.debug(f"Skipping item {item.temp_id} in {stage_name}: no policy problems to fix despite status.")
            continue
        elif not policy_problems_to_fix:
             item.audits.append(
                AuditEntrySchema(
                    stage=stage_name,
                    summary="Saltado: Ítem sin problemas de política para refinar."
                )
            )
             logger.debug(f"Skipping item {item.temp_id} in {stage_name}: no policy problems to fix.")
             continue

        if not item.payload:
            item.status = "refinement_skipped_no_payload"
            item.errors.append(
                ReportEntrySchema(
                    code="NO_PAYLOAD_FOR_REFINEMENT",
                    message="El ítem no tiene un payload para refinar las políticas.",
                    severity="error"
                )
            )
            add_audit_entry(
                item=item,
                stage_name=stage_name,
                summary="Saltado: no hay payload de ítem para refinar las políticas."
            )
            logger.warning(f"Item {item.temp_id} skipped in {stage_name}: no payload.")
            continue

        logger.info(f"Refining policy for item {item.temp_id} with {len(policy_problems_to_fix)} problems.")

        # 2. Preparar input para el LLM: Ítem actual + problemas detectados
        llm_input_payload = {
            "item": item.payload.model_dump(),
            "problems": [prob.model_dump() for prob in policy_problems_to_fix]
        }
        llm_input_content = json.dumps(llm_input_payload, indent=2, ensure_ascii=False)

        # 3. Llamada al LLM y parseo usando la utilidad
        refinement_result_from_llm, llm_errors, _ = await call_llm_and_parse_json_result( # Recibimos el texto crudo pero no lo usamos aquí
            prompt_name=prompt_name,
            user_input_content=llm_input_content,
            stage_name=stage_name,
            item=item,
            ctx=ctx,
            expected_schema=RefinementResultSchema # Esperamos la misma estructura de resultado de refinamiento
        )

        if llm_errors:
            item.status = "refinement_failed"
            item.errors.extend(llm_errors)
            add_audit_entry(
                item=item,
                stage_name=stage_name,
                summary=f"Fallo en llamada/parseo del LLM para refinamiento de políticas. Errores: {', '.join([e.code for e in llm_errors])}"
            )
            logger.error(f"LLM call or parsing failed for item {item.temp_id} in {stage_name}. Errors: {llm_errors}")
            continue

        if not refinement_result_from_llm:
             item.status = "refinement_failed_no_result"
             item.errors.append(
                 ReportEntrySchema(
                     code="NO_REFINEMENT_RESULT",
                     message="La utilidad de LLM no devolvió un resultado de refinamiento válido.",
                     severity="error"
                 )
             )
             add_audit_entry(
                 item=item,
                 stage_name=stage_name,
                 summary="Error interno: La utilidad LLM no devolvió resultado de refinamiento."
             )
             logger.error(f"Internal error: LLM utility returned no result for item {item.temp_id} in {stage_name}.")
             continue

        # Validar que el item_id del refinador coincide
        if refinement_result_from_llm.item_id != item.temp_id:
            item.status = "refinement_failed_mismatch"
            error_msg = f"Mismatched item_id in LLM policy refinement response. Expected {item.temp_id}, got {refinement_result_from_llm.item_id}."
            item.errors.append(
                ReportEntrySchema(
                    code="ITEM_ID_MISMATCH_REFINEMENT",
                    message=error_msg,
                    field="item_id",
                    severity="error"
                )
            )
            add_audit_entry(
                item=item,
                stage_name=stage_name,
                summary="Item ID mismatched en respuesta de refinamiento de política."
            )
            logger.error(error_msg)
            continue

        # Aplicar las correcciones al payload del ítem
        item.payload = refinement_result_from_llm.item_refinado

        # Limpiar los problemas de política anteriores (errores y advertencias)
        fixed_codes = {c.error_code for c in refinement_result_from_llm.correcciones_realizadas if c.error_code}
        item.errors = [err for err in item.errors if err.code not in fixed_codes and not (err.code.startswith("LLM_CALL_FAILED") or err.code.startswith("LLM_PARSE_VALIDATION_ERROR") or err.code.startswith("UNEXPECTED_LLM_PROCESSING_ERROR"))]
        item.warnings = [warn for warn in item.warnings if warn.code not in fixed_codes]

        # Añadir las correcciones realizadas al registro de auditoría del ítem
        add_audit_entry(
            item=item,
            stage_name=stage_name,
            summary="Refinamiento de políticas aplicado.",
            corrections=refinement_result_from_llm.correcciones_realizadas
        )

        # Marcar el ítem para revalidación por el Agente de Políticas
        item.status = "refining_policy"
        logger.info(f"Item {item.temp_id} policy refinement applied. Status: {item.status}")

    logger.info("Policy refinement stage completed for all items.")
    return items
