# Archivo nuevo: app/pipelines/logic_blocks.py

import json
from typing import Dict, Any, List
from app.schemas.models import Item
from app.schemas.item_schemas import ValidationResultSchema, RefinementResultSchema, ReportEntrySchema
from app.pipelines.utils.stage_helpers import update_item_status_and_audit, clean_specific_errors

# --- Bloques de Lógica de PREPARACIÓN de Input para el LLM ---

def prepare_validation_input(item: Item, **kwargs) -> str:
    """Prepara el input para una validación estándar. Envía solo el payload."""
    return item.payload.model_dump_json(indent=2)

def prepare_refinement_input(item: Item, **kwargs) -> str:
    """Prepara el input para un refinamiento basado en errores previos."""
    problemas: List[Dict[str, Any]] = [err.model_dump() for err in item.errors if err.severity == 'error']
    payload = {"item": item.payload.model_dump(), "problems": problemas}
    return json.dumps(payload, indent=2, ensure_ascii=False)

def prepare_correction_input(item: Item, **kwargs) -> str:
    """Prepara el input para una corrección directa (sin errores previos)."""
    payload = {"item": item.payload.model_dump(), "problems": []}
    return json.dumps(payload, indent=2, ensure_ascii=False)


# --- Bloques de Lógica de APLICACIÓN de Resultados del LLM ---

async def apply_validation_result(item: Item, result: ValidationResultSchema, stage_name: str, **kwargs):
    """Aplica el resultado de una validación estándar."""
    if result.is_valid:
        update_item_status_and_audit(item, stage_name, f"{stage_name}.success", "Validation passed.")
    else:
        storage_location = kwargs.get("store_findings_in", "warnings")
        storage: List[ReportEntrySchema] = getattr(item, storage_location)
        storage.extend(result.findings)
        summary = f"Validation failed. {len(result.findings)} issues found: {[f.code for f in result.findings]}"
        update_item_status_and_audit(item, stage_name, f"{stage_name}.fail", summary)

async def apply_refinement_result(item: Item, result: RefinementResultSchema, stage_name: str, **kwargs):
    """Aplica el resultado de un refinamiento o corrección estándar."""
    item.payload = result.item_refinado
    fixed_codes = {c.error_code for c in result.correcciones_realizadas if c.error_code}
    if fixed_codes:
        clean_specific_errors(item, fixed_codes)
    summary = f"Refinement applied. {len(fixed_codes)} issues reported as fixed."
    update_item_status_and_audit(item, stage_name, f"{stage_name}.success", summary)


# --- REGISTRO CENTRAL DE BLOQUES DE LÓGICA ---
# El motor usará este diccionario para componer su comportamiento.
LOGIC_BLOCKS: Dict[str, Dict[str, Any]] = {
    "prepare": {
        "validation": prepare_validation_input,
        "refinement": prepare_refinement_input,
        "correction": prepare_correction_input,
    },
    "apply": {
        "validation": apply_validation_result,
        "refinement": apply_refinement_result,
    },
    "schema": {
        "validation": ValidationResultSchema,
        "refinement": RefinementResultSchema
    }
}
