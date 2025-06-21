# app/pipelines/builtins/generate_items.py

from __future__ import annotations
import logging
import json
from typing import List, Dict, Any
from uuid import uuid4

from ..registry import register
from app.prompts import load_prompt
from app.schemas.models import Item
from app.schemas.item_schemas import ItemPayloadSchema, UserGenerateParams, ReportEntrySchema, MetadataSchema

from ..utils.llm_utils import call_llm_and_parse_json_result
from ..utils.stage_helpers import (
    skip_if_terminal_error,
    add_audit_entry,
    handle_prompt_not_found_error,
    clean_item_llm_errors,
    check_and_handle_batch_llm_errors, # Nueva
    check_and_handle_llm_response_format_error, # Nueva
    check_and_handle_llm_item_count_mismatch # Nueva
)


logger = logging.getLogger(__name__)

@register("generate")
async def generate_stage(items: List[Item], ctx: Dict[str, Any]) -> List[Item]:
    """
    Genera el payload de los ítems en un solo lote utilizando un LLM.
    Refactorizado para usar llm_utils y stage_helpers.
    """
    stage_name = "generate"

    user_params: UserGenerateParams = UserGenerateParams.model_validate(ctx.get("user_params", {}))

    params = ctx.get("params", {}).get(stage_name, {})
    prompt_name = params.get("prompt", "01_agent_dominio.md")

    try:
        _ = load_prompt(prompt_name)
    except FileNotFoundError as e:
        return handle_prompt_not_found_error(items, stage_name, prompt_name, e)

    llm_input_payload = user_params.model_dump()
    llm_input_payload["cantidad"] = len(items)

    user_input_content_json = json.dumps(llm_input_payload, ensure_ascii=False, indent=2)

    logger.info(f"Generating {len(items)} items with prompt '{prompt_name}' in a single batch.")

    representative_item = items[0] if items else Item(payload=ItemPayloadSchema(item_id=uuid4(), metadata=MetadataSchema(idioma_item="es", area="", asignatura="", tema="", nivel_destinatario="", nivel_cognitivo="recordar", dificultad_prevista="facil"))) # Se necesita metadata completa para inicializar

    generated_payloads_list_raw, llm_errors_from_call_parse, _ = await call_llm_and_parse_json_result(
        prompt_name=prompt_name,
        user_input_content=user_input_content_json,
        stage_name=stage_name,
        item=representative_item, # Se pasa un item representativo para tokens y auditoría de la llamada global
        ctx=ctx,
        expected_schema=List[ItemPayloadSchema]
    )

    # Manejar errores de la utilidad (fallo en llamada LLM o parseo inicial de la lista)
    if check_and_handle_batch_llm_errors(
        items=items,
        stage_name=stage_name,
        llm_errors_from_call_parse=llm_errors_from_call_parse,
        summary_prefix="Error fatal en la generación/parseo del lote por LLM",
        llm_fail_status="generation_failed"
    ):
        return items

    # Verificar que el LLM devolvió una lista
    if check_and_handle_llm_response_format_error(
        items=items,
        stage_name=stage_name,
        generated_payloads_list_raw=generated_payloads_list_raw,
        expected_type=List[ItemPayloadSchema], # Type[List[ItemPayloadSchema]]
        error_code="LLM_RESPONSE_FORMAT_INVALID",
        message="LLM did not return a list of items as expected.",
        llm_fail_status="generation_failed"
    ):
        return items

    # Verificar que el LLM generó la cantidad esperada de ítems
    if check_and_handle_llm_item_count_mismatch(
        items=items,
        stage_name=stage_name,
        generated_payloads_list_raw=generated_payloads_list_raw,
        error_code="LLM_ITEM_COUNT_MISMATCH",
        message=f"LLM generated {len(generated_payloads_list_raw)} items, but {len(items)} were requested.",
        llm_fail_status="generation_failed"
    ):
        return items

    payloads_by_id = {payload.item_id: payload for payload in generated_payloads_list_raw}

    for item in items:
        if skip_if_terminal_error(item, stage_name):
            continue

        generated_payload_for_item = payloads_by_id.get(item.temp_id)

        if generated_payload_for_item:
            item.payload = generated_payload_for_item
            item.status = "generated"
            item.prompt_v = prompt_name

            clean_item_llm_errors(item) # Limpia errores de LLM/parseo si este ítem fue exitoso

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
