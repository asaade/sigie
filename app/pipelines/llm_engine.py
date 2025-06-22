# Archivo nuevo: app/pipelines/builtins/llm_engine.py

import logging
from typing import List, Dict, Any

from ..registry import register
from ..logic_blocks import LOGIC_BLOCKS
from ..utils.llm_utils import call_llm_and_parse_json_result
from ..utils.stage_helpers import (
    process_items_concurrently,
    update_item_status_and_audit,
    handle_prompt_not_found_error
)
from app.prompts import load_prompt
from app.schemas.models import Item

logger = logging.getLogger(__name__)

@register("llm_engine")
async def llm_engine_stage(items: List[Item], ctx: Dict[str, Any], **kwargs: Any) -> List[Item]:
    """
    Motor universal para todas las etapas LLM. Compone su comportamiento
    a partir de bloques de lógica definidos en el pipeline.yml.
    """
    stage_name = kwargs.get("name")
    params = kwargs.get("params", {})
    prompt_name = params.get("prompt")

    if not stage_name:
        # Esto no debería ocurrir si el runner funciona como se espera.
        logger.error("LLM Engine called without a 'name' in kwargs.")
        return items

    if not prompt_name:
        logger.error(f"Stage '{stage_name}' uses llm_engine but does not define a 'prompt' in its params.")
        for item in items:
            update_item_status_and_audit(item, stage_name, f"{stage_name}.fail.config_error", "Configuration error: prompt missing.")
        return items

    try:
        _ = load_prompt(prompt_name)
    except FileNotFoundError as e:
        return handle_prompt_not_found_error(items, stage_name, prompt_name, e)

    # 1. Seleccionar los bloques de lógica según la configuración del YAML
    prepare_logic_key = params.get("prepare_logic", "validation")
    apply_logic_key = params.get("apply_logic", "validation")
    schema_key = params.get("schema_logic", prepare_logic_key)

    prepare_fn = LOGIC_BLOCKS["prepare"].get(prepare_logic_key)
    apply_fn = LOGIC_BLOCKS["apply"].get(apply_logic_key)
    schema = LOGIC_BLOCKS["schema"].get(schema_key)

    if not all([prepare_fn, apply_fn, schema]):
        error_msg = f"Configuration error in stage '{stage_name}': one or more logic_blocks keys are invalid (prepare: {prepare_logic_key}, apply: {apply_logic_key}, schema: {schema_key})."
        logger.error(error_msg)
        for item in items:
            update_item_status_and_audit(item, stage_name, f"{stage_name}.fail.config_error", error_msg)
        return items

    async def process_item(item: Item, ctx_inner: dict, **kwargs_inner: Any):
        """Función que se ejecuta para cada ítem de forma concurrente."""

        llm_input = prepare_fn(item, **params)

        result, llm_errors, _ = await call_llm_and_parse_json_result(
            prompt_name=prompt_name,
            user_input_content=llm_input,
            stage_name=stage_name,
            item=item,
            ctx=ctx,
            expected_schema=schema,
            **params
        )

        if llm_errors:
            error_summary = f"LLM call or parse failed: {llm_errors[0].message}"
            update_item_status_and_audit(item, stage_name, f"{stage_name}.fail.llm_error", error_summary)
            item.errors.extend(llm_errors)
        elif result:
            await apply_fn(item, result, stage_name, **params)
        else:
            update_item_status_and_audit(item, stage_name, f"{stage_name}.fail.no_result", "LLM did not return a valid result.")

    await process_items_concurrently(items, process_item, ctx, **params)

    logger.info(f"LLM Engine finished stage: '{stage_name}'.")
    return items
