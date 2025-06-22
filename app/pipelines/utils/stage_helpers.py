# app/pipelines/utils/stage_helpers.py

import logging
from typing import List, Optional
from uuid import UUID, uuid4 # Necesario para UUIDs en handle_item_id_mismatch_refinement y AuditEntrySchema

from app.schemas.models import Item
from app.schemas.item_schemas import AuditEntrySchema, ReportEntrySchema, CorrectionEntrySchema, ItemPayloadSchema, UserGenerateParams, MetadataSchema, OpcionSchema, RecursoVisualSchema

logger = logging.getLogger(__name__)

# --- Simplified: only checks for the ultimate fatal error ---
def skip_if_terminal_error(item: Item, stage_name: str) -> bool:
    """
    Verifica si un ítem ya está en un estado fatal y, si es así,
    añade una entrada de auditoría y retorna True (indica que debe ser saltado).
    Los estados de agotamiento de intentos son gestionados por el runner.
    """
    if item.status == "fatal_error": # Only check for the most generic fatal state
        add_audit_entry(
            item=item,
            stage_name=stage_name,
            summary=f"Saltado: ítem ya en estado fatal ('{item.status}')."
        )
        logger.debug(f"Skipping item {item.temp_id} in {stage_name} due to prior fatal status.")
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

# --- Simplified: consolidate LLM call/parse errors into a single handler if needed ---
# async def handle_llm_call_and_parse_errors(...) - REMOVED / CONSOLIDATED

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
            err.code.startswith("NO_LLM_")
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

# --- Simplified: consolidate batch error handlers ---
# def check_and_handle_batch_llm_errors(...) - REMOVED / CONSOLIDATED
# def check_and_handle_llm_response_format_error(...) - REMOVED / CONSOLIDATED
# def check_and_handle_llm_item_count_mismatch(...) - REMOVED / CONSOLIDATED

def handle_item_id_mismatch_refinement(
    item: Item,
    stage_name: str,
    expected_id: UUID,
    received_id: UUID,
    status_on_fail: str,
    summary_msg: str
) -> None:
    """
    Maneja el error de item_id no coincidente en la respuesta de refinamiento del LLM.
    """
    error_msg = f"Mismatched item_id in LLM response. Expected {expected_id}, got {received_id}."
    item.errors.append(
        ReportEntrySchema(
            code="ITEM_ID_MISMATCH_REFINEMENT",
            message=error_msg,
            field="item_id",
            severity="error"
        )
    )
    update_item_status_and_audit(
        item=item,
        stage_name=stage_name,
        new_status=status_on_fail,
        summary_msg=summary_msg
    )
    logger.error(f"Item ID mismatched for item {item.temp_id} in {stage_name}: {error_msg}")

def initialize_items_for_pipeline(user_params: UserGenerateParams) -> List[Item]:
    """
    Inicializa una lista de objetos Item con payloads dummy pero válidos
    basándose en los user_params.
    """
    items: List[Item] = []
    # Asegúrate de que UserGenerateParams tiene todos los campos necesarios para MetadataSchema y el ItemPayloadSchema base
    # (habilidad, referencia_curricular, contexto_regional, etc.)
    for _ in range(user_params.n_items):
        item_metadata = MetadataSchema(
            idioma_item=user_params.idioma_item,
            area=user_params.area,
            asignatura=user_params.asignatura,
            tema=user_params.tema,
            contexto_regional=user_params.contexto_regional,
            nivel_destinatario=user_params.nivel_destinatario,
            nivel_cognitivo=user_params.nivel_cognitivo,
            dificultad_prevista=user_params.dificultad_prevista,
            parametro_irt_b=user_params.parametro_irt_b,
            referencia_curricular=user_params.referencia_curricular,
            habilidad_evaluable=user_params.habilidad,
        )

        recurso_visual_obj = None
        if user_params.recurso_visual:
            try:
                recurso_visual_obj = RecursoVisualSchema.model_validate(user_params.recurso_visual)
            except Exception as e:
                logger.warning(f"Error validating recurso_visual from user_params during item initialization: {e}. Setting to None.")

        dummy_payload = ItemPayloadSchema(
            item_id=uuid4(),
            metadata=item_metadata,
            enunciado_pregunta="Pregunta inicial (será reemplazada por el LLM)",
            opciones=[
                OpcionSchema(id="a", texto="Opción A", es_correcta=True, justificacion="Justificación A"),
                OpcionSchema(id="b", texto="Opción B", es_correcta=False, justificacion="Justificación B"),
                OpcionSchema(id="c", texto="Opción C", es_correcta=False, justificacion="Justificación C"),
            ],
            respuesta_correcta_id="a",
            tipo_reactivo=user_params.tipo_reactivo,
            fragmento_contexto=user_params.fragmento_contexto,
            recurso_visual=recurso_visual_obj,
            estimulo_compartido=user_params.estimulo_compartido,
            testlet_id=user_params.testlet_id,
        )

        items.append(Item(payload=dummy_payload))
    return items
