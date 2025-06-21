# app/pipelines/builtins/validate_logic.py

from __future__ import annotations
import logging
# Eliminado import json - encapsulado en llm_utils
from typing import List, Dict, Any # Eliminado Tuple que no se usaba

from ..registry import register
# Eliminadas generate_response, LLMResponse, load_prompt - encapsulados en llm_utils
from app.llm import generate_response, LLMResponse # Mantengo LLMResponse para tipado, generate_response se usa dentro de llm_utils
from app.prompts import load_prompt # Mantenemos para la verificación inicial de prompt_name
from app.schemas.models import Item
# Eliminada la importación directa de parse_logic_report, ahora encapsulada en llm_utils
from app.schemas.item_schemas import ReportEntrySchema, AuditEntrySchema, LogicValidationResultSchema # Todas estas son necesarias
# Eliminada extract_json_block - encapsulado en llm_utils
# Eliminada la importación de _helpers.add_tokens, ya que la acumulación de tokens está en llm_utils.call_llm_and_parse_json_result

# Importar las nuevas utilidades
from ..utils.llm_utils import call_llm_and_parse_json_result
from ..utils.stage_helpers import skip_if_terminal_error, add_audit_entry


logger = logging.getLogger(__name__)

@register("validate_logic")
async def validate_logic_stage(items: List[Item], ctx: Dict[str, Any]) -> List[Item]:
    """
    Etapa de validación lógica de ítems mediante un LLM (Agente de Razonamiento).
    El LLM detecta errores de coherencia, precisión y nivel cognitivo, sin modificar el ítem.
    Refactorizado para usar llm_utils y stage_helpers.
    """
    stage_name = "validate_logic"

    params = ctx.get("params", {}).get(stage_name, {})
    prompt_name = params.get("prompt", "02_agent_razonamiento.md") # Se mantiene un default, pero pipeline.yml debería definirlo

    try:
        # Verificación inicial de prompt, aunque call_llm_and_parse_json_result también lo hace
        _ = load_prompt(prompt_name)
    except FileNotFoundError as e:
        for item in items:
            item.status = "fatal_error"
            item.errors.append(
                ReportEntrySchema(
                    code="PROMPT_NOT_FOUND",
                    message=f"Prompt '{prompt_name}' not found for logic validation: {e}",
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
            item.status = "logic_validation_skipped_no_payload"
            item.errors.append(
                ReportEntrySchema(
                    code="NO_PAYLOAD_FOR_LOGIC_VALIDATION",
                    message="El ítem no tiene un payload para validar la lógica.",
                    severity="error"
                )
            )
            add_audit_entry(
                item=item,
                stage_name=stage_name,
                summary="Saltado: no hay payload de ítem para validar la lógica."
            )
            logger.warning(f"Item {item.temp_id} skipped in {stage_name}: no payload.")
            continue

        logger.info(f"Validating logic for item {item.temp_id} using prompt '{prompt_name}'.")

        # 2. Preparar input para el LLM: ItemPayloadSchema como JSON
        llm_input_content = item.payload.model_dump_json(indent=2)

        # 3. Llamada al LLM y parseo usando la utilidad
        # expected_schema es LogicValidationResultSchema
        logic_result_from_llm, llm_errors_from_call_parse = await call_llm_and_parse_json_result(
            prompt_name=prompt_name,
            user_input_content=llm_input_content,
            stage_name=stage_name,
            item=item, # Se pasa el item para que la utilidad registre tokens y auditorías
            ctx=ctx,
            expected_schema=LogicValidationResultSchema # Espera la estructura de reporte lógico del LLM
        )

        if llm_errors_from_call_parse: # Si hubo errores de llamada o parseo inicial del LLM
            item.status = "llm_logic_validation_failed"
            item.errors.extend(llm_errors_from_call_parse)
            add_audit_entry(
                item=item,
                stage_name=stage_name,
                summary=f"Fallo en llamada/parseo del LLM para validación lógica. Errores: {', '.join([e.code for e in llm_errors_from_call_parse])}"
            )
            logger.error(f"LLM call or parsing failed for item {item.temp_id} in {stage_name}. Errors: {llm_errors_from_call_parse}")
            continue # Pasa al siguiente ítem

        # Si la utilidad no devolvió un resultado válido (y no hubo errores explícitos)
        if not logic_result_from_llm:
            item.status = "llm_logic_validation_failed"
            item.errors.append(
                ReportEntrySchema(
                    code="NO_LLM_LOGIC_RESULT",
                    message="La utilidad de LLM no devolvió un resultado de validación lógica.",
                    severity="error"
                )
            )
            add_audit_entry(
                item=item,
                stage_name=stage_name,
                summary="Error interno: La utilidad LLM no devolvió resultado de validación lógica."
            )
            logger.error(f"Internal error: LLM utility returned no logic result for item {item.temp_id} in {stage_name}.")
            continue

        # Procesar los errores reportados por el LLM Agente de Razonamiento
        if not logic_result_from_llm.logic_ok:
            item.status = "failed_logic_validation" # Se marca para reintento de refinamiento
            # Aseguramos que los errores del LLM tengan severity="error" como este agente sólo reporta errores críticos.
            # Esto ya se maneja en parse_logic_report dentro de __init__.py, pero lo reaseguramos.
            processed_llm_errors = [
                ReportEntrySchema(
                    code=err.code,
                    message=err.message,
                    field=err.field,
                    severity="error"
                ) for err in logic_result_from_llm.errors
            ]
            item.errors.extend(processed_llm_errors)

            summary_msg = f"Validación lógica: Falló. {len(processed_llm_errors)} errores detectados."
            logger.warning(f"Item {item.temp_id} failed logic validation. Errors: {processed_llm_errors}")
        else:
            # Solo actualizar el estado si no hay un error previo más grave
            # Se añade "refining_logic" para asegurar que los ítems que vuelven del refinador
            # también actualicen su estado si pasan la revalidación.
            if item.status in ["hard_validated", "generated", "refining_logic"]:
                item.status = "logic_validated"
            summary_msg = "Validación lógica: OK."
            logger.info(f"Item {item.temp_id} passed logic validation.")

        # Añadir entrada de auditoría (resumen principal de la etapa)
        add_audit_entry(
            item=item,
            stage_name=stage_name,
            summary=summary_msg,
            # No se añaden correcciones aquí, porque esta es una etapa de validación.
            # Los errores se añaden directamente a item.errors.
        )

    logger.info(f"Logic validation completed for all items.")
    return items
