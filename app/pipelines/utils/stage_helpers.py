# app/pipelines/utils/stage_helpers.py

import logging
from typing import List, Any, Optional, Type
from pydantic import BaseModel

from app.schemas.models import Item
from app.schemas.item_schemas import AuditEntrySchema, ReportEntrySchema, CorrectionEntrySchema

logger = logging.getLogger(__name__)

def skip_if_terminal_error(item: Item, stage_name: str) -> bool:
    """
    Verifica si un ítem ya está en un estado de error terminal y, si es así,
    añade una entrada de auditoría y retorna True (indica que debe ser saltado).
    """
    terminal_statuses = [
        "fatal_error",
        "generation_failed",
        "llm_generation_failed",
        "generation_validation_failed",
        "generation_failed_mismatch",
        "failed_hard_validation",
        "failed_logic_validation_after_retries",
        "failed_policy_validation_after_retries",
        "refinement_failed",
        "refinement_parsing_failed",
        "refinement_unexpected_error",
        "final_failed_validation",
        "llm_finalization_failed",
        "finalization_failed_no_result",
        "finalization_failed_mismatch",
        "persistence_failed_db_error",
        "persistence_failed_unexpected_error",
        "fatal_error_on_persist_stage"
    ]
    if item.status in terminal_statuses:
        add_audit_entry(
            item=item,
            stage_name=stage_name,
            summary=f"Saltado: ítem ya en estado de error terminal previo ({item.status})."
        )
        logger.debug(f"Skipping item {item.temp_id} in {stage_name} due to prior terminal error status: {item.status}")
        return True
    return False

def add_audit_entry(
    item: Item,
    stage_name: str,
    summary: str,
    corrections: Optional[List[CorrectionEntrySchema]] = None,
    errors_reported: Optional[List[ReportEntrySchema]] = None
) -> None:
    """
    Añade una entrada de auditoría al ítem.
    """
    if corrections is None:
        corrections = []
    if errors_reported is None:
        errors_reported = []

    item.audits.append(
        AuditEntrySchema(
            stage=stage_name,
            summary=summary,
            corrections=corrections
        )
    )
    logger.debug(f"Audit for item {item.temp_id} in {stage_name}: {summary}")

def handle_prompt_not_found_error(items: List[Item], stage_name: str, prompt_name: str, e: FileNotFoundError) -> List[Item]:
    """
    Maneja el error de prompt no encontrado, marca los ítems como fatales y audita.
    """
    error_msg = f"Prompt '{prompt_name}' not found for stage '{stage_name}': {e}"
    for item in items:
        item.status = "fatal_error"
        item.errors.append(
            ReportEntrySchema(
                code="PROMPT_NOT_FOUND",
                message=error_msg,
                field="prompt_name",
                severity="error"
            )
        )
        add_audit_entry(
            item=item,
            stage_name=stage_name,
            summary=f"Error fatal: El archivo de prompt '{prompt_name}' no fue encontrado."
        )
    logger.error(error_msg)
    return items

async def handle_llm_call_and_parse_errors(
    item: Item, # Recibe un item para registrar los tokens y auditoría de la llamada
    stage_name: str,
    llm_errors_from_call_parse: List[ReportEntrySchema],
    llm_fail_status: str,
    summary_prefix: str
) -> bool:
    """
    Maneja errores de llamada o parseo de la utilidad LLM.
    Actualiza el estado del ítem, extiende errores y añade una auditoría.
    Retorna True si hubo errores y el procesamiento debe continuar, False si no hay errores.
    """
    if llm_errors_from_call_parse:
        # Si el ítem ya es fatal por prompt no encontrado (manejado por handle_prompt_not_found_error)
        # no sobrescribimos el estado, solo extendemos los errores.
        if item.status not in ["fatal_error"]:
            item.status = llm_fail_status
        item.errors.extend(llm_errors_from_call_parse)
        add_audit_entry(
            item=item,
            stage_name=stage_name,
            summary=f"{summary_prefix}. Errores: {', '.join([e.code for e in llm_errors_from_call_parse])}"
        )
        logger.error(f"LLM call or parsing failed for item {item.temp_id} in {stage_name}. Errors: {llm_errors_from_call_parse}")
        return True
    return False

def handle_missing_payload(item: Item, stage_name: str, error_code: str, message: str, status: str, summary: str) -> None:
    """
    Maneja el caso donde el payload del ítem está ausente para una etapa.
    """
    item.status = status
    item.errors.append(
        ReportEntrySchema(
            code=error_code,
            message=message,
            severity="error"
        )
    )
    add_audit_entry(
        item=item,
        stage_name=stage_name,
        summary=summary
    )
    logger.warning(f"Item {item.temp_id} skipped in {stage_name}: {summary}.")

def clean_item_llm_errors(item: Item) -> None:
    """
    Limpia los errores y advertencias del ítem que son generados por llamadas/parseo de LLM.
    """
    item.errors = [
        err for err in item.errors
        if not (
            err.code.startswith("LLM_CALL_FAILED") or
            err.code.startswith("LLM_PARSE_VALIDATION_ERROR") or
            err.code.startswith("UNEXPECTED_LLM_PROCESSING_ERROR") or
            err.code.startswith("NO_LLM_") # Códigos como NO_LLM_RESULT, NO_LLM_LOGIC_RESULT, NO_LLM_POLICY_RESULT
        )
    ]
    item.warnings = [
        warn for warn in item.warnings
        if not (
            warn.code.startswith("LLM_CALL_FAILED") or
            warn.code.startswith("LLM_PARSE_VALIDATION_ERROR") or
            warn.code.startswith("UNEXPECTED_LLM_PROCESSING_ERROR") or
            warn.code.startswith("NO_LLM_")
        )
    ]

def clean_specific_errors(item: Item, fixed_codes: set) -> None:
    """
    Limpia los errores y advertencias de un ítem cuyos códigos han sido corregidos.
    """
    item.errors = [err for err in item.errors if err.code not in fixed_codes]
    item.warnings = [warn for warn in item.warnings if warn.code not in fixed_codes]

def update_item_status_and_audit(
    item: Item,
    stage_name: str,
    new_status: str,
    summary_msg: str,
    audit_corrections: Optional[List[CorrectionEntrySchema]] = None
) -> None:
    """
    Actualiza el estado del ítem y añade una entrada de auditoría genérica.
    """
    item.status = new_status
    add_audit_entry(
        item=item,
        stage_name=stage_name,
        summary=summary_msg,
        corrections=audit_corrections
    )
    logger.info(f"Item {item.temp_id} in {stage_name} status updated to: {item.status}. Summary: {summary_msg}")

def check_and_handle_batch_llm_errors(
    items: List[Item],
    stage_name: str,
    llm_errors_from_call_parse: List[ReportEntrySchema],
    summary_prefix: str,
    llm_fail_status: str
) -> bool:
    """
    Gestiona errores que afectan a todo el lote de ítems procesado por una llamada LLM.
    Propaga los errores y auditorías a cada ítem del lote.
    Retorna True si hubo errores de lote que deben detener el procesamiento adicional.
    """
    if llm_errors_from_call_parse:
        for item in items:
            if item.status not in ["fatal_error"]: # No sobrescribir errores fatales pre-existentes (ej. prompt no encontrado)
                item.status = llm_fail_status # Ejemplo: "generation_failed"
                item.errors.extend(llm_errors_from_call_parse)
                add_audit_entry(
                    item=item,
                    stage_name=stage_name,
                    summary=f"{summary_prefix}. Detalles: {llm_errors_from_call_parse[0].message[:200]}"
                )
        logger.error(f"Batch LLM processing failed for stage '{stage_name}'. Errors: {llm_errors_from_call_parse}")
        return True
    return False

def check_and_handle_llm_response_format_error(
    items: List[Item],
    stage_name: str,
    generated_payloads_list_raw: Any,
    expected_type: Type[List[BaseModel]],
    error_code: str,
    message: str,
    llm_fail_status: str
) -> bool:
    """
    Verifica si la respuesta global del LLM es del tipo esperado (ej., una lista de ítems)
    y maneja el error si no lo es.
    Retorna True si hubo un error de formato, False en caso contrario.
    """
    if not isinstance(generated_payloads_list_raw, expected_type):
        error_msg = message
        for item in items:
            if item.status not in ["fatal_error"]:
                item.status = llm_fail_status
                item.errors.append(
                    ReportEntrySchema(
                        code=error_code,
                        message=error_msg,
                        field="llm_response",
                        severity="error"
                    )
                )
                add_audit_entry(
                    item=item,
                    stage_name=stage_name,
                    summary=f"Fallo de formato de respuesta del LLM. Detalles: {error_msg}"
                )
        logger.error(error_msg)
        return True
    return False

def check_and_handle_llm_item_count_mismatch(
    items: List[Item],
    stage_name: str,
    generated_payloads_list_raw: List[BaseModel],
    error_code: str,
    message: str,
    llm_fail_status: str
) -> bool:
    """
    Verifica si la cantidad de ítems generados por el LLM coincide con la cantidad solicitada
    y maneja el error si no lo es.
    Retorna True si hubo un error de conteo, False en caso contrario.
    """
    if len(generated_payloads_list_raw) != len(items):
        error_msg = message
        for item in items:
            if item.status not in ["fatal_error"]:
                item.status = llm_fail_status
                item.errors.append(
                    ReportEntrySchema(
                        code=error_code,
                        message=error_msg,
                        field="llm_response",
                        severity="error"
                    )
                )
                add_audit_entry(
                    item=item,
                    stage_name=stage_name,
                    summary=f"Conteo de ítems generado por LLM no coincide. Detalles: {error_msg}"
                )
        logger.error(error_msg)
        return True
    return False
