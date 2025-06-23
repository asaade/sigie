# Archivo completo: app/pipelines/utils/stage_helpers.py

import asyncio
import logging
from typing import List, Optional, Callable, Coroutine, Any
from uuid import UUID, uuid4

from app.schemas.models import Item
from app.schemas.item_schemas import AuditEntrySchema, ReportEntrySchema, CorrectionEntrySchema, ItemPayloadSchema, UserGenerateParams, MetadataSchema, OpcionSchema, RecursoVisualSchema

logger = logging.getLogger(__name__)


def skip_if_terminal_error(item: Item, stage_name: str) -> bool:
    if item.status == "fatal_error":
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

def handle_missing_payload(item: Item, stage_name: str, error_code: str, message: str, status: str, summary: str) -> None:
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
    Limpia los hallazgos (findings) de un ítem cuyos códigos han sido corregidos.
    """
    # ▼▼▼ LÓGICA MODIFICADA PARA USAR 'findings' ▼▼▼
    original_count = len(item.findings)
    item.findings = [f for f in item.findings if f.code not in fixed_codes]
    if original_count > len(item.findings):
        logger.debug(f"Removed {original_count - len(item.findings)} fixed findings for item {item.temp_id}.")

def update_item_status_and_audit(
    item: Item,
    stage_name: str,
    new_status: str,
    summary_msg: str,
    audit_corrections: Optional[List[CorrectionEntrySchema]] = None
) -> None:
    item.status = new_status
    add_audit_entry(
        item=item,
        stage_name=stage_name,
        summary=summary_msg,
        corrections=audit_corrections
    )
    logger.info(f"Item {item.temp_id} in {stage_name} status updated to: {item.status}. Summary: {summary_msg}")

def handle_item_id_mismatch_refinement(
    item: Item,
    stage_name: str,
    expected_id: UUID,
    received_id: UUID,
    status_on_fail: str,
    summary_msg: str
) -> None:
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
    items: List[Item] = []
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

# ▼▼▼ NUEVA FUNCIÓN AÑADIDA ▼▼▼
async def process_items_concurrently(
    items: List[Item],
    processing_func: Callable[[Item, dict, Any], Coroutine[Any, Any, None]],
    ctx: dict,
    **kwargs: Any,
):
    """
    Filtra ítems por estado (si se especifica) y los procesa de forma concurrente.
    """
    listen_to_status = kwargs.get("listen_to_status")

    if listen_to_status:
        items_to_process = [
            item for item in items if item.status == listen_to_status
        ]
        logger.info(f"Found {len(items_to_process)} items with status '{listen_to_status}' to process.")
    else:
        # Si no se especifica un estado, se procesan todos los que no estén en un estado final de error.
        items_to_process = [
            item for item in items if "fail" not in item.status and "error" not in item.status and item.status != "logic_validated"
        ]
        logger.info(f"Processing {len(items_to_process)} items that are not in a final error state.")

    tasks = [
        processing_func(item, ctx, **kwargs) for item in items_to_process
    ]

    if tasks:
        await asyncio.gather(*tasks)
