# app/llm/providers.py

from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Type, Tuple

from app.core.config import settings, Settings
from .utils import make_retry

log = logging.getLogger("app.llm")

@dataclass
class LLMResponse:
    text: str
    model: str
    usage: Dict[str, int]
    extra: Dict[str, Any]
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
        messages: List[Dict[str, str]],
        **kwargs: Any
    ) -> LLMResponse:
        self.logger.debug("→ Generando %d mensajes", len(messages))
        try:
            return await self._retry(self._call)(messages, **kwargs)
        except Exception as e:
            self.logger.error(f"Error durante la llamada LLM para {self.__class__.__name__}: {e}", exc_info=True)
            return LLMResponse(
                text="",
                model=kwargs.get("model", "unknown"),
                usage={},
                extra={},
                success=False,
                error_message=str(e)
            )

    async def _call(self, messages: List[Dict[str, Any]], **kwargs: Any) -> LLMResponse:
        raise NotImplementedError

from openai import AsyncOpenAI, APIError, RateLimitError, APITimeoutError, AuthenticationError

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
        params.update(kwargs)

        res = await client.chat.completions.create(**params)
        usage = getattr(res, "usage", None)
        return LLMResponse(
            text=res.choices[0].message.content or "",
            model=res.model or params["model"],
            usage={
                "prompt": getattr(usage, "prompt_tokens", 0),
                "completion": getattr(usage, "completion_tokens", 0),
                "total": getattr(usage, "total_tokens", 0),
            },
            extra={"finish_reason": res.choices[0].finish_reason},
            success=True
        )

from google import genai
from google.genai import types
from google.api_core.exceptions import ResourceExhausted, InternalServerError, Aborted, DeadlineExceeded, GoogleAPICallError

@register_provider("gemini")
class GeminiClient(BaseLLMClient):
    @classmethod
    def retry_exceptions(cls):
        return (ResourceExhausted, InternalServerError, Aborted, DeadlineExceeded, GoogleAPICallError)

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.client = genai.Client(api_key=settings.google_api_key)

    async def _call(self, messages: List[Dict[str, Any]], **kwargs: Any) -> LLMResponse:
        # Busca el primer mensaje con rol 'system' y lo guarda.
        system_instruction = next((msg["content"] for msg in messages if msg["role"] == "system"), None)

        # Filtra para obtener solo los mensajes de rol 'user'.
        user_parts = [types.Part(text=msg["content"]) for msg in messages if msg["role"] == "user"]
        gemini_contents = [types.UserContent(parts=user_parts)] if user_parts else []

        config_params = {
            "temperature": kwargs.pop("temperature", self.settings.llm_temperature),
            "max_output_tokens": kwargs.pop("max_tokens", self.settings.llm_max_tokens),
            "response_mime_type": "application/json",
            "safety_settings": [
                types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
                types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
                types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
                types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
            ],
            "system_instruction": system_instruction,
        }

        generation_config = types.GenerateContentConfig(**config_params)
        model_name = kwargs.pop("model", self.settings.llm_model)

        res = await self.client.aio.models.generate_content(
            model=model_name,
            contents=gemini_contents,
            config=generation_config,
        )

        self.logger.debug(f"Raw Gemini Response: {res}")

        text_content = ""
        success = True
        error_message = None

        try:
            if not res.candidates:
                error_message = "LLM no devolvió candidatos."
                success = False
            else:
                candidate = res.candidates[0]
                # Esta parte para extraer el texto es robusta y se mantiene.
                if candidate.content and candidate.content.parts:
                    text_content = "".join(part.text for part in candidate.content.parts if hasattr(part, "text"))

                if not text_content:
                    finish_reason = getattr(candidate, 'finish_reason', 'UNKNOWN')
                    # Si el modelo fue bloqueado por seguridad, lo indicará aquí.
                    if finish_reason == 'SAFETY':
                         safety_ratings = [str(rating) for rating in getattr(candidate, 'safety_ratings', [])]
                         error_message = f"LLM response blocked due to safety settings. Finish Reason: {finish_reason}. Ratings: {', '.join(safety_ratings)}"
                    else:
                         error_message = f"LLM response contained no usable text content. Finish Reason: {finish_reason}"
                    success = False

        except Exception as e:
            success = False
            error_message = f"Error crítico al parsear la respuesta de Gemini: {e}"
            self.logger.error(error_message, exc_info=True)

        usage_metadata = getattr(res, 'usage_metadata', None)
        usage = {
            "prompt": getattr(usage_metadata, 'prompt_token_count', 0),
            "completion": getattr(usage_metadata, 'candidates_token_count', 0),
            "total": getattr(usage_metadata, 'total_token_count', 0),
        }

        return LLMResponse(
            text=text_content,
            model=model_name,
            usage=usage,
            extra={},
            success=success,
            error_message=error_message
        )


# --- Unified API ---
async def generate_response(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    provider: Optional[str] = None,
    **kwargs: Any
) -> LLMResponse:
    prov = provider or settings.llm_provider
    client = get_provider(prov)

    # Se eliminan los kwargs que ya se manejan para no pasarlos dos veces
    kwargs.pop("model", None)
    kwargs.pop("temperature", None)
    kwargs.pop("max_tokens", None)
    kwargs.pop("provider", None)

    return await client.generate_response(
        messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs
    )
