# app/llm/providers.py

from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Type, Tuple

from app.core.config import Settings
from .utils import make_retry

settings = Settings()
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
        kwargs: Optional[Dict[str, Any]] = None
    ) -> LLMResponse:
        self.logger.debug("→ Generando %d mensajes", len(messages))
        kwargs = kwargs or {}

        try:
            provider_resp = await self._retry(self._call)(messages, kwargs)
            return self._parse_response(provider_resp)
        except Exception as e:
            self.logger.error(f"Error durante la llamada LLM o el parseo de respuesta para {self.__class__.__name__}: {e}", exc_info=True)
            return LLMResponse(
                text="",
                model=kwargs.get("model", "unknown"),
                usage={},
                extra={},
                success=False,
                error_message=str(e)
            )

    async def _call(self, messages: List[Dict[str, str]], kwargs: Dict[str, Any]) -> Any:
        raise NotImplementedError

    def _parse_response(self, provider_resp: Any) -> LLMResponse:
        raise NotImplementedError

from openai import AsyncOpenAI, APIError, RateLimitError, APITimeoutError, AuthenticationError, InvalidAPIKeyError

@register_provider("openai")
class OpenAIClient(BaseLLMClient):
    @classmethod
    def retry_exceptions(cls):
        return (RateLimitError, APIError, APITimeoutError, AuthenticationError, InvalidAPIKeyError)

    async def _call(self, messages: List[Dict[str, str]], kwargs: Dict[str, Any]) -> Any:
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
        return await client.chat.completions.create(**params)

    def _parse_response(self, res: Any) -> LLMResponse:
        usage = getattr(res, "usage", None)
        return LLMResponse(
            text=res.choices[0].message.content or "",
            model=res.model,
            usage={
                "prompt": getattr(usage, "prompt_tokens", 0),
                "completion": getattr(usage, "completion_tokens", 0),
                "total": getattr(usage, "total_tokens", 0),
            },
            extra={"finish_reason": res.choices[0].finish_reason},
            success=True
        )

@register_provider("openrouter")
class OpenRouterClient(OpenAIClient):
    def __init__(self, settings: Settings):
        super().__init__(settings)
        self._async_client = AsyncOpenAI(
            base_url=self.settings.openrouter_base_url,
            api_key=self.settings.openrouter_api_key,
            timeout=self.settings.llm_request_timeout
        )

    async def _call(self, messages: List[Dict[str, str]], kwargs: Dict[str, Any]) -> Any:
        params = {
            "model": kwargs.pop("model", self.settings.llm_model),
            "messages": messages,
            "temperature": kwargs.pop("temperature", self.settings.llm_temperature),
            "max_tokens": kwargs.pop("max_tokens", self.settings.llm_max_tokens),
        }
        params.update(kwargs)
        return await self._async_client.chat.completions.create(**params)

from google import genai
from google.genai import types
from google.generativeai.types import GenerateContentResponse
from google.api_core.exceptions import ResourceExhausted, InternalServerError, Aborted, DeadlineExceeded, GoogleAPICallError

@register_provider("gemini")
class GeminiClient(BaseLLMClient):
    @classmethod
    def retry_exceptions(cls):
        return (ResourceExhausted, InternalServerError, Aborted, DeadlineExceeded, GoogleAPICallError)

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self._client = genai.Client(api_key=self.settings.google_api_key)

        if self.settings.gemini_base_url:
            self.logger.warning("gemini_base_url not directly supported by genai.Client() via api_endpoint in this way. Check new SDK docs.")

    async def _call(self, messages: List[Dict[str, str]], kwargs: Dict[str, Any]) -> Any:
        system_instruction_content = ""
        gemini_contents = []
        for msg in messages:
            if msg["role"] == "system":
                system_instruction_content = msg["content"]
            elif msg["role"] == "user":
                gemini_contents.append(msg["content"])
            elif msg["role"] == "model":
                gemini_contents.append({"role": "model", "parts": [msg["content"]]})

        model_name = kwargs.pop("model", self.settings.llm_model)

        generate_content_config_params = {
            "temperature": kwargs.pop("temperature", self.settings.llm_temperature),
            "max_output_tokens": kwargs.pop("max_tokens", self.settings.llm_max_tokens),
        }

        generate_content_config = types.GenerateContentConfig(
            **generate_content_config_params,
            system_instruction=system_instruction_content if system_instruction_content else None,
        )

        return await self._client.aio.models.generate_content(
             model=model_name,
             contents=gemini_contents,
             config=generate_content_config,
             timeout=self.settings.llm_request_timeout,
             **kwargs
        )

    def _parse_response(self, res: GenerateContentResponse) -> LLMResponse:
        text_content = ""
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0

        try:
            text_content = res.text
            if not text_content and res.candidates:
                text_content = res.candidates[0].content.parts[0].text
        except (AttributeError, IndexError):
            self.logger.warning("No se pudo extraer texto de la respuesta de Gemini.")

        if res.usage_metadata:
             total_tokens = getattr(res.usage_metadata, 'total_token_count', 0)
             prompt_tokens = getattr(res.usage_metadata, 'prompt_token_count', 0)
             completion_tokens = getattr(res.usage_metadata, 'candidates_token_count', 0)

        model_name = getattr(res, 'model', 'gemini-model')

        return LLMResponse(
            text=text_content,
            model=model_name,
            usage={"prompt": prompt_tokens, "completion": completion_tokens, "total": total_tokens},
            extra={},
            success=True
        )

import ollama

@register_provider("ollama")
class OllamaClient(BaseLLMClient):
    @classmethod
    def retry_exceptions(cls):
        return (ollama.ResponseError, ConnectionError, TimeoutError)

    async def _call(self, messages: List[Dict[str, str]], kwargs: Dict[str, Any]) -> Any:
        host = self.settings.ollama_host
        client = ollama.AsyncClient(host=host)

        opts = {
            "temperature": kwargs.pop("temperature", self.settings.llm_temperature),
            "num_predict": kwargs.pop("max_tokens", self.settings.llm_max_tokens),
        }
        kwargs.setdefault("options", {}).update(opts)

        chat_params = {
            "model": kwargs.pop("model", self.settings.llm_model),
            "messages": messages,
        }
        chat_params.update(kwargs)

        return await client.chat(**chat_params, timeout=self.settings.llm_request_timeout)


    def _parse_response(self, res: Any) -> LLMResponse:
        text_content = res.get("message", {}).get("content", "")
        prompt_tokens = res.get("prompt_eval_count", 0)
        completion_tokens = res.get("eval_count", 0)
        total_tokens = prompt_tokens + completion_tokens
        model_name = res.get("model", "ollama-model")

        return LLMResponse(
            text=text_content,
            model=model_name,
            usage={"prompt": prompt_tokens, "completion": completion_tokens, "total": total_tokens},
            extra={},
            success=True
        )

async def generate_response(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    provider: Optional[str] = None,
    **kwargs: Any,
) -> LLMResponse:
    """
    Genera una respuesta usando el proveedor LLM indicado (o el por defecto en settings.llm_provider).
    Permite sobrescribir model, temperature, max_tokens por llamada.
    """
    prov = provider or settings.llm_provider
    client = get_provider(prov)

    call_kwargs = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    call_kwargs = {k: v for k, v in call_kwargs.items() if v is not None}

    call_kwargs.update(kwargs)

    return await client.generate_response(messages, call_kwargs)
