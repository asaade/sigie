# app/pipelines/builtins/validate_policy.py

from __future__ import annotations
import logging
from typing import List, Dict, Any

from ..registry import register
from app.prompts import load_prompt
from app.schemas.models import Item
from app.schemas.item_schemas import ReportEntrySchema
from app.validators import parse_policy_report

from ..utils.llm_utils import call_llm_and_parse_json_result
from ..utils.stage_helpers import ( # Importar las nuevas funciones helper
    skip_if_terminal_error,
    add_audit_entry,
    handle_prompt_not_found_error,
    handle_missing_payload,
    clean_item_llm_errors,
    update_item_status_and_audit,
    handle_llm_call_and_parse_errors
)

logger = logging.getLogger(__name__)

@register("validate_policy")
async def validate_policy_stage(items: List[Item], ctx: Dict[str, Any]) -> List[Item]:
    """
    Etapa de validación de políticas de ítems mediante un LLM (Agente de Políticas).
    Refactorizado para usar llm_utils y stage_helpers.
    """
    stage_name = "validate_policy"

    params = ctx.get("params", {}).get(stage_name, {})
    prompt_name = params.get("prompt", "05_agent_politicas.md")

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
                "NO_PAYLOAD_FOR_POLICY_VALIDATION",
                "El ítem no tiene un payload para validar las políticas.",
                "policy_validation_skipped_no_payload",
                "Saltado: no hay payload de ítem para validar las políticas."
            )
            continue

        logger.info(f"Validating policy for item {item.temp_id} using prompt '{prompt_name}'.")

        llm_input_content = item.payload.model_dump_json(indent=2)

        policy_result_raw, llm_errors, _ = await call_llm_and_parse_json_result(
            prompt_name=prompt_name,
            user_input_content=llm_input_content,
            stage_name=stage_name,
            item=item,
            ctx=ctx,
            expected_schema=None, # No esperamos un esquema Pydantic directo aquí
            custom_parser_func=parse_policy_report # Usamos el parser personalizado
        )

        if await handle_llm_call_and_parse_errors(
            item=item,
            stage_name=stage_name,
            llm_errors_from_call_parse=llm_errors,
            llm_fail_status="llm_policy_validation_failed",
            summary_prefix="Fallo en llamada/parseo del LLM para validación de políticas"
        ):
            continue

        if not policy_result_raw: # Si el parser personalizado devolvió None como resultado
            update_item_status_and_audit(
                item=item,
                stage_name=stage_name,
                new_status="llm_policy_validation_failed", # Marcamos como fallo LLM si no hay resultado
                summary_msg="Error interno: El parser de política no devolvió un resultado válido.",
            )
            item.errors.append(
                ReportEntrySchema(
                    code="NO_LLM_POLICY_RESULT",
                    message="El parser de política no devolvió un resultado válido.",
                    severity="error"
                )
            )
            logger.error(f"Internal error: Policy parser returned no result for item {item.temp_id} in {stage_name}.")
            continue

        # policy_result_raw es ahora el dict/estructura que parse_policy_report devolvió: {"policy_ok": bool, "reports": List[ReportEntrySchema]}
        policy_ok = policy_result_raw.get("policy_ok", False)
        llm_reports = policy_result_raw.get("reports", [])

        current_summary_errors = [r for r in llm_reports if r.severity == "error"]
        current_summary_warnings = [r for r in llm_reports if r.severity == "warning"]

        item.warnings.extend(current_summary_warnings)
        item.errors.extend(current_summary_errors)

        if not policy_ok or current_summary_errors:
            update_item_status_and_audit(
                item=item,
                stage_name=stage_name,
                new_status="failed_policy_validation",
                summary_msg=f"Validación de políticas: Falló. {len(current_summary_errors)} errores, {len(current_summary_warnings)} advertencias."
            )
            logger.warning(f"Item {item.temp_id} failed policy validation. Report: {llm_reports}")
        else:
            clean_item_llm_errors(item) # Limpiar errores LLM/parseo si el ítem pasó ahora.
            if item.status in ["hard_validated", "logic_validated", "soft_validated", "generated", "refining_logic_applied", "refining_style_applied", "refining_policy"]:
                update_item_status_and_audit(
                    item=item,
                    stage_name=stage_name,
                    new_status="policy_validated",
                    summary_msg="Validación de políticas: OK."
                )
            else: # Si el estado era de un fallo no de política pero pasó la política ahora.
                add_audit_entry(
                    item=item,
                    stage_name=stage_name,
                    summary="Validación de políticas: OK. (Estado previo no alterado)."
                )
            logger.info(f"Item {item.temp_id} passed policy validation.")

    logger.info("Policy validation completed for all items.")
    return items
