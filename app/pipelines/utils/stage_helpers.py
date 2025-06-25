# app/pipelines/utils/stage_helpers.py

import logging
from typing import List, Optional # Dict, Any, Type, Tuple ya no son necesarios
from uuid import UUID, uuid4

from app.schemas.models import Item
# AuditEntrySchema, ReportEntrySchema, CorrectionEntrySchema, ItemPayloadSchema, UserGenerateParams, MetadataSchema, OpcionSchema, TipoReactivo, RecursoVisualSchema
# Se importan explícitamente solo los que se usan como tipos a nivel superior o en initialize_items_for_pipeline
from app.schemas.item_schemas import AuditEntrySchema, ReportEntrySchema, CorrectionEntrySchema, ItemPayloadSchema, UserGenerateParams, MetadataSchema, OpcionSchema, RecursoVisualSchema # TipoReactivo eliminado

# BaseModel no es necesario aquí si se usa Type[RecursoVisualSchema] en lugar de Type[BaseModel]
# from pydantic import BaseModel

logger = logging.getLogger(__name__)

def skip_if_terminal_error(item: Item, stage_name: str) -> bool:
    """
    Verifica si un ítem ya está en un estado fatal y, si es así,
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
                message=error_msg,
                field="prompt_name",
                severity="error"
            )
        )
    logger.error(error_msg)
    return items

def handle_missing_payload(item: Item, stage_name: str, error_code: str, message: str, status: str, summary: str) -> None:
    """Maneja el caso donde el payload del ítem está ausente para una etapa."""
    item.findings.append(
        ReportEntrySchema(code=error_code, message=message, severity="error")
    )
    update_item_status_and_audit(item, stage_name, status, summary)
    logger.warning(f"Item {item.temp_id} skipped in {stage_name}: {summary}.")

def handle_item_id_mismatch_refinement(
    item: Item,
    stage_name: str,
    expected_id: UUID,
    received_id: UUID,
    status_on_fail: str,
    summary_msg: str
) -> None:
    """Maneja el error de item_id no coincidente en la respuesta de refinamiento del LLM."""
    error_msg = f"Mismatched item_id in LLM response. Expected {expected_id}, got {received_id}."
    item.findings.append(
        ReportEntrySchema(code="ITEM_ID_MISMATCH", message=error_msg, field="item_id", severity="error")
    )
    update_item_status_and_audit(item, stage_name, status_on_fail, summary_msg)
    logger.error(f"Item ID mismatched for item {item.temp_id} in {stage_name}: {error_msg}")


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
    """Limpia los hallazgos de un ítem cuyos códigos han sido corregidos."""
    original_count = len(item.findings)
    item.findings = [f for f in item.findings if f.code not in fixed_codes]
    if original_count > len(item.findings):
        logger.debug(f"Removed {original_count - len(item.findings)} fixed findings for item {item.temp_id}.")

def initialize_items_for_pipeline(user_params: UserGenerateParams) -> List[Item]:
    """
    Inicializa una lista de objetos Item con payloads dummy pero válidos
    basándose en los user_params.
    """
    items: List[Item] = []

    try:
        # UserGenerateParams es un BaseModel, y UserGenerateParams.model_validate
        # devolverá una instancia de UserGenerateParams. No se necesita .model_dump() aquí.
        # Si UserGenerateParams ya fue validado en el router, simplemente lo usamos.
        validated_user_params = user_params # Ya viene validado desde el router
        n_items = validated_user_params.n_items
    except Exception as e:
        logger.error(f"Error validating UserGenerateParams during pipeline initialization: {e}", exc_info=True)
        return []

    for _ in range(n_items):
        item_metadata = MetadataSchema(
            idioma_item=validated_user_params.idioma_item,
            area=validated_user_params.area,
            asignatura=validated_user_params.asignatura,
            tema=validated_user_params.tema,
            contexto_regional=validated_user_params.contexto_regional,
            nivel_destinatario=validated_user_params.nivel_destinatario,
            nivel_cognitivo=validated_user_params.nivel_cognitivo,
            dificultad_prevista=validated_user_params.dificultad_prevista,
            referencia_curricular=validated_user_params.referencia_curricular,
            habilidad_evaluable=validated_user_params.habilidad,
        )

        recurso_visual_obj = None
        if validated_user_params.recurso_visual:
            try:
                # model_validate en un Dict exige que el Dict tenga el formato exacto del esquema.
                # Si el user_params.recurso_visual es ya un RecursoVisualSchema (por validación previa), usarlo directamente.
                # Si es un dict, validarlo.
                if isinstance(validated_user_params.recurso_visual, dict):
                    recurso_visual_obj = RecursoVisualSchema.model_validate(validated_user_params.recurso_visual)
                else: # Ya es RecursoVisualSchema object
                    recurso_visual_obj = validated_user_params.recurso_visual
            except Exception as e:
                logger.warning(f"Error validating recurso_visual from user_params during item initialization: {e}. Setting to None.")

        dummy_payload = ItemPayloadSchema(
            item_id=uuid4(),
            metadata=item_metadata,
            enunciado_pregunta="[DUMMY] Enunciado inicial. Será reemplazado por el LLM.",
            opciones=[
                OpcionSchema(id="a", texto="[DUMMY] Opción A", es_correcta=True, justificacion="[DUMMY] Justificación A"),
                OpcionSchema(id="b", texto="[DUMMY] Opción B", es_correcta=False, justificacion="[DUMMY] Justificación B"),
                OpcionSchema(id="c", texto="[DUMMY] Opción C", es_correcta=False, justificacion="[DUMMY] Justificación C"),
            ],
            respuesta_correcta_id="a",
            tipo_reactivo=validated_user_params.tipo_reactivo,
            fragmento_contexto=validated_user_params.fragmento_contexto,
            recurso_visual=recurso_visual_obj,
            estimulo_compartido=validated_user_params.estimulo_compartido,
            testlet_id=validated_user_params.testlet_id,
        )

        items.append(Item(payload=dummy_payload))

    logger.info(f"Initialized {len(items)} items for pipeline execution based on user parameters.")
    return items
