# app/pipelines/builtins/refine_item_style.py

import logging
import json
from typing import List, Dict, Any, Optional

from ..registry import register
from app.llm import generate_response, LLMResponse
from app.prompts import load_prompt
from app.schemas.models import Item
from app.schemas.item_schemas import ReportEntrySchema, AuditEntrySchema, RefinementResultSchema, CorrectionEntrySchema, ItemPayloadSchema
from pydantic import ValidationError

from ..utils.llm_utils import call_llm_and_parse_json_result # Importar la utilidad
from ..utils.stage_helpers import skip_if_terminal_error, add_audit_entry

logger = logging.getLogger(__name__)

@register("refine_item_style")
async def refine_item_style_stage(items: List[Item], ctx: Dict[str, Any]) -> List[Item]:
    """
    Etapa de refinamiento de estilo de ítems mediante un LLM (Agente Refinador de Estilo).
    Realiza una revisión y corrección integral del estilo, concisión y tono del ítem.
    """
    stage_name = "refine_item_style"

    params = ctx.get("params", {}).get(stage_name, {})
    prompt_name = params.get("prompt", "04_agente_refinador_estilo.md")

    try:
        prompt_template = load_prompt(prompt_name) # Aunque ahora lo hará call_llm_and_parse_json_result, la dejamos para validación inicial
    except FileNotFoundError as e:
        for item in items:
            item.status = "fatal_error"
            item.errors.append(
                ReportEntrySchema(
                    code="PROMPT_NOT_FOUND",
                    message=f"Prompt '{prompt_name}' not found for style refinement: {e}",
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

        # Asegurarse de que el ítem tenga un payload para refinar
        if not item.payload:
            item.status = "refinement_skipped_no_payload"
            item.errors.append(
                ReportEntrySchema(
                    code="NO_PAYLOAD_FOR_REFINEMENT",
                    message="El ítem no tiene un payload para refinar el estilo.",
                    severity="error"
                )
            )
            add_audit_entry(
                item=item,
                stage_name=stage_name,
                summary="Saltado: no hay payload de ítem para refinar el estilo."
            )
            logger.warning(f"Item {item.temp_id} skipped in {stage_name}: no payload.")
            continue

        logger.info(f"Refining style for item {item.temp_id} using prompt '{prompt_name}'.")

        # El refinador de estilo no necesita una lista de "problems" específicos como el lógico.
        # Recibe el ítem completo y aplica una revisión integral.
        llm_input_content = item.payload.model_dump_json(indent=2)

        # 2. Llamada al LLM y parseo usando la utilidad
        refinement_result_raw, llm_errors = await call_llm_and_parse_json_result(
            prompt_name=prompt_name,
            user_input_content=llm_input_content,
            stage_name=stage_name,
            item=item,
            ctx=ctx,
            expected_schema=RefinementResultSchema # Esperamos la misma estructura de resultado de refinamiento
        )

        if llm_errors: # Si hubo errores de llamada o parseo del LLM
            item.status = "refinement_failed" # Estado de fallo genérico de refinamiento
            item.errors.extend(llm_errors)
            add_audit_entry(
                item=item,
                stage_name=stage_name,
                summary=f"Fallo en llamada/parseo del LLM para refinamiento de estilo. Errores: {', '.join([e.code for e in llm_errors])}"
            )
            logger.error(f"LLM call or parsing failed for item {item.temp_id} in {stage_name}. Errors: {llm_errors}")
            continue # Pasa al siguiente ítem

        # Asegurarse de que el resultado parseado no es None si no hubo errores de LLM
        if not refinement_result_raw:
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
        if refinement_result_raw.item_id != item.temp_id:
            item.status = "refinement_failed_mismatch"
            error_msg = f"Mismatched item_id in LLM style refinement response. Expected {item.temp_id}, got {refinement_result_raw.item_id}."
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
                summary=f"Item ID mismatched en respuesta de refinamiento de estilo."
            )
            logger.error(error_msg)
            continue

        # Aplicar las correcciones al payload del ítem
        item.payload = refinement_result_raw.item_refinado # Reemplazamos el payload con el corregido

        # Limpiar las advertencias de estilo anteriores (generadas por validate_soft)
        # Esto asume que el refinador intentó corregir todos los problemas de estilo.
        # Podríamos hacer un filtrado más fino si el refinador indica qué warnings corrigió.
        # Por ahora, eliminamos todas las warnings de 'soft' para reevaluar en etapas posteriores.
        item.warnings = [
            warn for warn in item.warnings
            if not (warn.code.startswith("W") and warn.code not in ["W106_TODAS_NINGUNA", "W101_STEM_NEG_LOWER"]) # Mantener warnings que el refinador no debería tocar.
            # Los warnings como W106 y W101 podrían ser errores de HARD_VALIDATION si no se corrigen en la siguiente validación.
        ]
        # También limpiamos errores de LLM/parseo anteriores si los hubo
        item.errors = [
            err for err in item.errors
            if not (err.code.startswith("LLM_CALL_FAILED") or err.code.startswith("LLM_PARSE_ERROR") or err.code.startswith("UNEXPECTED_LLM_PROCESSING_ERROR"))
        ]

        # Añadir las correcciones realizadas al registro de auditoría del ítem
        add_audit_entry(
            item=item,
            stage_name=stage_name,
            summary="Refinamiento de estilo aplicado.",
            corrections=refinement_result_raw.correcciones_realizadas # Usamos la lista de correcciones del LLM
        )

        # Marcar el ítem para revalidación por una etapa de estilo posterior (ej. validate_soft de nuevo o una final)
        item.status = "refining_style_applied"
        logger.info(f"Item {item.temp_id} style refinement applied. Status: {item.status}")

    logger.info(f"Style refinement stage completed for all items.")
    return items
