# app/pipelines/utils/llm_utils.py

import json
import logging
from typing import Dict, Any, List, Tuple, Type, Optional, Callable
from pydantic import BaseModel, ValidationError

from app.llm import generate_response, LLMResponse
from app.prompts import load_prompt
from app.schemas.models import Item
from app.schemas.item_schemas import ReportEntrySchema
from ..utils.parsers import extract_json_block

logger = logging.getLogger(__name__)

async def call_llm_and_parse_json_result(
    prompt_name: str,
    user_input_content: str,
    stage_name: str,
    item: Item,
    ctx: Dict[str, Any],
    expected_schema: Optional[Type[BaseModel]] = None,
    custom_parser_func: Optional[Callable[[str], Tuple[Any, List[ReportEntrySchema]]]] = None
) -> Tuple[Optional[Any], List[ReportEntrySchema], Optional[str]]:
    """
    Encapsula la llamada al LLM, el manejo de su respuesta, el parseo de JSON
    y la validación Pydantic, reportando errores y acumulando tokens.
    Ahora también permite especificar el proveedor LLM por etapa.

    Retorna:
        - parsed_result: El objeto parseado (BaseModel o cualquier tipo del custom_parser_func) si es exitoso, None si falla.
        - errors: Lista de ReportEntrySchema con errores detectados por la utilidad.
        - raw_llm_text: El texto crudo completo de la respuesta del LLM.
    """
    current_errors: List[ReportEntrySchema] = []
    parsed_result: Optional[Any] = None
    raw_llm_text: Optional[str] = None

    llm_params = ctx.get("params", {}).get(stage_name, {})

    # --- Añadido: Obtener el proveedor específico para esta etapa ---
    provider = llm_params.get("provider")
    # ----------------------------------------------------------------

    model = llm_params.get("model")
    temperature = llm_params.get("temperature", 0.7)
    max_tokens = llm_params.get("max_tokens", 1000)

    try:
        prompt_template = load_prompt(prompt_name)
    except FileNotFoundError as e:
        error_msg = f"Prompt '{prompt_name}' not found for stage '{stage_name}': {e}"
        current_errors.append(
            ReportEntrySchema(
                code="PROMPT_NOT_FOUND",
                message=error_msg,
                field="prompt_name",
                severity="error"
            )
        )
        logger.error(error_msg)
        return None, current_errors, None

    messages = [
        {"role": "system", "content": prompt_template},
        {"role": "user", "content": user_input_content},
    ]

    resp: LLMResponse = await generate_response(
        messages=messages,
        provider=provider, # --- Añadido: Pasamos el proveedor específico de la etapa ---
        model=model,
        temperature=temperature,
        max_tokens=max_tokens
    )

    raw_llm_text = resp.text

    current_item_tokens = resp.usage.get("total", 0)
    item.token_usage = (item.token_usage or 0) + current_item_tokens
    ctx['usage_tokens_total'] = ctx.get('usage_tokens_total', 0) + current_item_tokens

    if not resp.success:
        error_msg = f"LLM call failed for stage '{stage_name}': {resp.error_message}"
        current_errors.append(
            ReportEntrySchema(
                code="LLM_CALL_FAILED",
                message=error_msg,
                field="llm_response",
                severity="error"
            )
        )
        logger.error(error_msg)
        return None, current_errors, raw_llm_text

    if custom_parser_func:
        try:
            parsed_result, parser_errors = custom_parser_func(raw_llm_text)
            current_errors.extend(parser_errors)
        except Exception as e:
            error_msg = f"Unexpected error during custom parsing for stage '{stage_name}': {e}. Raw: {raw_llm_text[:500]}"
            current_errors.append(
                ReportEntrySchema(
                    code="UNEXPECTED_CUSTOM_PARSE_ERROR",
                    message=error_msg,
                    field="llm_response_custom_parse",
                    severity="error"
                )
            )
            logger.error(error_msg)
            return None, current_errors, raw_llm_text
    elif expected_schema:
        try:
            clean_json_str = extract_json_block(raw_llm_text)
            parsed_result = expected_schema.model_validate_json(clean_json_str)

        except (json.JSONDecodeError, ValueError, ValidationError) as e:
            error_msg = f"Failed to parse/validate LLM response for stage '{stage_name}': {e}. Raw: {raw_llm_text[:500]}"
            current_errors.append(
                ReportEntrySchema(
                    code="LLM_PARSE_VALIDATION_ERROR",
                    message=error_msg,
                    field="llm_response_json",
                    severity="error"
                )
            )
            logger.error(error_msg)
            return None, current_errors, raw_llm_text
        except Exception as e:
            error_msg = f"Unexpected error during LLM response processing for stage '{stage_name}': {e}"
            current_errors.append(
                ReportEntrySchema(
                    code="UNEXPECTED_LLM_PROCESSING_ERROR",
                    message=error_msg,
                    field="llm_response",
                    severity="error"
                )
            )
            logger.error(error_msg)
            return None, current_errors, raw_llm_text

    return parsed_result, current_errors, raw_llm_text
