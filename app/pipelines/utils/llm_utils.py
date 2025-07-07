# app/pipelines/utils/llm_utils.py

from __future__ import annotations
import logging
import json
from typing import Tuple, List, Optional, Type, Any, Dict
from pydantic import BaseModel, ValidationError

from app.llm.providers import generate_response as generate_llm_response
from app.schemas.item_schemas import FindingSchema
from app.schemas.models import Item
from app.prompts import load_prompt
from app.core.config import settings

logger = logging.getLogger(__name__)

async def call_llm_and_parse_json_result(
    prompt_name: str,
    user_input_content: str,
    stage_name: str,
    item: Item,
    ctx: Dict[str, Any],
    expected_schema: Optional[Type[BaseModel]] = None,
    **kwargs,
) -> Tuple[Optional[BaseModel | str], Optional[List[FindingSchema]], int]:
    """
    Prepara los prompts, llama al proveedor de LLM y parsea la respuesta JSON.
    Ahora es robusto al manejar la carga del prompt.
    """
    total_tokens_used = 0
    try:
        # --- CORRECCIÓN DE LÓGICA DE PARSEO ---
        prompt_data = load_prompt(prompt_name)
        system_prompt = None
        user_prompt_template = None

        if isinstance(prompt_data, dict):
            system_prompt = prompt_data.get("system_message")
            user_prompt_template = prompt_data.get("content")
        elif isinstance(prompt_data, str):
            user_prompt_template = prompt_data

        if not user_prompt_template:
            raise ValueError(f"No se pudo cargar una plantilla de prompt válida desde '{prompt_name}'.")

        # Se usa .replace() para inyectar el JSON de forma segura, evitando errores con llaves {}.
        full_user_prompt = user_prompt_template.replace("{input}", user_input_content)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": full_user_prompt})

        provider_name = kwargs.pop("provider", settings.llm_provider)
        model_name = kwargs.pop("model", settings.llm_model)

        llm_response = await generate_llm_response(
            messages=messages,
            provider=provider_name,
            model=model_name,
            **kwargs,
        )

        tokens_used = llm_response.usage.get("total", 0)
        total_tokens_used += tokens_used
        item.token_usage += tokens_used

        if not llm_response.success:
            error_msg = llm_response.error_message or "Error desconocido del proveedor LLM."
            error = FindingSchema(codigo_error="E901_LLM_CALL_FAILED", campo_con_error="llm_response", descripcion_hallazgo=error_msg)
            return None, [error], total_tokens_used

        response_text = llm_response.text
        if not response_text:
            error = FindingSchema(codigo_error="E901_LLM_NO_RESPONSE", campo_con_error="llm_response", descripcion_hallazgo="El LLM no devolvió contenido de texto.")
            return None, [error], total_tokens_used

        if expected_schema is None:
            return response_text, None, total_tokens_used

        cleaned_json_str = response_text.strip().removeprefix("```json").removesuffix("```").strip()
        validated_obj = expected_schema.model_validate_json(cleaned_json_str)
        return validated_obj, None, total_tokens_used

    except (json.JSONDecodeError, ValidationError) as e:
        error_msg = f"Error parseando o validando la respuesta del LLM: {e}. Respuesta: {response_text[:500]}..."
        error = FindingSchema(codigo_error="E902_JSON_PARSE_VALIDATION_ERROR", campo_con_error="llm_response", descripcion_hallazgo=error_msg)
        return None, [error], total_tokens_used
    except Exception as e:
        error_msg = f"Error inesperado en la utilidad LLM: {e}"
        logger.error(f"[{stage_name}] Item {item.temp_id}: {error_msg}", exc_info=True)
        error = FindingSchema(codigo_error="E999_UNEXPECTED_ERROR", campo_con_error="llm_call", descripcion_hallazgo=error_msg)
        return None, [error], total_tokens_used
