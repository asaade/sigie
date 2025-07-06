# app/pipelines/utils/llm_utils.py

import json
import logging
from typing import Any, Dict, List, Optional, Tuple, Type, Callable, Union
from pydantic import BaseModel, ValidationError, TypeAdapter

from app.llm import generate_response, LLMResponse # Asumo que generate_response ahora es la función directamente importada
from app.prompts import load_prompt
from app.schemas.models import Item
from app.schemas.item_schemas import ReportEntrySchema

from ..utils.parsers import extract_json_block, build_prompt_messages # Mantengo build_prompt_messages por si se usa en otros sitios

logger = logging.getLogger(__name__)

MAX_ERROR_MESSAGE_LENGTH = 900 # Definido en la versión anterior, lo mantengo aquí por coherencia

def _strip_json_markdown(text: str) -> str:
    """Strips markdown code fences (```json\n...\n```) from a string."""
    if text.startswith("```json"):
        text = text[len("```json"):].strip()
        if text.endswith("```"):
            text = text[:-len("```")].strip()
    return text

async def call_llm_and_parse_json_result(
    prompt_name: str,
    user_input_content: str,
    stage_name: str,
    item: Item,
    ctx: Dict[str, Any],
    expected_schema: Optional[Type[BaseModel] | Type[List[Any]]] = None, # Tipo actualizado para listas
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
    response_metadata = {"stage": stage_name} # Se mantiene por si se usa

    try:
        prompt_data = load_prompt(prompt_name)
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

    system_message = ""
    user_prompt_template = ""

    if isinstance(prompt_data, dict):
        system_message = prompt_data.get("system_message", "")
        # MODIFICACIÓN CRÍTICA: Corregido para usar 'content'
        user_prompt_template = prompt_data.get("content", "{input}")
    else:
        # Si no hay separador, todo el contenido es la plantilla de usuario
        user_prompt_template = str(prompt_data)

    # Asegurarse de que el user_input_content se inyecte en el placeholder
    # Si la plantilla de usuario no tiene {input}, simplemente se añadirá al final.
    formatted_user_prompt = user_prompt_template.replace("{input}", user_input_content)

    # MODIFICACIÓN CRÍTICA AQUÍ: Construir los mensajes correctamente para el LLM
    messages = []
    if system_message:
        messages.append({"role": "system", "content": system_message})
    messages.append({"role": "user", "content": formatted_user_prompt})


    llm_call_params = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "provider": provider, # Lo mantengo como argumento, según tu versión
        "top_k": top_k,
        "top_p": top_p,
        "stop_sequences": stop_sequences,
        "seed": seed,
    }
    llm_call_params = {k: v for k, v in llm_call_params.items() if v is not None}
    llm_call_params.update(kwargs)

    # Asumo que generate_response es de app.llm y usa el 'provider' de kwargs o del contexto
    llm_provider_name = llm_call_params.pop("provider", ctx.get("llm_provider_name", "openai"))

    try:
        # Asegúrate de que generate_response en app.llm acepte 'provider' como parámetro
        resp: LLMResponse = await generate_response(
            messages=messages,
            provider=llm_provider_name,
            **llm_call_params
        )

        # response_metadata["model"] = resp.model # Asumo que resp tiene .model
        # response_metadata["usage"] = resp.usage # Asumo que resp tiene .usage
        if resp.usage:
            item.token_usage = (item.token_usage or 0) + resp.usage.get("total", 0)
            ctx["usage_tokens_total"] = ctx.get("usage_tokens_total", 0) + resp.usage.get("total", 0)


        if not resp.success:
            error_msg = f"LLM call failed for stage '{stage_name}': {resp.error_message}"
            current_errors.append(
                ReportEntrySchema(
                    code="E905_LLM_CALL_FAILED", # Usando tu nuevo código de error
                    message=error_msg[:MAX_ERROR_MESSAGE_LENGTH],
                    field="llm_api_call",
                    severity="error"
                )
            )
            logger.error(error_msg)
            return None, current_errors, resp.text # Retorna raw_llm_text

        raw_llm_text = resp.text

        if custom_parser_func:
            parsed_result, parser_errors = custom_parser_func(raw_llm_text)
            current_errors.extend(parser_errors)
        else:
            cleaned_response_text = _strip_json_markdown(raw_llm_text)

            if expected_schema is None:
                # Si no se espera un esquema específico, devolver el texto limpio
                return cleaned_response_text, current_errors, raw_llm_text # Retorna raw_llm_text

            try:
                # Intentar validar con TypeAdapter si es una lista, o directamente si es BaseModel
                if hasattr(expected_schema, '__origin__') and expected_schema.__origin__ is list:
                    parsed_result = TypeAdapter(expected_schema).validate_json(cleaned_response_text)
                else:
                    parsed_result = expected_schema.model_validate_json(cleaned_response_text)

            except ValidationError as e:
                error_msg = f"Error de validación/parseo del LLM: {e}. Respuesta recibida: {cleaned_response_text[:500]}..."
                current_errors.append(
                    ReportEntrySchema(
                        code="E906_LLM_PARSE_VALIDATION_ERROR", # Usando tu nuevo código de error
                        message=error_msg[:MAX_ERROR_MESSAGE_LENGTH],
                        field="llm_response_json",
                        severity="error"
                    )
                )
                logger.error(error_msg)
                return None, current_errors, raw_llm_text # Retorna raw_llm_text
            except json.JSONDecodeError as e:
                error_msg = f"Error de decodificación JSON para la etapa '{stage_name}': {e}. Raw: {cleaned_response_text[:200]}"
                current_errors.append(
                    ReportEntrySchema(
                        code="E906_LLM_PARSE_VALIDATION_ERROR",
                        message=error_msg[:MAX_ERROR_MESSAGE_LENGTH],
                        field="llm_response_json",
                        severity="error"
                    )
                )
                logger.error(error_msg)
                return None, current_errors, raw_llm_text
    except Exception as e:
        error_msg = f"Error inesperado durante la llamada al LLM en la etapa '{stage_name}': {e}"
        logger.error(error_msg, exc_info=True)
        current_errors.append(
            ReportEntrySchema(
                code="E907_UNEXPECTED_LLM_PROCESSING_ERROR", # Usando tu nuevo código de error
                message=error_msg[:MAX_ERROR_MESSAGE_LENGTH],
                field="llm_response",
                severity="fatal"
            )
        )
        return None, current_errors, None

    return parsed_result, current_errors, raw_llm_text
