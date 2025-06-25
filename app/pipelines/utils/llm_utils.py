# app/pipelines/utils/llm_utils.py

import json
import logging
from typing import List, Tuple, Type, Optional, Any, Dict, Callable # Aseguradas solo las importaciones necesarias
from pydantic import BaseModel, ValidationError, TypeAdapter # TypeAdapter es CRÍTICO aquí

from app.llm import generate_response, LLMResponse # generate_response y LLMResponse son necesarios
from app.prompts import load_prompt # load_prompt es necesario para cargar el prompt
from app.schemas.models import Item # Item es necesario para el argumento 'item'
from app.schemas.item_schemas import ReportEntrySchema # ReportEntrySchema es necesario para los errores

from ..utils.parsers import extract_json_block # extract_json_block es necesario para parseo de JSON

logger = logging.getLogger(__name__)

# Límite de caracteres para los mensajes de error internos del sistema
# para evitar desbordar los campos 'message' de ReportEntrySchema (max_length=2000)
# y 'summary' de AuditEntrySchema (max_length=1000).
MAX_ERROR_MESSAGE_LENGTH = 900 # Un valor conservador que cabe bien en summary y message.

async def call_llm_and_parse_json_result(
    prompt_name: str,
    user_input_content: str,
    stage_name: str,
    item: Item, # Se pasa el ítem para auditoría y tokens
    ctx: Dict[str, Any], # Necesario para parámetros de etapa y acumulación de tokens
    expected_schema: Optional[Type[BaseModel] | Type[List[Any]]] = None, # Puede ser un BaseModel o List[AlgunTipo]. Usamos Any para flexibilidad con TypeAdapter.
    custom_parser_func: Optional[Callable[[str], Tuple[Any, List[ReportEntrySchema]]]] = None
) -> Tuple[Optional[Any], List[ReportEntrySchema], Optional[str]]:
    """
    Encapsula la llamada al LLM, el manejo de su respuesta, el parseo de JSON
    y la validación Pydantic, reportando errores y acumulando tokens.
    Permite especificar el proveedor LLM por etapa.

    Retorna:
        - parsed_result: El objeto parseado (BaseModel o cualquier tipo del custom_parser_func) si es exitoso, None si falla.
        - errors: Lista de ReportEntrySchema con errores detectados por la utilidad (ej. fallo de llamada LLM, parseo JSON).
        - raw_llm_text: El texto crudo completo de la respuesta del LLM.
    """
    current_errors: List[ReportEntrySchema] = []
    parsed_result: Optional[Any] = None
    raw_llm_text: Optional[str] = None

    # Obtener parámetros del LLM desde el contexto del pipeline (definidos en pipeline.yml)
    llm_params = ctx.get("params", {}).get(stage_name, {})

    provider = llm_params.get("provider")
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
                message=error_msg[:MAX_ERROR_MESSAGE_LENGTH], # Truncar mensaje para asegurar que quepa
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
        provider=provider, # Pasa el proveedor específico
        model=model,
        temperature=temperature,
        max_tokens=max_tokens
    )

    raw_llm_text = resp.text

    # Acumular uso de tokens en el ítem y en el contexto global
    current_item_tokens = resp.usage.get("total", 0)
    item.token_usage = (item.token_usage or 0) + current_item_tokens
    ctx['usage_tokens_total'] = ctx.get('usage_tokens_total', 0) + current_item_tokens

    if not resp.success:
        error_msg = f"LLM call failed for stage '{stage_name}': {resp.error_message}"
        current_errors.append(
            ReportEntrySchema(
                code="LLM_CALL_FAILED",
                message=error_msg[:MAX_ERROR_MESSAGE_LENGTH], # Truncar mensaje
                field="llm_response",
                severity="error"
            )
        )
        logger.error(error_msg)
        return None, current_errors, raw_llm_text

    if custom_parser_func:
        try:
            # Asumimos que custom_parser_func devolverá (resultado, lista_de_ReportEntrySchema_si_hay_errores)
            # y que extract_json_block se maneja dentro de custom_parser_func si es necesario.
            parsed_result, parser_errors = custom_parser_func(raw_llm_text)
            current_errors.extend(parser_errors) # Añadir errores del parser personalizado a la lista de errores de la utilidad
        except Exception as e:
            error_msg = f"Unexpected error during custom parsing for stage '{stage_name}': {e}. Raw: {raw_llm_text[:200]}"
            current_errors.append(
                ReportEntrySchema(
                    code="UNEXPECTED_CUSTOM_PARSE_ERROR",
                    message=error_msg[:MAX_ERROR_MESSAGE_LENGTH], # Truncar mensaje
                    field="llm_response_custom_parse",
                    severity="error"
                )
            )
            logger.error(error_msg)
            return None, current_errors, raw_llm_text
    elif expected_schema: # Si no hay custom_parser_func, usar el esquema Pydantic directamente
        try:
            clean_json_str = extract_json_block(raw_llm_text)

            # CRÍTICO: Usar TypeAdapter para validar tipos complejos como List[BaseModel] o List[Any]
            parsed_result = TypeAdapter(expected_schema).validate_json(clean_json_str)

        except (json.JSONDecodeError, ValueError, ValidationError) as e:
            error_msg = f"Failed to parse/validate LLM response for stage '{stage_name}': {e}. Raw: {raw_llm_text[:200]}"
            current_errors.append(
                ReportEntrySchema(
                    code="LLM_PARSE_VALIDATION_ERROR",
                    message=error_msg[:MAX_ERROR_MESSAGE_LENGTH], # Truncar mensaje
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
                    message=error_msg[:MAX_ERROR_MESSAGE_LENGTH], # Truncar mensaje
                    field="llm_response",
                    severity="error"
                )
            )
            logger.error(error_msg)
            return None, current_errors, raw_llm_text

    return parsed_result, current_errors, raw_llm_text
