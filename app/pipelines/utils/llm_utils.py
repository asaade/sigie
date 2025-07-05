# app/pipelines/utils/llm_utils.py

import logging
from typing import Optional, Type, Tuple, Dict, Any
from pydantic import BaseModel, ValidationError

from app.schemas.models import Item
from app.schemas.item_schemas import ReportEntrySchema
from app.prompts import load_prompt
from app.llm.providers import get_provider

logger = logging.getLogger(__name__)

async def call_llm_and_parse_json_result(
    prompt_name: str,
    user_input_content: str,
    stage_name: str,
    item: Item,
    ctx: Dict[str, Any],
    expected_schema: Optional[Type[BaseModel]] = None,
    **kwargs
) -> Tuple[Optional[BaseModel | str], Optional[list[ReportEntrySchema]], Optional[Dict[str, Any]]]:
    """
    Orquesta la llamada a un LLM, seleccionando el proveedor dinámicamente,
    y parsea la respuesta JSON.
    """
    try:
        prompt_data = load_prompt(prompt_name)

        system_message = ""
        user_prompt_template = ""

        if isinstance(prompt_data, dict):
            system_message = prompt_data.get("system_message", "")
            user_prompt_template = prompt_data.get("content", "{input}")
        else:
            user_prompt_template = str(prompt_data)

        # --- INICIO DE LA CORRECCIÓN ---
        # Se reemplaza el método .format() por .replace().
        # Esto busca la cadena de texto exacta "{input}" y la reemplaza,
        # sin interpretar las llaves {} del ejemplo de JSON en el prompt.
        formatted_user_prompt = user_prompt_template.replace("{input}", user_input_content)
        # --- FIN DE LA CORRECCIÓN ---

        full_prompt = f"{system_message}\n\n{formatted_user_prompt}".strip()

        provider_name = kwargs.get("provider", "openai").lower()
        llm_provider = get_provider(provider_name)

        logger.info(f"Usando proveedor de LLM: {provider_name} para la etapa {stage_name}")

        messages = [{"role": "user", "content": full_prompt}]
        response_obj = await llm_provider.generate_response(messages, kwargs)

        if not response_obj.success:
            error = ReportEntrySchema(code="E905_LLM_CALL_FAILED", message=response_obj.error_message, severity="error")
            return None, [error], None

        if response_obj.usage:
            item.token_usage += response_obj.usage.get("total", 0)
            ctx["usage_tokens_total"] = ctx.get("usage_tokens_total", 0) + response_obj.usage.get("total", 0)

        if not response_obj.text:
            error = ReportEntrySchema(code="E904_NO_LLM_RESPONSE", message="El LLM no devolvió contenido.", severity="error")
            return None, [error], response_obj.usage

        if expected_schema is None:
            return response_obj.text, None, response_obj.usage

        try:
            parsed_result = expected_schema.model_validate_json(response_obj.text)
            return parsed_result, None, response_obj.usage
        except ValidationError as e:
            error_msg = f"Error de validación/parseo del LLM: {e}. Respuesta recibida: {response_obj.text[:500]}..."
            error = ReportEntrySchema(code="E906_LLM_PARSE_VALIDATION_ERROR", message=error_msg, severity="error")
            return None, [error], response_obj.usage

    except Exception as e:
        error_msg = f"Error inesperado durante la llamada al LLM en la etapa '{stage_name}': {e}"
        logger.error(error_msg, exc_info=True)
        error = ReportEntrySchema(code="E907_UNEXPECTED_LLM_PROCESSING_ERROR", message=error_msg, severity="fatal")
        return None, [error], None
