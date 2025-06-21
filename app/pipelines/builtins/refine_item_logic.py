# app/pipelines/builtins/refine_item_logic.py

from __future__ import annotations
import logging
import json # Necesario para json.dumps
from typing import List, Dict, Any, Optional

from ..registry import register
# Eliminadas generate_response, LLMResponse, load_prompt - encapsulados en llm_utils
from app.llm import LLMResponse # Mantenemos para tipado si es necesario, aunque su uso directo se encapsula
from app.prompts import load_prompt # Mantenemos para la verificación inicial de prompt_name
from app.schemas.models import Item
from app.schemas.item_schemas import ReportEntrySchema, AuditEntrySchema, RefinementResultSchema, CorrectionEntrySchema, ItemPayloadSchema
from pydantic import ValidationError # Mantenemos para manejar errores de validación si es necesario fuera de llm_utils

# Importar las nuevas utilidades
from ..utils.llm_utils import call_llm_and_parse_json_result
from ..utils.stage_helpers import skip_if_terminal_error, add_audit_entry

logger = logging.getLogger(__name__)

@register("refine_item_logic")
async def refine_item_logic_stage(items: List[Item], ctx: Dict[str, Any]) -> List[Item]:
    """
    Etapa de refinamiento lógico de ítems mediante un LLM (Agente Refinador de Razonamiento).
    Recibe ítems con errores lógicos y modifica el payload para corregirlos.
    Refactorizado para usar llm_utils y stage_helpers.
    """
    stage_name = "refine_item_logic"

    params = ctx.get("params", {}).get(stage_name, {})
    prompt_name = params.get("prompt", "03_agente_refinador_razonamiento.md") # Se mantiene un default, pero pipeline.yml debería definirlo

    try:
        # Verificación inicial de prompt, aunque call_llm_and_parse_json_result también lo hace
        _ = load_prompt(prompt_name)
    except FileNotFoundError as e:
        for item in items:
            item.status = "fatal_error"
            item.errors.append(
                ReportEntrySchema(
                    code="PROMPT_NOT_FOUND",
                    message=f"Prompt '{prompt_name}' not found for logic refinement: {e}",
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
        # 1. Saltar ítems ya en estado de error terminal o si no deben ser procesados
        if skip_if_terminal_error(item, stage_name):
            continue

        # Filtramos los errores que son de severidad "error" y que no sean de parseo del LLM
        # Estos son los 'problems' que el refinador debe corregir.
        logic_errors_to_fix = [
            err for err in item.errors
            if err.severity == "error" and
            (err.code.startswith("E") or err.code == "LLM_PARSE_ERROR" or err.code == "UNEXPECTED_PARSE_ERROR")
        ]

        # Si el ítem llega aquí, significa que falló 'validate_logic', por lo que debería tener errores.
        # Sin embargo, si en un ciclo de reintento ya no tiene los errores originales, podría ser un caso de éxito.
        if not logic_errors_to_fix and item.status == "failed_logic_validation":
            item.audits.append(
                AuditEntrySchema(
                    stage=stage_name,
                    summary="Saltado: Ítem marcado como 'failed_logic_validation' pero sin errores lógicos para refinar. Podría estar corregido."
                )
            )
            item.status = "logic_validated_by_previous_refinement" # Estado para indicar que no se necesitó acción en esta pasada
            logger.debug(f"Skipping item {item.temp_id} in {stage_name}: no logic errors to fix despite status.")
            continue
        elif not logic_errors_to_fix: # Si no hay errores y no viene de failed_logic_validation (ej. si viene de refine_style)
             item.audits.append(
                AuditEntrySchema(
                    stage=stage_name,
                    summary="Saltado: Ítem sin errores lógicos de tipo 'error' para refinar."
                )
            )
             logger.debug(f"Skipping item {item.temp_id} in {stage_name}: no logic errors to fix.")
             continue

        # Asegurarse de que el ítem tenga un payload para refinar
        if not item.payload:
            item.status = "refinement_skipped_no_payload"
            item.errors.append(
                ReportEntrySchema(
                    code="NO_PAYLOAD_FOR_REFINEMENT",
                    message="El ítem no tiene un payload para refinar la lógica.",
                    severity="error"
                )
            )
            add_audit_entry(
                item=item,
                stage_name=stage_name,
                summary="Saltado: no hay payload de ítem para refinar la lógica."
            )
            logger.warning(f"Item {item.temp_id} skipped in {stage_name}: no payload.")
            continue

        logger.info(f"Refining logic for item {item.temp_id} with {len(logic_errors_to_fix)} errors.")

        # 2. Preparar input para el LLM: Ítem actual + problemas detectados
        llm_input_payload = {
            "item": item.payload.model_dump(), # Pasar el payload como un diccionario para el prompt
            "problems": [err.model_dump() for err in logic_errors_to_fix] # Pasar los errores como dicts
        }
        llm_input_content = json.dumps(llm_input_payload, indent=2, ensure_ascii=False)

        # 3. Llamada al LLM y parseo usando la utilidad
        refinement_result_from_llm, llm_errors = await call_llm_and_parse_json_result(
            prompt_name=prompt_name,
            user_input_content=llm_input_content,
            stage_name=stage_name,
            item=item, # Se pasa el item para que la utilidad registre tokens y auditorías
            ctx=ctx,
            expected_schema=RefinementResultSchema # Espera la estructura de resultado de refinamiento
        )

        if llm_errors: # Si hubo errores de llamada o parseo del LLM
            item.status = "refinement_failed" # Estado de fallo genérico de refinamiento
            item.errors.extend(llm_errors)
            add_audit_entry(
                item=item,
                stage_name=stage_name,
                summary=f"Fallo en llamada/parseo del LLM para refinamiento lógico. Errores: {', '.join([e.code for e in llm_errors])}"
            )
            logger.error(f"LLM call or parsing failed for item {item.temp_id} in {stage_name}. Errors: {llm_errors}")
            continue # Pasa al siguiente ítem

        # Si la utilidad no devolvió un resultado válido (y no hubo errores explícitos)
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
            error_msg = f"Mismatched item_id in LLM logic refinement response. Expected {item.temp_id}, got {refinement_result_from_llm.item_id}."
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
                summary=f"Item ID mismatched en respuesta de refinamiento lógico."
            )
            logger.error(error_msg)
            continue

        # Aplicar las correcciones al payload del ítem
        item.payload = refinement_result_from_llm.item_refinado # Reemplazamos el payload con el corregido

        # Limpiar los errores lógicos anteriores que motivaron este refinamiento
        # Se asume que el refinador intentó corregir todos los problemas pasados.
        fixed_codes = {c.error_code for c in refinement_result_from_llm.correcciones_realizadas if c.error_code}
        item.errors = [
            err for err in item.errors
            if err.code not in fixed_codes and not (
                err.code.startswith("LLM_CALL_FAILED") or
                err.code.startswith("LLM_PARSE_VALIDATION_ERROR") or
                err.code.startswith("UNEXPECTED_LLM_PROCESSING_ERROR")
            )
        ]
        # También limpiar advertencias si el refinador de lógica pudo haberlas corregido (menos común)
        item.warnings = [
            warn for warn in item.warnings
            if warn.code not in fixed_codes
        ]


        # Añadir las correcciones realizadas al registro de auditoría del ítem
        add_audit_entry(
            item=item,
            stage_name=stage_name,
            summary="Refinamiento lógico aplicado.",
            corrections=refinement_result_from_llm.correcciones_realizadas
        )

        # Marcar el ítem para revalidación por el Agente de Razonamiento
        item.status = "refining_logic" # El runner lo detectará y lo enviará de vuelta a validate_logic
        logger.info(f"Item {item.temp_id} logic refinement applied. Status: {item.status}")

    logger.info(f"Logic refinement stage completed for all items.")
    return items
