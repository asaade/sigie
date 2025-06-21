# app/pipelines/builtins/validate_policy.py

from __future__ import annotations
import logging
# Eliminado import json (encapsulado en llm_utils)
from typing import List, Dict, Any

from ..registry import register
from app.prompts import load_prompt # Mantenemos para la verificación inicial de prompt_name
from app.schemas.models import Item
from app.schemas.item_schemas import ReportEntrySchema
from app.validators import parse_policy_report # Necesario para parsear la respuesta del LLM

# Importar las utilidades
from ..utils.llm_utils import call_llm_and_parse_json_result
from ..utils.stage_helpers import skip_if_terminal_error, add_audit_entry

logger = logging.getLogger(__name__)

@register("validate_policy")
async def validate_policy_stage(items: List[Item], ctx: Dict[str, Any]) -> List[Item]:
    """
    Etapa de validación de políticas de ítems mediante un LLM (Agente de Políticas).
    El LLM evalúa el ítem en busca de sesgos, problemas de inclusión, y cumplimiento de políticas.
    No modifica el ítem directamente.
    Refactorizado para usar llm_utils y stage_helpers.
    """
    stage_name = "validate_policy"

    params = ctx.get("params", {}).get(stage_name, {})
    prompt_name = params.get("prompt", "05_agent_politicas.md") # Se mantiene un default, pero pipeline.yml debería definirlo

    try:
        _ = load_prompt(prompt_name)
    except FileNotFoundError as e:
        for item in items:
            item.status = "fatal_error"
            item.errors.append(
                ReportEntrySchema(
                    code="PROMPT_NOT_FOUND",
                    message=f"Prompt '{prompt_name}' not found for policy validation: {e}",
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

        # Asegurarse de que el ítem tenga un payload para validar
        if not item.payload:
            item.status = "policy_validation_skipped_no_payload"
            item.errors.append(
                ReportEntrySchema(
                    code="NO_PAYLOAD_FOR_POLICY_VALIDATION",
                    message="El ítem no tiene un payload para validar las políticas.",
                    severity="error"
                )
            )
            add_audit_entry(
                item=item,
                stage_name=stage_name,
                summary="Saltado: no hay payload de ítem para validar las políticas."
            )
            logger.warning(f"Item {item.temp_id} skipped in {stage_name}: no payload.")
            continue

        logger.info(f"Validating policy for item {item.temp_id} using prompt '{prompt_name}'.")

        # 2. Preparar input para el LLM: ItemPayloadSchema como JSON
        llm_input_content = item.payload.model_dump_json(indent=2)

        # 3. Llamada al LLM y obtención del texto crudo (para parse_policy_report) y errores de la utilidad
        # No se pasa expected_schema aquí porque parse_policy_report maneja su propio parseo.
        _, llm_errors_from_call_parse, raw_llm_text = await call_llm_and_parse_json_result(
            prompt_name=prompt_name,
            user_input_content=llm_input_content,
            stage_name=stage_name,
            item=item,
            ctx=ctx,
            expected_schema=None # No esperamos un esquema Pydantic directo de esta utilidad para el output del LLM
        )

        if llm_errors_from_call_parse: # Si hubo errores de llamada o parseo inicial del LLM
            item.status = "llm_policy_validation_failed"
            item.errors.extend(llm_errors_from_call_parse)
            add_audit_entry(
                item=item,
                stage_name=stage_name,
                summary=f"Fallo en llamada/parseo del LLM para validación de políticas. Errores: {', '.join([e.code for e in llm_errors_from_call_parse])}"
            )
            logger.error(f"LLM call or parsing failed for item {item.temp_id} in {stage_name}. Errors: {llm_errors_from_call_parse}")
            continue

        # Si el texto crudo no se obtuvo (ej. si prompt_name no fue encontrado o falla interna de llm_utils)
        if not raw_llm_text:
            item.status = "llm_policy_validation_failed"
            item.errors.append(
                ReportEntrySchema(
                    code="NO_LLM_RAW_TEXT",
                    message="La utilidad LLM no devolvió texto crudo para parseo de política.",
                    severity="error"
                )
            )
            add_audit_entry(
                item=item,
                stage_name=stage_name,
                summary="Error interno: La utilidad LLM no devolvió texto crudo."
            )
            logger.error(f"Internal error: LLM utility returned no raw text for item {item.temp_id} in {stage_name}.")
            continue

        # Parsear la respuesta del LLM usando parse_policy_report
        # Esta función maneja su propia extracción de JSON y validación (simple)
        policy_ok, llm_reports = parse_policy_report(raw_llm_text) # parse_policy_report devuelve List[ReportEntrySchema]

        current_summary_errors = [r for r in llm_reports if r.severity == "error"]
        current_summary_warnings = [r for r in llm_reports if r.severity == "warning"]

        item.warnings.extend(current_summary_warnings) # Añadir las advertencias
        item.errors.extend(current_summary_errors) # Añadir los errores (si los hay)

        if not policy_ok or current_summary_errors: # Si no está OK o si hay errores (severity=error)
            item.status = "failed_policy_validation" # Se marca para reintento de refinamiento o fallo final
            summary_msg = f"Validación de políticas: Falló. {len(current_summary_errors)} errores, {len(current_summary_warnings)} advertencias."
            logger.warning(f"Item {item.temp_id} failed policy validation. Report: {llm_reports}")
        else:
            # Solo actualizar el estado si no hay un error previo más grave
            # Añadido "refining_policy" para ítems que vuelven del refinador
            if item.status in ["hard_validated", "logic_validated", "soft_validated", "generated", "refining_logic_applied", "refining_style_applied", "refining_policy"]:
                item.status = "policy_validated"
            summary_msg = "Validación de políticas: OK."
            logger.info(f"Item {item.temp_id} passed policy validation.")

        add_audit_entry(
            item=item,
            stage_name=stage_name,
            summary=summary_msg
        )

    logger.info("Policy validation completed for all items.")
    return items
