# app/pipelines/builtins/validate_logic.py

from __future__ import annotations
import logging
from typing import List, Dict, Any

from ..registry import register
from app.prompts import load_prompt
from app.schemas.models import Item
from app.schemas.item_schemas import ReportEntrySchema, LogicValidationResultSchema

from ..utils.llm_utils import call_llm_and_parse_json_result
from ..utils.stage_helpers import ( # Importar las nuevas funciones helper
    skip_if_terminal_error,
    add_audit_entry,
    handle_prompt_not_found_error,
    handle_llm_call_and_parse_errors,
    handle_missing_payload,
    clean_item_llm_errors,
    update_item_status_and_audit
)


logger = logging.getLogger(__name__)

@register("validate_logic")
async def validate_logic_stage(items: List[Item], ctx: Dict[str, Any]) -> List[Item]:
    """
    Etapa de validación lógica de ítems mediante un LLM (Agente de Razonamiento).
    Refactorizado para usar llm_utils y stage_helpers.
    """
    stage_name = "validate_logic"

    params = ctx.get("params", {}).get(stage_name, {})
    prompt_name = params.get("prompt", "02_agent_razonamiento.md")

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
                "NO_PAYLOAD_FOR_LOGIC_VALIDATION",
                "El ítem no tiene un payload para validar la lógica.",
                "logic_validation_skipped_no_payload",
                "Saltado: no hay payload de ítem para validar la lógica."
            )
            continue

        logger.info(f"Validating logic for item {item.temp_id} using prompt '{prompt_name}'.")

        llm_input_content = item.payload.model_dump_json(indent=2)

        logic_result_from_llm, llm_errors, _ = await call_llm_and_parse_json_result(
            prompt_name=prompt_name,
            user_input_content=llm_input_content,
            stage_name=stage_name,
            item=item,
            ctx=ctx,
            expected_schema=LogicValidationResultSchema
        )

        if await handle_llm_call_and_parse_errors(
            item=item,
            stage_name=stage_name,
            llm_errors_from_call_parse=llm_errors,
            llm_fail_status="llm_logic_validation_failed",
            summary_prefix="Fallo en llamada/parseo del LLM para validación lógica"
        ):
            # Si hubo errores de utilidad, el ítem ya está marcado y auditado por handle_llm_call_and_parse_errors
            continue

        # Si la utilidad no devolvió un resultado válido (y no hubo errores explícitos de la llamada)
        if not logic_result_from_llm:
            update_item_status_and_audit(
                item=item,
                stage_name=stage_name,
                new_status="llm_logic_validation_failed", # Marcamos como fallo LLM si no hay resultado
                summary_msg="Error interno: La utilidad LLM no devolvió resultado de validación lógica.",
            )
            item.errors.append(
                ReportEntrySchema(
                    code="NO_LLM_LOGIC_RESULT",
                    message="La utilidad de LLM no devolvió un resultado de validación lógica.",
                    severity="error"
                )
            )
            logger.error(f"Internal error: LLM utility returned no logic result for item {item.temp_id} in {stage_name}.")
            continue

        # Procesar los errores reportados por el LLM Agente de Razonamiento
        if not logic_result_from_llm.logic_ok:
            # Aseguramos que los errores del LLM tengan severity="error" como este agente sólo reporta errores críticos.
            processed_llm_errors = [
                ReportEntrySchema(
                    code=err.code,
                    message=err.message,
                    field=err.field,
                    severity="error"
                ) for err in logic_result_from_llm.errors
            ]
            item.errors.extend(processed_llm_errors)

            update_item_status_and_audit(
                item=item,
                stage_name=stage_name,
                new_status="failed_logic_validation",
                summary_msg=f"Validación lógica: Falló. {len(processed_llm_errors)} errores detectados."
            )
            logger.warning(f"Item {item.temp_id} failed logic validation. Errors: {processed_llm_errors}")
        else:
            # Limpiar cualquier error LLM_CALL/PARSE previo si el ítem pasó ahora.
            clean_item_llm_errors(item)
            # Solo actualizar el estado si no hay un error previo más grave
            if item.status in ["hard_validated", "generated", "refining_logic", "refining_style_applied"]: # Añadido refining_style_applied
                update_item_status_and_audit(
                    item=item,
                    stage_name=stage_name,
                    new_status="logic_validated",
                    summary_msg="Validación lógica: OK."
                )
            else: # Si el estado era de un fallo no lógico pero pasó la lógica ahora.
                add_audit_entry(
                    item=item,
                    stage_name=stage_name,
                    summary="Validación lógica: OK. (Estado previo no alterado)."
                )
            logger.info(f"Item {item.temp_id} passed logic validation.")

    logger.info("Logic validation completed for all items.")
    return items
