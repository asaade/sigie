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

# ─── Plugin registry ─────────────────────────────────────────────────────────
_PROVIDER_REGISTRY: Dict[str, BaseLLMClient] = {}

def register_provider(name: str):
    def decorator(cls: Type[BaseLLMClient]):
        instance = cls(settings)
        _PROVIDER_REGISTRY[name.lower()] = instance
        return cls
    return decorator

def get_provider(name: str) -> BaseLLMClient:
    try:
        return _PROVIDER_REGISTRY[name.lower()]
    except KeyError:
        raise ValueError(f"Proveedor LLM no soportado: {name!r}")

# ─── Clase base (Template Method) ────────────────────────────────────────────
class BaseLLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.logger = logging.getLogger(f"app.llm.{self.__class__.__name__}")
        # crea decorador de retry según excepciones específicas
        self._retry = make_retry(self.retry_exceptions(), settings.llm_max_retries)

    @classmethod
    def retry_exceptions(cls) -> Tuple[Type[Exception], ...]:
        """Cada cliente define a qué excepciones hace retry."""
        return ()

    async def generate_response(
        self,
        messages: List[Dict[str, str]],
        kwargs: Any
    ) -> LLMResponse:
        self.logger.debug("→ Generando %d mensajes", len(messages))
        provider_resp = await self._retry(self._call)(messages, kwargs)
        return self._parse_response(provider_resp)

    async def _call(self, messages: List[Dict[str, str]], kwargs: Any) -> Any:
        """Subclases lo implementan para llamar al SDK del proveedor."""
        raise NotImplementedError

    def _parse_response(self, provider_resp: Any) -> LLMResponse:
        """Convierte la respuesta del proveedor en nuestro LLMResponse."""
        raise NotImplementedError

# ─── Cliente OpenAI ──────────────────────────────────────────────────────────
from openai import AsyncOpenAI, APIError, RateLimitError  # type: ignore

@register_provider("openai")
class OpenAIClient(BaseLLMClient):
    @classmethod
    def retry_exceptions(cls):
        return (RateLimitError, APIError)

    async def _call(self, messages, kwargs):
        client = AsyncOpenAI(
            base_url=self.settings.openai_base_url or None,
            api_key=self.settings.openai_api_key or None,
        )
        params = {
            "model": self.settings.llm_model,
            "messages": messages,
            "temperature": self.settings.llm_temperature,
            "max_tokens": self.settings.llm_max_tokens,
        }
        params.update(kwargs)
        return await client.chat.completions.create(params)

    def _parse_response(self, res) -> LLMResponse:
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
        )

# ─── Cliente Gemini / Google GenAI ───────────────────────────────────────────
# (similar al de arriba; omitido por brevedad, pero sigue mismo patrón)
# @register_provider("gemini") class GeminiClient(BaseLLMClient): ...

# ─── Cliente Ollama ───────────────────────────────────────────────────────────
import ollama

@register_provider("ollama")
class OllamaClient(BaseLLMClient):
    @classmethod
    def retry_exceptions(cls):
        # ConnectionError + ResponseError
        return (ollama.ResponseError, ConnectionError)

    async def _call(self, messages, kwargs):
        host = getattr(self.settings, "ollama_host", "http://172.17.0.1:11434")
        client = ollama.AsyncClient(host=host)

        opts = {
            "temperature": self.settings.llm_temperature,
            "num_predict": self.settings.llm_max_tokens,
        }
        opts.update(kwargs.pop("options", {}))

        # ---- timeout manual ----------------------------------------------
        import asyncio
        TIMEOUT = getattr(self.settings, "llm_timeout", 30)  # añade field en Settings si quieres

        return await asyncio.wait_for(
            client.chat(
                model=self.settings.llm_model,
                messages=messages,
                options=opts,
                kwargs,
            ),
            timeout=TIMEOUT,
        )

# ─── Función pública (API compatible) ────────────────────────────────────────
async def generate_response(
    messages: List[Dict[str, str]],
    provider: Optional[str] = None,
    kwargs: Any,
) -> LLMResponse:
    """
    Genera una respuesta usando el proveedor LLM indicado (o el por defecto
    en settings.llm_provider). Mantiene la misma firma que antes.
    """
    prov = provider or settings.llm_provider
    client = get_provider(prov)
    return await client.generate_response(messages, kwargs)
