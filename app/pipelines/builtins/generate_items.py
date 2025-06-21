# app/pipelines/builtins/generate_items.py

from __future__ import annotations
import logging
import json # Re-importado: es necesario para json.dumps
from typing import List, Dict, Any
from uuid import uuid4 # Necesario para inicializar item_id

from ..registry import register
# Eliminada la importación directa de _helpers para add_tokens, ahora a través de llm_utils
from app.schemas.models import Item
# Eliminadas generate_response, LLMResponse, load_prompt - encapsulados en llm_utils
from app.prompts import load_prompt # Mantenemos para la verificación inicial de prompt_name
# Eliminada AuditEntrySchema: ahora encapsulada en add_audit_entry
from app.schemas.item_schemas import ItemPayloadSchema, UserGenerateParams, ReportEntrySchema # ValidationError se usa dentro de llm_utils
# Eliminado extract_json_block - encapsulado en llm_utils

# Importar las nuevas utilidades
from ..utils.llm_utils import call_llm_and_parse_json_result
from ..utils.stage_helpers import skip_if_terminal_error, add_audit_entry


logger = logging.getLogger(__name__)

@register("generate")
async def generate_stage(items: List[Item], ctx: Dict[str, Any]) -> List[Item]:
    """
    Genera el payload de los ítems en un solo lote utilizando un LLM.
    Asigna los resultados a los objetos Item existentes en la lista de entrada.
    Refactorizado para usar llm_utils y stage_helpers.
    """
    stage_name = "generate"

    user_params: UserGenerateParams = UserGenerateParams.model_validate(ctx.get("user_params", {}))

    params = ctx.get("params", {}).get(stage_name, {})
    prompt_name = params.get("prompt", "01_agent_dominio.md") # Se mantiene un default, pero debería venir de pipeline.yml

    try:
        # Verificación inicial de prompt, aunque call_llm_and_parse_json_result también lo hace
        _ = load_prompt(prompt_name)
    except FileNotFoundError as e:
        for item in items:
            item.status = "fatal_error"
            item.errors.append(
                ReportEntrySchema(
                    code="PROMPT_NOT_FOUND",
                    message=f"Prompt '{prompt_name}' not found for generation stage: {e}",
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

    # Preparar el input para el LLM.
    llm_input_payload = user_params.model_dump()
    llm_input_payload["cantidad"] = len(items) # Usar 'cantidad' como lo espera el prompt

    user_input_content_json = json.dumps(llm_input_payload, ensure_ascii=False, indent=2)

    logger.info(f"Generating {len(items)} items with prompt '{prompt_name}' in a single batch.")

    # La etapa de generación no salta ítems en el bucle principal porque todos los ítems deben
    # ser generados o marcados con un error. La lógica de skip se aplicará en etapas posteriores.
    # Los ítems que vienen aquí están en estado 'pending' o 'fatal_error' por prompt_name no encontrado.

    # Llamada al LLM y parseo usando la utilidad genérica
    # expected_schema es List[ItemPayloadSchema] porque el LLM devuelve un array de ítems
    generated_payloads_list_raw, llm_errors_from_call_parse = await call_llm_and_parse_json_result(
        prompt_name=prompt_name,
        user_input_content=user_input_content_json,
        stage_name=stage_name,
        # Pasamos un item para acumular tokens y auditorías.
        # Si la llamada falla a nivel de lote, los errores se propagan a todos los ítems.
        item=items[0] if items else Item(payload=ItemPayloadSchema(item_id=uuid4(), metadata=user_params.metadata)),
        ctx=ctx,
        expected_schema=List[ItemPayloadSchema] # Espera un array de payloads
    )

    # Manejo de errores de la utilidad (fallo en llamada LLM o parseo inicial de la lista)
    if llm_errors_from_call_parse:
        for item in items: # Propaga el error a todos los ítems del lote
            # Solo si el ítem no ha sido marcado ya por un error fatal más temprano (ej. prompt not found)
            if item.status not in ["fatal_error"]:
                item.status = "generation_failed"
                item.errors.extend(llm_errors_from_call_parse)
                add_audit_entry(
                    item=item,
                    stage_name=stage_name,
                    summary=f"Error fatal en la generación/parseo del lote por LLM. Detalles: {llm_errors_from_call_parse[0].message[:200]}"
                )
        return items

    # Si no se devolvió una lista de payloads válidos
    if not isinstance(generated_payloads_list_raw, list):
        error_msg = "LLM did not return a list of items as expected."
        for item in items:
            if item.status not in ["fatal_error"]:
                item.status = "generation_failed"
                item.errors.append(
                    ReportEntrySchema(
                        code="LLM_RESPONSE_FORMAT_INVALID",
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
        return items


    # Verificar que el LLM generó la cantidad esperada de ítems
    if len(generated_payloads_list_raw) != len(items):
        error_msg = f"LLM generated {len(generated_payloads_list_raw)} items, but {len(items)} were requested."
        for item in items:
            if item.status not in ["fatal_error"]:
                item.status = "generation_failed"
                item.errors.append(
                    ReportEntrySchema(
                        code="LLM_ITEM_COUNT_MISMATCH",
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
        return items

    # Mapear los payloads generados a los objetos Item originales
    # Asumimos que el LLM mantiene el item_id (temp_id) en el payload generado
    # Crear un mapeo por item_id para una asignación precisa
    payloads_by_id = {payload.item_id: payload for payload in generated_payloads_list_raw}

    for item in items:
        # Aquí sí usamos skip_if_terminal_error para manejar ítems que ya fallaron en el manejo de lote
        if skip_if_terminal_error(item, stage_name):
            continue

        generated_payload_for_item = payloads_by_id.get(item.temp_id)

        if generated_payload_for_item:
            item.payload = generated_payload_for_item
            item.status = "generated" # Marcar el ítem como generado exitosamente
            item.prompt_v = prompt_name # Registrar el prompt usado

            # Limpiar errores de generación específicos de este ítem (si los hubo por algún motivo)
            # Esto se refiere a errores como LLM_CALL_FAILED o LLM_PARSE_VALIDATION_ERROR si ocurrieron a nivel de ítem.
            item.errors = [err for err in item.errors if not (err.code.startswith("LLM_") and ("GENERATION" in err.code or "PARSE" in err.code or "CALL" in err.code or "UNEXPECTED" in err.code))]

            add_audit_entry(
                item=item,
                stage_name=stage_name,
                summary=f"Ítem generado exitosamente por el Agente de Dominio (prompt: {prompt_name})."
            )
        else:
            item.status = "generation_failed_mismatch"
            item.errors.append(
                ReportEntrySchema(
                    code="ITEM_ID_MISMATCH",
                    message=f"LLM no devolvió un payload para el item_id: {item.temp_id}",
                    severity="error"
                )
            )
            add_audit_entry(
                item=item,
                stage_name=stage_name,
                summary=f"Fallo al mapear el payload generado por el LLM al ítem (missing item_id: {item.temp_id})."
            )
            logger.error(f"LLM did not return a payload for item_id: {item.temp_id} during generation.")

    logger.info(f"Generation stage completed for {len(items)} items. Total tokens: {ctx.get('usage_tokens_total', 0)}")
    return items
