# app/pipelines/utils/llm_utils.py

import json
import logging
from typing import Any, Dict, List, Optional, Tuple, Type, Callable

from pydantic import BaseModel, ValidationError, TypeAdapter

from app.llm import generate_response, LLMResponse
from app.prompts import load_prompt
from app.schemas.models import Item
from app.schemas.item_schemas import ReportEntrySchema

from ..utils.parsers import extract_json_block, build_prompt_messages

logger = logging.getLogger(__name__)

MAX_ERROR_MESSAGE_LENGTH = 900

async def call_llm_and_parse_json_result(
    prompt_name: str,
    user_input_content: str,
    stage_name: str,
    item: Item,
    ctx: Dict[str, Any],
    expected_schema: Optional[Type[BaseModel] | Type[List[Any]]] = None,
    custom_parser_func: Optional[Callable[[str], Tuple[Any, List[ReportEntrySchema]]]] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    provider: Optional[str] = None, # provider es un argumento explícito aquí
    top_k: Optional[int] = None,
    top_p: Optional[float] = None,
    stop_sequences: Optional[List[str]] = None,
    seed: Optional[int] = None,
    **kwargs: Any
) -> Tuple[Optional[Any], List[ReportEntrySchema], Optional[str]]:
    """
    Función central para llamar a los LLMs, obtener respuestas JSON y validarlas.
    """
    current_errors: List[ReportEntrySchema] = []
    parsed_result: Optional[Any] = None
    raw_llm_text: Optional[str] = None
    response_metadata = {"stage": stage_name}

    try:
        prompt_template_dict = load_prompt(prompt_name)
    except FileNotFoundError as e:
        error_msg = f"Prompt '{prompt_name}' not found for stage '{stage_name}': {e}"
        current_errors.append(
            ReportEntrySchema(
                code="PROMPT_NOT_FOUND",
                message=error_msg[:MAX_ERROR_MESSAGE_LENGTH],
                field="prompt_name",
                severity="error"
            )
        )
        logger.error(error_msg)
        return None, current_errors, None

    system_message = prompt_template_dict.get("system_message", "")
    user_message_template = prompt_template_dict.get("user_message_template", "")

    messages = build_prompt_messages(
        system_template=system_message,
        user_message_template=user_message_template,
        payload=user_input_content
    )

    llm_call_params = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        # "provider": provider, # ¡REMOVIDO! generate_response lo recibe como argumento nombrado explícito
        "top_k": top_k,
        "top_p": top_p,
        "stop_sequences": stop_sequences,
        "seed": seed,
    }
    llm_call_params = {k: v for k, v in llm_call_params.items() if v is not None}
    llm_call_params.update(kwargs)

    llm_provider_name = ctx.get("llm_provider_name", "openai") # Este valor se usará si el argumento 'provider' es None

    try:
        resp: LLMResponse = await generate_response(
            messages=messages,
            provider=llm_provider_name, # Pasar provider explícitamente como argumento nombrado
            **llm_call_params # Pasar el resto de los parámetros de configuración vía **kwargs
        )

        response_metadata["model"] = resp.model
        response_metadata["usage"] = resp.usage
        item.token_usage = (item.token_usage or 0) + resp.usage.get("total", 0)

        if not resp.success:
            error_msg = f"LLM call failed for stage '{stage_name}': {resp.error_message}"
            current_errors.append(
                ReportEntrySchema(
                    code="LLM_CALL_FAILED",
                    message=error_msg[:MAX_ERROR_MESSAGE_LENGTH],
                    field="llm_api_call",
                    severity="error"
                )
            )
            logger.error(error_msg)
            return None, current_errors, resp.text

        raw_llm_text = resp.text

        if custom_parser_func:
            parsed_result, parser_errors = custom_parser_func(raw_llm_text)
            current_errors.extend(parser_errors)
        else:
            clean_json_str = extract_json_block(raw_llm_text)

            parsed_result = TypeAdapter(expected_schema).validate_json(clean_json_str)

    except (json.JSONDecodeError, ValueError, ValidationError) as e:
        error_msg = f"Failed to parse/validate LLM response for stage '{stage_name}': {e}. Raw: {raw_llm_text[:200]}"
        current_errors.append(
            ReportEntrySchema(
                code="LLM_PARSE_VALIDATION_ERROR",
                message=error_msg[:MAX_ERROR_MESSAGE_LENGTH],
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
                message=error_msg[:MAX_ERROR_MESSAGE_LENGTH],
                field="llm_response",
                severity="error"
            )
        )
        logger.error(error_msg)
        return None, current_errors, raw_llm_text

    return parsed_result, current_errors, raw_llm_text
