# app/pipelines/utils/stage_helpers.py

import logging
from typing import List, Optional
from uuid import UUID, uuid4
from datetime import datetime

from app.schemas.models import Item
from app.schemas.item_schemas import AuditEntrySchema, ReportEntrySchema, CorrectionEntrySchema, ItemPayloadSchema, UserGenerateParams, MetadataSchema, OpcionSchema


logger = logging.getLogger(__name__)

def skip_if_terminal_error(item: Item, stage_name: str) -> bool:
    """
    Verifica si un ítem ya está en un estado fatal_error global y, si es así,
    añade una entrada de auditoría y retorna True para omitirlo.
    """
    if item.status == "fatal_error":
        add_audit_entry(
            item=item,
            stage_name=stage_name,
            summary=f"Saltado: Ítem ya en estado fatal ('{item.status}')."
        )
        logger.debug(f"Skipping item {item.temp_id} in {stage_name} due to prior fatal status.")
        return True
    return False

def add_audit_entry(
    item: Item,
    stage_name: str,
    summary: str,
    corrections: Optional[List[CorrectionEntrySchema]] = None
) -> None:
    """Añade una entrada de auditoría al ítem."""
    item.audits.append(
        AuditEntrySchema(
            stage=stage_name,
            timestamp=datetime.now(),
            summary=summary,
            corrections=corrections or []
        )
    )
    logger.debug(f"Audit for item {item.temp_id} in {stage_name}: {summary}")

def update_item_status_and_audit(
    item: Item,
    stage_name: str,
    new_status: str,
    summary_msg: str,
    audit_corrections: Optional[List[CorrectionEntrySchema]] = None
) -> None:
    """Actualiza el estado del ítem y añade una entrada de auditoría."""
    item.status = new_status
    add_audit_entry(
        item=item,
        stage_name=stage_name,
        summary=summary_msg,
        corrections=audit_corrections
    )
    logger.info(f"Item {item.temp_id} in {stage_name} status updated to: {item.status}. Summary: {summary_msg}")


def handle_prompt_not_found_error(items: List[Item], stage_name: str, prompt_name: str, e: FileNotFoundError) -> List[Item]:
    """Maneja el error de prompt no encontrado, marca los ítems como fatales."""
    error_msg = f"Prompt '{prompt_name}' not found for stage '{stage_name}': {e}"
    for item in items:
        update_item_status_and_audit(
            item=item,
            stage_name=stage_name,
            new_status="fatal_error",
            summary_msg=f"Error fatal: Archivo de prompt '{prompt_name}' no encontrado."
        )
        item.findings.append(
            ReportEntrySchema(
                code="PROMPT_NOT_FOUND",
                message=error_msg[:900],
                field="prompt_name",
                severity="fatal" # MODIFICADO: A fatal
            )
        )
    logger.error(error_msg)
    return items

def handle_missing_payload(item: Item, stage_name: str, error_code: str, message: str, status: str, summary: str) -> None:
    """Maneja el caso donde el payload del ítem está ausente para una etapa."""
    item.findings.append(
        ReportEntrySchema(code=error_code, message=message, severity="fatal") # MODIFICADO: A fatal
    )
    update_item_status_and_audit(item, stage_name, "fatal_error", summary) # MODIFICADO: A fatal_error
    logger.warning(f"Item {item.temp_id} skipped in {stage_name}: {summary}.")

def handle_item_id_mismatch_refinement(
    item: Item,
    stage_name: str,
    expected_id: UUID,
    received_id: UUID,
    status_on_fail: str, # Este parámetro puede volverse redundante si siempre es fatal_error
    summary_msg: str
) -> None:
    """Maneja el error de item_id no coincidente en la respuesta de refinamiento del LLM."""
    error_msg = f"Mismatched item_id in LLM response. Expected {expected_id}, got {received_id}."
    item.findings.append(
        ReportEntrySchema(code="ITEM_ID_MISMATCH", message=error_msg[:900], field="item_id", severity="fatal") # MODIFICADO: A fatal
    )
    update_item_status_and_audit(item, stage_name, "fatal_error", summary_msg) # MODIFICADO: A fatal_error
    logger.error(f"Item ID mismatched for item {item.temp_id} in {stage_name}: {error_msg}")


def clean_item_llm_errors(item: Item) -> None:
    """
    Limpia los hallazgos del ítem que son generados por fallos de llamadas/parseo de LLM.
    Asume que todos los hallazgos de LLM están en item.findings.
    """
    item.findings = [
        f for f in item.findings
        if not (
            f.code.startswith("LLM_CALL_FAILED") or
            f.code.startswith("LLM_PARSE_VALIDATION_ERROR") or
            f.code.startswith("UNEXPECTED_LLM_PROCESSING_ERROR") or
            f.code.startswith("NO_LLM_")
        )
    ]

def clean_specific_errors(item: Item, fixed_codes: set) -> None:
    """Limpia los hallazgos de un ítem cuyos códigos han sido corregidos."""
    original_count = len(item.findings)
    item.findings = [f for f in item.findings if f.code not in fixed_codes]
    if original_count > len(item.findings):
        logger.debug(f"Removed {original_count - len(item.findings)} fixed findings for item {item.temp_id}.")

def initialize_items_for_pipeline(user_params: UserGenerateParams) -> List[Item]:
    """
    Inicializa una lista de objetos Item basados en los parámetros de la solicitud del usuario.
    """
    items: List[Item] = []
    n_items = user_params.n_items

    # Asegurarse de que item_ids_a_usar sea una lista, incluso si no se proporciona explícitamente para cada item
    # Si item_ids_a_usar viene en user_params, usarlo; de lo contrario, generar IDs temporales
    item_ids_to_use = user_params.item_ids_a_usar if user_params.item_ids_a_usar else [str(uuid4()) for _ in range(n_items)]

    for i in range(n_items):
        current_item_id = item_ids_to_use[i] if i < len(item_ids_to_use) else str(uuid4())
        current_temp_id = str(uuid4()) # Generar un temp_id único para cada Item

        # Crear un payload dummy inicial para satisfacer el esquema Pydantic si es necesario
        # Usar un payload válido pero que será reemplazado por el generador
        dummy_payload = ItemPayloadSchema(
            item_id=UUID(current_item_id), # Usar el item_id generado o provisto
            metadata=MetadataSchema(
                area=user_params.area,
                asignatura=user_params.asignatura,
                tema=user_params.tema,
                nivel_destinatario=user_params.nivel_destinatario,
                nivel_cognitivo=user_params.nivel_cognitivo,
                dificultad_prevista=user_params.dificultad_prevista,
                errores_comunes=["dummy error 1", "dummy error 2"], # Requiere 2 errores comunes
                fecha_creacion=datetime.now().isoformat().split('T')[0] # Fecha actual en YYYY-MM-DD
            ),
            tipo_reactivo=user_params.tipo_reactivo,
            enunciado_pregunta="[DUMMY] Enunciado inicial. Será reemplazado por el LLM.",
            opciones=[
                OpcionSchema(id="a", texto="[DUMMY] Opción A", es_correcta=True, justificacion="[DUMMY] Justificación A"),
                OpcionSchema(id="b", texto="[DUMMY] Opción B", es_correcta=False, justificacion="[DUMMY] Justificación B"),
                OpcionSchema(id="c", texto="[DUMMY] Opción C", es_correcta=False, justificacion="[DUMMY] Justificación C")
            ],
            respuesta_correcta_id="a"
        )

        # Al construir el objeto Item, pasa el temp_id y item_id
        items.append(Item(
            temp_id=UUID(current_temp_id), # Asegurarse de pasar temp_id aquí
            item_id=UUID(current_item_id), # Asegurarse de pasar item_id aquí
            payload=dummy_payload # Pasar el payload dummy inicial
        ))

    logger.info(f"Initialized {len(items)} items for pipeline execution based on user parameters.")
    return items
