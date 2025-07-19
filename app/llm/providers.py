# app/llm/providers.py

from __future__ import annotations
import logging
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type, Tuple

from app.core.config import settings, Settings
from .utils import make_retry

# Dependencias de los proveedores de LLM
from openai import AsyncOpenAI, APIError, RateLimitError, APITimeoutError, AuthenticationError
from google import genai
from google.genai import types
from google.api_core.exceptions import ResourceExhausted, InternalServerError, Aborted, DeadlineExceeded, GoogleAPICallError

log = logging.getLogger("app.llm")

@dataclass
class LLMResponse:
    text: str
    model: str
    usage: Dict[str, int]
    tool_calls: Optional[List[Dict[str, Any]]] = None
    extra: Dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error_message: Optional[str] = None

_PROVIDER_REGISTRY: Dict[str, Type['BaseLLMClient']] = {}

def register_provider(name: str):
    def decorator(cls: Type['BaseLLMClient']):
        _PROVIDER_REGISTRY[name.lower()] = cls
        return cls
    return decorator

def get_provider(name: str) -> 'BaseLLMClient':
    try:
        client_cls = _PROVIDER_REGISTRY[name.lower()]
        return client_cls(settings)
    except KeyError:
        raise ValueError(f"Proveedor LLM no soportado: {name!r}")

class BaseLLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.logger = logging.getLogger(f"app.llm.{self.__class__.__name__}")
        self._retry = make_retry(self.retry_exceptions(), settings.llm_max_retries)

    @classmethod
    def retry_exceptions(cls) -> Tuple[Type[Exception], ...]:
        return ()

    async def generate_response(
        self,
        messages: List[Dict[str, Any]],
        **kwargs: Any
    ) -> LLMResponse:
        self.logger.debug("→ Generando %d mensajes", len(messages))
        try:
            return await self._retry(self._call)(messages, **kwargs)
        except Exception as e:
            self.logger.error(f"Error durante la llamada LLM para {self.__class__.__name__}: {e}", exc_info=True)
            return LLMResponse(
                text="", model=kwargs.get("model", "unknown"),
                usage={}, success=False, error_message=str(e)
            )

    async def _call(self, messages: List[Dict[str, Any]], **kwargs: Any) -> LLMResponse:
        raise NotImplementedError

@register_provider("openai")
class OpenAIClient(BaseLLMClient):
    @classmethod
    def retry_exceptions(cls):
        return (RateLimitError, APIError, APITimeoutError, AuthenticationError)

    async def _call(self, messages: List[Dict[str, Any]], **kwargs: Any) -> LLMResponse:
        client = AsyncOpenAI(
            base_url=self.settings.openai_base_url or None,
            api_key=self.settings.openai_api_key or None,
            timeout=self.settings.llm_request_timeout
        )
        params = {
            "model": kwargs.pop("model", self.settings.llm_model),
            "messages": messages,
            "temperature": kwargs.pop("temperature", self.settings.llm_temperature),
            "max_tokens": kwargs.pop("max_tokens", self.settings.llm_max_tokens),
        }
        if kwargs.get("tools"):
            params["tools"] = kwargs.get("tools")
        params.update(kwargs)

        res = await client.chat.completions.create(**params)
        choice = res.choices[0]
        usage = getattr(res, "usage", None)

        tool_calls = None
        if choice.message.tool_calls:
            tool_calls = [
                {
                    "id": tc.id, "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                } for tc in choice.message.tool_calls
            ]

        return LLMResponse(
            text=choice.message.content or "", model=res.model or params["model"],
            usage={
                "prompt": getattr(usage, "prompt_tokens", 0),
                "completion": getattr(usage, "completion_tokens", 0),
                "total": getattr(usage, "total_tokens", 0),
            },
            tool_calls=tool_calls, extra={"finish_reason": choice.finish_reason}, success=True
        )

@register_provider("gemini")
class GeminiClient(BaseLLMClient):
    @classmethod
    def retry_exceptions(cls):
        return (ResourceExhausted, InternalServerError, Aborted, DeadlineExceeded, GoogleAPICallError)

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.client = genai.Client(api_key=settings.google_api_key)

    async def _call(self, messages: List[Dict[str, Any]], **kwargs: Any) -> LLMResponse:
        system_instruction = next((msg.get("content") for msg in messages if msg.get("role") == "system"), None)

        gemini_contents = []
        for msg in messages:
            role = msg.get("role")
            if role == "user":
                gemini_contents.append(types.Content(parts=[types.Part(text=msg.get("content", ""))]))
            elif role == "tool":
                gemini_contents.append(types.Content(
                    parts=[types.Part(function_response=types.FunctionResponse(name=msg.get("name", ""), response={"content": msg.get("content", "")}))]
                ))
            elif role == "assistant" and msg.get("tool_calls"):
                 tool_calls = msg.get("tool_calls", [])
                 tool_calls_parts = []
                 for tc in tool_calls:
                     function_call = tc.get('function', {})
                     if function_call:
                         args = json.loads(function_call.get('arguments', '{}'))
                         tool_calls_parts.append(
                             types.Part(function_call=types.FunctionCall(name=function_call.get('name'), args=args))
                         )
                 if tool_calls_parts:
                    gemini_contents.append(types.Content(parts=tool_calls_parts, role="model"))

        config_params = {
            "temperature": kwargs.pop("temperature", self.settings.llm_temperature),
            "max_output_tokens": kwargs.pop("max_tokens", self.settings.llm_max_tokens),
            "safety_settings": [
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
            ],
        }
        if system_instruction:
            config_params["system_instruction"] = types.Content(parts=[types.Part(text=system_instruction)])

        # --- INICIO DE LA CORRECCIÓN ---
        # Bloque defensivo para traducir el formato de herramientas genérico al de Gemini.
        tools = kwargs.get("tools")
        if tools:
            gemini_tools = []
            try:
                for tool_spec in tools:
                    if not isinstance(tool_spec, dict): continue

                    if tool_spec.get("type") == "function":
                        func_data = tool_spec.get("function")
                        if not isinstance(func_data, dict): continue

                        name = func_data.get("name")
                        description = func_data.get("description")
                        parameters = func_data.get("parameters")

                        if name and description and parameters:
                            func_declaration = types.FunctionDeclaration(
                                name=name,
                                description=description,
                                parameters=parameters
                            )
                            gemini_tools.append(types.Tool(function_declarations=[func_declaration]))

                if gemini_tools:
                    config_params["tools"] = gemini_tools
            except Exception as e:
                self.logger.error(f"Error fatal durante la conversión de formato de la herramienta: {e}", exc_info=True)
                return LLMResponse(
                    text="", model=kwargs.get("model", "unknown"),
                    usage={}, success=False, error_message=f"No se pudieron convertir las herramientas para Gemini: {e}"
                )
        # --- FIN DE LA CORRECCIÓN ---

        generation_config = types.GenerateContentConfig(**config_params)
        model_name = kwargs.pop("model", self.settings.llm_model)

        res = await self.client.aio.models.generate_content(
            model=model_name,
            contents=gemini_contents,
            config=generation_config
        )

        self.logger.debug(f"Raw Gemini Response: {res}")

        text_content = ""
        tool_calls = None
        success = True
        error_message = None

        try:
            candidate = res.candidates[0]
            if candidate.content and candidate.content.parts:
                for part in candidate.content.parts:
                    if hasattr(part, "text") and part.text:
                        text_content += part.text
                    if hasattr(part, "function_call"):
                        if not tool_calls: tool_calls = []
                        fc = part.function_call
                        tool_calls.append({
                            "id": str(uuid.uuid4()),
                            "type": "function",
                            "function": {"name": getattr(fc, 'name', ''), "arguments": json.dumps(dict(getattr(fc, 'args', {})))},
                        })

            if not text_content and not tool_calls:
                finish_reason_enum = getattr(candidate, 'finish_reason', None)
                finish_reason = finish_reason_enum.name if finish_reason_enum else "UNKNOWN"

                if finish_reason == 'SAFETY':
                     safety_ratings = [str(rating) for rating in getattr(candidate, 'safety_ratings', [])]
                     error_message = f"LLM response blocked due to safety settings. Ratings: {', '.join(safety_ratings)}"
                else:
                     error_message = f"LLM response contained no usable content. Finish Reason: {finish_reason}"
                success = False
        except (IndexError, AttributeError) as e:
            success = False
            error_message = f"Error crítico al parsear la respuesta de Gemini (posiblemente vacía o bloqueada): {e}"
            self.logger.error(f"{error_message} | Raw Response: {res}", exc_info=True)

        usage_metadata = getattr(res, 'usage_metadata', None)
        usage = {
            "prompt": getattr(usage_metadata, 'prompt_token_count', 0) if usage_metadata else 0,
            "completion": getattr(usage_metadata, 'candidates_token_count', 0) if usage_metadata else 0,
            "total": getattr(usage_metadata, 'total_token_count', 0) if usage_metadata else 0,
        }

        return LLMResponse(
            text=text_content, model=model_name, usage=usage,
            tool_calls=tool_calls, success=success, error_message=error_message
        )

async def generate_response(
    messages: List[Dict[str, Any]],
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    provider: Optional[str] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    **kwargs: Any
) -> LLMResponse:
    prov = provider or settings.llm_provider
    client = get_provider(prov)

    kwargs.pop("model", None)
    kwargs.pop("temperature", None)
    kwargs.pop("max_tokens", None)
    kwargs.pop("provider", None)

    return await client.generate_response(
        messages, model=model, temperature=temperature,
        max_tokens=max_tokens, tools=tools, **kwargs
    )
