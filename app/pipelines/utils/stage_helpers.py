# app/pipelines/utils/stage_helpers.py

from __future__ import annotations
import uuid
from datetime import datetime

from app.schemas.models import Item, ItemStatus
from app.schemas.item_schemas import (
    AuditEntrySchema,
    ReportEntrySchema,
    CorrectionSchema,
    ItemGenerationParams,
    ValidationResultSchema
)
from app.core.log import logger

# ---------------------------------------------------------------------------
# Funciones Helper Esenciales para el Pipeline
# ---------------------------------------------------------------------------

def skip_if_terminal_error(item: Item, stage_name: str) -> bool:
    """
    Verifica si un ítem ya está en un estado fatal y, si es así,
    añade una entrada de auditoría y retorna True para omitirlo.
    """
    if item.status == "fatal_error":
        # Se corrige el f-string que no tenía placeholders
        summary = f"Saltado: Ítem ya en estado fatal ('{item.status}')."
        add_audit_entry(
            item=item,
            stage_name=stage_name,
            status=ItemStatus.FATAL,
            summary=summary
        )
        return True
    return False

def handle_missing_payload(item: Item, stage_name: str):
    """
    Maneja el caso donde el payload del ítem está ausente, marcándolo como fatal.
    """
    summary = "Error Crítico: El payload del ítem está ausente y es requerido para esta etapa."
    finding = ReportEntrySchema(code="E952_NO_PAYLOAD", message=summary, severity="fatal")
    item.findings.append(finding)
    update_item_status_and_audit(item, stage_name, ItemStatus.FATAL, summary)
    logger.warning(f"Item {item.temp_id} marcado como FATAL en {stage_name}: {summary}")

def initialize_items_for_pipeline(params: Dict[str, Any]) -> List[Item]:
    """
    Inicializa una lista de objetos Item para ser procesados por el pipeline.
    """
    try:
        gen_params = ItemGenerationParams.model_validate(params)
    except Exception as e:
        logger.error(f"Error al validar los parámetros de generación: {e}", exc_info=True)
        return []

    items_to_process: List[Item] = []
    batch_id = str(uuid.uuid4())
    item_ids_to_use = []

    lote_params = gen_params.lote
    if lote_params:
        item_ids_to_use = lote_params.get("item_ids_a_usar", [])

    if not item_ids_to_use:
        item_ids_to_use = [str(uuid.uuid4()) for _ in range(gen_params.n_items)]

    specs_por_item = lote_params.get("especificaciones_por_item", []) if lote_params else []

    for i in range(gen_params.n_items):
        item_id = item_ids_to_use[i]
        local_specs = next((spec for spec in specs_por_item if spec.get("item_id") == item_id), {})
        final_params = gen_params.model_copy(deep=True)

        if local_specs:
            if "objetivo_aprendizaje" in local_specs:
                final_params.objetivo_aprendizaje = local_specs["objetivo_aprendizaje"]
            if "audiencia" in local_specs and isinstance(local_specs["audiencia"], dict):
                final_params.audiencia.nivel_educativo = local_specs["audiencia"].get("nivel_educativo", final_params.audiencia.nivel_educativo)
                final_params.audiencia.dificultad_esperada = local_specs["audiencia"].get("dificultad_esperada", final_params.audiencia.dificultad_esperada)
            if "formato" in local_specs and isinstance(local_specs["formato"], dict):
                final_params.formato.tipo_reactivo = local_specs["formato"].get("tipo_reactivo", final_params.formato.tipo_reactivo)
                final_params.formato.numero_opciones = local_specs["formato"].get("numero_opciones", final_params.formato.numero_opciones)

        new_item = Item(
            item_id=item_id,
            batch_id=batch_id,
            status=ItemStatus.PENDING.value,
            generation_params=final_params.model_dump(mode='json'),
            payload=None,
            findings=[],
            audits=[]
        )
        items_to_process.append(new_item)

    return items_to_process

def add_audit_entry(item: Item, stage_name: str, status: ItemStatus, summary: str, corrections: Optional[List[CorrectionSchema]] = None):
    """Añade una entrada de auditoría al log del ítem."""
    audit_entry = AuditEntrySchema(
        stage=stage_name,
        timestamp=datetime.utcnow(),
        summary=summary,
        corrections=corrections or []
    )
    item.audits.append(audit_entry)

def update_item_status_and_audit(item: Item, stage_name: str, status: ItemStatus, summary: str, corrections: Optional[List[CorrectionSchema]] = None):
    """Actualiza el estado de un ítem y añade una entrada de auditoría."""
    status_value = status.value if isinstance(status, ItemStatus) else str(status)
    item.status = f"{stage_name}.{status_value}"
    add_audit_entry(item, stage_name, status, summary, corrections)

def clean_specific_errors(item: Item, error_codes_to_remove: set[str]):
    """Elimina findings específicos de un ítem."""
    item.findings = [f for f in item.findings if f.code not in error_codes_to_remove]

def get_error_message_from_validation_result(result: ValidationResultSchema, context: str) -> str:
    """Genera un mensaje de resumen a partir de un resultado de validación."""
    error_codes = ", ".join([f.code for f in result.findings])
    return f"Validación de {context}: FALLÓ con los siguientes códigos: {error_codes}"

def handle_item_id_mismatch_refinement(item: Item, stage_name: str, expected_id: str, actual_id: str) -> bool:
    """Maneja el caso de un mismatch de ID en una etapa de refinamiento."""
    if actual_id != expected_id:
        msg = f"Error Crítico: El ID del ítem en la respuesta del LLM ('{actual_id}') no coincide con el esperado ('{expected_id}')."
        update_item_status_and_audit(item, stage_name, ItemStatus.FATAL, msg)
        return True
    return False
