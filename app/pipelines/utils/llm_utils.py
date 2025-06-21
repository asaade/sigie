# app/pipelines/utils/llm_utils.py

import json
import logging
from typing import Dict, Any, List, Tuple, Type, Optional
from pydantic import BaseModel, ValidationError

from app.llm import generate_response, LLMResponse # Asumo que LLMResponse está definido en app.llm
from app.prompts import load_prompt
from app.schemas.models import Item # Para poder usar el objeto Item
from app.schemas.item_schemas import ReportEntrySchema # Para reportar errores internos de la utilidad
from ..utils.parsers import extract_json_block # Necesario para la extracción del bloque JSON

logger = logging.getLogger(__name__)

async def call_llm_and_parse_json_result(
    prompt_name: str,
    user_input_content: str, # Contenido JSON serializado para el rol "user"
    stage_name: str,
    item: Item, # Pasamos el ítem para añadir errores/auditorías directamente
    ctx: Dict[str, Any], # Contexto del pipeline para params y tokens
    expected_schema: Optional[Type[BaseModel]] = None # El esquema Pydantic esperado para la salida del LLM (ahora opcional)
) -> Tuple[Optional[BaseModel], List[ReportEntrySchema], Optional[str]]:
    """
    Encapsula la llamada al LLM, el manejo de su respuesta, el parseo de JSON
    y la validación Pydantic, reportando errores y acumulando tokens.
    Ahora también devuelve el texto crudo de la respuesta del LLM.

    Retorna:
        - parsed_result: El objeto Pydantic parseado si es exitoso y expected_schema no es None.
        - errors: Lista de ReportEntrySchema con errores detectados por la utilidad.
        - raw_llm_text: El texto crudo completo de la respuesta del LLM.
    """
    current_errors: List[ReportEntrySchema] = []
    parsed_result: Optional[BaseModel] = None
    raw_llm_text: Optional[str] = None

    # Obtener parámetros del LLM desde el contexto del pipeline (definidos en pipeline.yml)
    llm_params = ctx.get("params", {}).get(stage_name, {})
    model = llm_params.get("model")
    temperature = llm_params.get("temperature", 0.7)
    max_tokens = llm_params.get("max_tokens", 1000)

    try:
        # Cargar el prompt
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
        return None, current_errors, None # Devolver None para el texto crudo también

    messages = [
        {"role": "system", "content": prompt_template},
        {"role": "user", "content": user_input_content},
    ]

    # Llamada al LLM
    resp: LLMResponse = await generate_response(
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens
    )

    # Capturar el texto crudo inmediatamente
    raw_llm_text = resp.text

    # Acumular uso de tokens
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
        return None, current_errors, raw_llm_text # Devolver el texto crudo

    # Parsear y validar la respuesta JSON solo si se espera un esquema específico
    if expected_schema:
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
            return None, current_errors, raw_llm_text # Devolver el texto crudo
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
            return None, current_errors, raw_llm_text # Devolver el texto crudo

    return parsed_result, current_errors, raw_llm_text
