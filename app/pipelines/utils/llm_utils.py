# app/pipelines/utils/llm_utils.py

from __future__ import annotations
import logging
import json
from typing import Tuple, List, Optional, Type, Any, Dict
from pydantic import BaseModel, ValidationError

# Dependencias del sistema
from app.llm.providers import generate_response
from app.schemas.item_schemas import FindingSchema
from app.schemas.models import Item
from app.prompts import load_prompt
from app.core.config import settings
from .parsers import build_prompt_messages
from .search_tools import WebSearchTool

logger = logging.getLogger(__name__)

async def call_llm_and_parse_json_result(
    prompt_name: str,
    user_input_content: str,
    stage_name: str,
    item: Item,
    ctx: Dict[str, Any], # <-- CORRECCIÓN: Se renombró de '_ctx' a 'ctx'
    expected_schema: Optional[Type[BaseModel]] = None,
    **kwargs,
) -> Tuple[Optional[BaseModel | str], Optional[List[FindingSchema]], int]:

    total_tokens_used = 0
    response_text = ""
    try:
        prompt_data = load_prompt(prompt_name)

        if isinstance(prompt_data, dict):
            system_template = prompt_data.get("system_message", "")
            user_prompt_template = prompt_data.get("content", "")
        else:
            system_template = ""
            user_prompt_template = prompt_data

        if not user_prompt_template:
            raise ValueError(f"No se pudo cargar una plantilla de prompt de usuario válida desde '{prompt_name}'.")

        messages = build_prompt_messages(
            system_template=system_template,
            user_message_template=user_prompt_template,
            payload=user_input_content
        )

        provider_name = kwargs.pop("provider", settings.llm_provider)
        model_name = kwargs.pop("model", settings.llm_model)

        llm_response = await generate_response(messages=messages, provider=provider_name, model=model_name, **kwargs)
        tokens_used = llm_response.usage.get("total", 0)
        total_tokens_used += tokens_used
        item.token_usage += tokens_used

        if not llm_response.success:
            error_msg = llm_response.error_message or "Error desconocido del proveedor LLM."
            error = FindingSchema(codigo_error="E905_LLM_CALL_FAILED", campo_con_error="llm_response", descripcion_hallazgo=error_msg)
            return None, [error], total_tokens_used

        response_text = llm_response.text
        if not response_text:
            error = FindingSchema(codigo_error="E904_LLM_NO_RESPONSE", campo_con_error="llm_response", descripcion_hallazgo="El LLM no devolvió contenido de texto.")
            return None, [error], total_tokens_used

        if expected_schema is None:
            return response_text, None, total_tokens_used

        cleaned_json_str = response_text.strip().removeprefix("```json").removesuffix("```").strip()
        validated_obj = expected_schema.model_validate_json(cleaned_json_str)
        return validated_obj, None, total_tokens_used

    except (json.JSONDecodeError, ValidationError) as e:
        error_msg = f"Error parseando o validando la respuesta del LLM: {e}. Respuesta: {response_text[:500]}..."
        error = FindingSchema(codigo_error="E904_LLM_RESPONSE_FORMAT_ERROR", campo_con_error="llm_response", descripcion_hallazgo=error_msg)
        return None, [error], total_tokens_used
    except Exception as e:
        error_msg = f"Error inesperado en la utilidad LLM: {e}"
        logger.error(f"[{stage_name}] Item {item.temp_id}: {error_msg}", exc_info=True)
        error = FindingSchema(codigo_error="E999_UNEXPECTED_ERROR", campo_con_error="llm_call", descripcion_hallazgo=error_msg)
        return None, [error], total_tokens_used


async def call_llm_with_tools(
    prompt_name: str,
    user_input_content: str,
    stage_name: str,
    item: Item,
    ctx: Dict[str, Any], # <-- CORRECCIÓN: Se renombró de '_ctx' a 'ctx'
    expected_schema: Type[BaseModel],
    max_iterations: int = 5,
    **kwargs,
) -> Tuple[Optional[BaseModel], Optional[List[FindingSchema]], int]:

    total_tokens_used = 0
    try:
        prompt_data = load_prompt(prompt_name)

        if isinstance(prompt_data, dict):
            system_template = prompt_data.get("system_message", "")
            user_prompt_template = prompt_data.get("content", "")
        else:
            system_template = ""
            user_prompt_template = prompt_data

        if not user_prompt_template:
            raise ValueError(f"No se pudo cargar una plantilla de prompt de usuario válida desde '{prompt_name}'.")

        messages: List[Dict[str, Any]] = build_prompt_messages(
            system_template=system_template,
            user_message_template=user_prompt_template,
            payload=user_input_content
        )

        search_tool = WebSearchTool()
        tools = [search_tool.get_tool_spec()]

        for i in range(max_iterations):
            logger.info(f"[{stage_name}] Item {item.temp_id}: Iteración del agente {i+1}/{max_iterations}")

            llm_response = await generate_response(messages=messages, tools=tools, **kwargs)
            tokens_used = llm_response.usage.get("total", 0)
            total_tokens_used += tokens_used
            item.token_usage += tokens_used

            if not llm_response.success:
                raise Exception(f"La llamada al LLM falló: {llm_response.error_message}")

            response_message: Dict[str, Any] = {"role": "assistant", "content": llm_response.text}

            if llm_response.tool_calls:
                response_message["tool_calls"] = llm_response.tool_calls
                messages.append(response_message)

                tool_call = llm_response.tool_calls[0]
                if tool_call.get('function', {}).get('name') == 'web_search':
                    arguments = json.loads(tool_call.get('function', {}).get('arguments', '{}'))
                    query = arguments.get('query', '')
                    logger.info(f"[{stage_name}] Item {item.temp_id}: Ejecutando búsqueda: '{query}'")
                    search_results_str = await search_tool(query=query)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.get('id'),
                        "name": tool_call.get('function', {}).get('name'),
                        "content": search_results_str
                    })
                continue

            else:
                messages.append(response_message)
                cleaned_json_str = llm_response.text.strip().removeprefix("```json").removesuffix("```").strip()
                validated_obj = expected_schema.model_validate_json(cleaned_json_str)
                return validated_obj, None, total_tokens_used

        error = FindingSchema(codigo_error="E906_AGENT_LOOP_EXCEEDED", campo_con_error="llm_agent", descripcion_hallazgo="El agente superó el número máximo de iteraciones sin llegar a una respuesta final.")
        return None, [error], total_tokens_used

    except Exception as e:
        error_msg = f"Error inesperado en el agente con herramientas: {e}"
        logger.error(f"[{stage_name}] Item {item.temp_id}: {error_msg}", exc_info=True)
        error = FindingSchema(codigo_error="E999_UNEXPECTED_ERROR", campo_con_error="llm_agent_call", descripcion_hallazgo=error_msg)
        return None, [error], total_tokens_used
