# app/llm/providers.py

from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Type, Tuple

from app.core.config import Settings
from .utils import make_retry

# Se instancia settings fuera de las clases para acceso global
# pero get_provider ahora crea instancias de clientes, que reciben settings
settings = Settings()
log = logging.getLogger("app.llm")

@dataclass
class LLMResponse:
    text: str
    model: str
    usage: Dict[str, int]
    extra: Dict[str, Any]
    success: bool = True # Añadido para indicar éxito de la llamada LLM
    error_message: Optional[str] = None # Mensaje de error si success es False

# ─── Plugin registry ─────────────────────────────────────────────────────────
_PROVIDER_REGISTRY: Dict[str, Type['BaseLLMClient']] = {} # Usar Type['BaseLLMClient'] para forward reference

def register_provider(name: str):
    def decorator(cls: Type['BaseLLMClient']):
        _PROVIDER_REGISTRY[name.lower()] = cls # Guarda la CLASE, no la instancia
        return cls
    return decorator

def get_provider(name: str) -> 'BaseLLMClient': # Retorna la instancia, no la clase
    try:
        client_cls = _PROVIDER_REGISTRY[name.lower()]
        return client_cls(settings) # Crea la instancia al solicitarla, pasando settings
    except KeyError:
        raise ValueError(f"Proveedor LLM no soportado: {name!r}")

# ─── Clase base (Template Method) ────────────────────────────────────────────
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
        kwargs: Optional[Dict[str, Any]] = None # kwargs ahora es un dict opcional
    ) -> LLMResponse:
        self.logger.debug("→ Generando %d mensajes", len(messages))
        kwargs = kwargs or {} # Asegurar que kwargs es un diccionario

        try:
            provider_resp = await self._retry(self._call)(messages, kwargs)
            return self._parse_response(provider_resp)
        except Exception as e: # Captura cualquier error durante la llamada o el parseo
            self.logger.error(f"Error durante la llamada LLM o el parseo de respuesta para {self.__class__.__name__}: {e}", exc_info=True)
            return LLMResponse(
                text="",
                model=kwargs.get("model", "unknown"), # Usar el modelo de kwargs si está
                usage={},
                extra={},
                success=False,
                error_message=str(e)
            )


    async def _call(self, messages: List[Dict[str, str]], kwargs: Dict[str, Any]) -> Any: # kwargs no es Any, es Dict
        raise NotImplementedError

    def _parse_response(self, provider_resp: Any) -> LLMResponse:
        raise NotImplementedError

# ─── Cliente OpenAI ──────────────────────────────────────────────────────────
from openai import AsyncOpenAI, APIError, RateLimitError, APITimeoutError, AuthenticationError, InvalidAPIKeyError # type: ignore

@register_provider("openai")
class OpenAIClient(BaseLLMClient):
    @classmethod
    def retry_exceptions(cls):
        return (RateLimitError, APIError, APITimeoutError, AuthenticationError, InvalidAPIKeyError) # Añadido APITimeoutError, AuthenticationError, InvalidAPIKeyError

    async def _call(self, messages: List[Dict[str, str]], kwargs: Dict[str, Any]) -> Any:
        client = AsyncOpenAI(
            base_url=self.settings.openai_base_url or None,
            api_key=self.settings.openai_api_key or None,
            timeout=self.settings.llm_request_timeout # Usar el timeout global
        )
        params = {
            "model": kwargs.pop("model", self.settings.llm_model), # kwarg tiene precedencia
            "messages": messages,
            "temperature": kwargs.pop("temperature", self.settings.llm_temperature),
            "max_tokens": kwargs.pop("max_tokens", self.settings.llm_max_tokens),
        }
        params.update(kwargs) # Añade cualquier otro kwarg restante
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
            success=True # Si llegamos aquí, fue un éxito de parseo
        )

# ─── Cliente OpenRouter ──────────────────────────────────────────────────────
# OpenRouter es API compatible con OpenAI, así que podemos heredar y ajustar base_url/api_key
@register_provider("openrouter")
class OpenRouterClient(OpenAIClient): # Heredamos de OpenAIClient por compatibilidad de API
    def __init__(self, settings: Settings):
        super().__init__(settings)
        # Sobreescribimos el cliente para usar la base_url y api_key de OpenRouter
        self._async_client = AsyncOpenAI(
            base_url=self.settings.openrouter_base_url,
            api_key=self.settings.openrouter_api_key,
            timeout=self.settings.llm_request_timeout
        )

    async def _call(self, messages: List[Dict[str, str]], kwargs: Dict[str, Any]) -> Any:
        # Aquí self._async_client ya está inicializado con la base/key de OpenRouter
        params = {
            "model": kwargs.pop("model", self.settings.llm_model),
            "messages": messages,
            "temperature": kwargs.pop("temperature", self.settings.llm_temperature),
            "max_tokens": kwargs.pop("max_tokens", self.settings.llm_max_tokens),
        }
        params.update(kwargs)
        return await self._async_client.chat.completions.create(**params)


# ─── Cliente Gemini / Google GenAI ───────────────────────────────────────────
import google.generativeai as genai
from google.generativeai.types import GenerateContentResponse
from google.api_core.exceptions import ResourceExhausted, InternalServerError, Aborted, DeadlineExceeded

@register_provider("gemini")
class GeminiClient(BaseLLMClient):
    @classmethod
    def retry_exceptions(cls):
        return (ResourceExhausted, InternalServerError, Aborted, DeadlineExceeded) # Añadido DeadlineExceeded

    def __init__(self, settings: Settings):
        super().__init__(settings)
        genai.configure(api_key=self.settings.google_api_key) # Configura la API key
        if self.settings.gemini_base_url: # Si hay una URL base específica
            genai.configure(client_options={'api_endpoint': self.settings.gemini_base_url})

    async def _call(self, messages: List[Dict[str, str]], kwargs: Dict[str, Any]) -> Any:
        # Convertir mensajes de formato OpenAI a formato Gemini si es necesario
        gemini_messages = []
        for msg in messages:
            # Gemini usa "role": "user" y "role": "model"
            role = "user" if msg["role"] == "user" else "model" # Ajustar si hay otros roles
            gemini_messages.append({"role": role, "parts": [msg["content"]]})

        model_name = kwargs.pop("model", self.settings.llm_model)

        generation_config = {
            "temperature": kwargs.pop("temperature", self.settings.llm_temperature),
            "max_output_tokens": kwargs.pop("max_tokens", self.settings.llm_max_tokens), # num_predict para max_tokens
        }

        model = genai.GenerativeModel(model_name=model_name)
        return await model.generate_content_async(
             gemini_messages,
             generation_config=generation_config,
             timeout=self.settings.llm_request_timeout,
             **kwargs # Pasar cualquier kwarg restante
        )


    def _parse_response(self, res: GenerateContentResponse) -> LLMResponse: # Type hint para Gemini response
        text_content = ""
        try:
            text_content = res.candidates[0].content.parts[0].text # Acceder a la respuesta de texto
        except (AttributeError, IndexError):
            self.logger.warning("No se pudo extraer texto de la respuesta de Gemini.")

        total_tokens = 0
        if res.usage_metadata:
             total_tokens = getattr(res.usage_metadata, 'total_token_count', 0)

        model_name = getattr(res, 'model', 'gemini-model') # El modelo puede estar en res.model o en los kwargs de la llamada

        return LLMResponse(
            text=text_content,
            model=model_name,
            usage={"prompt": getattr(res.usage_metadata, 'prompt_token_count', 0), "completion": getattr(res.usage_metadata, 'candidates_token_count', 0), "total": total_tokens}, # Gemini usage may be less granular
            extra={},
            success=True
        )

# ─── Cliente Ollama ───────────────────────────────────────────────────────────
import ollama # Asegúrate que ollama-python SDK está instalado

@register_provider("ollama")
class OllamaClient(BaseLLMClient):
    @classmethod
    def retry_exceptions(cls):
        return (ollama.ResponseError, ConnectionError, TimeoutError) # Añadido TimeoutError para asyncio.wait_for

    async def _call(self, messages: List[Dict[str, str]], kwargs: Dict[str, Any]) -> Any:
        host = self.settings.ollama_host
        client = ollama.AsyncClient(host=host)

        opts = {
            "temperature": kwargs.pop("temperature", self.settings.llm_temperature),
            "num_predict": kwargs.pop("max_tokens", self.settings.llm_max_tokens), # num_predict para max_tokens
        }
        kwargs.setdefault("options", {}).update(opts) # Asegura que opts se mergea en kwargs['options']

        chat_params = {
            "model": kwargs.pop("model", self.settings.llm_model),
            "messages": messages,
        }
        chat_params.update(kwargs) # mergea el resto de kwargs

        return await client.chat(**chat_params, timeout=self.settings.llm_request_timeout)


    def _parse_response(self, res: Any) -> LLMResponse:
        text_content = res.get("message", {}).get("content", "")
        prompt_tokens = res.get("prompt_eval_count", 0)
        completion_tokens = res.get("eval_count", 0)
        total_tokens = prompt_tokens + completion_tokens
        model_name = res.get("model", "ollama-model") # El modelo está en res['model']

        return LLMResponse(
            text=text_content,
            model=model_name,
            usage={"prompt": prompt_tokens, "completion": completion_tokens, "total": total_tokens},
            extra={},
            success=True
        )


# ─── Función pública (API compatible) ────────────────────────────────────────
async def generate_response(
    messages: List[Dict[str, str]],
    model: Optional[str] = None, # Parámetro 'model' ahora explícito
    temperature: Optional[float] = None, # Parámetro 'temperature' explícito
    max_tokens: Optional[int] = None, # Parámetro 'max_tokens' explícito
    provider: Optional[str] = None,
    **kwargs: Any, # Captura el resto de parámetros específicos del proveedor
) -> LLMResponse:
    """
    Genera una respuesta usando el proveedor LLM indicado (o el por defecto en settings.llm_provider).
    Permite sobrescribir model, temperature, max_tokens por llamada.
    """
    prov = provider or settings.llm_provider
    client = get_provider(prov)

    # Construir el diccionario de kwargs a pasar al cliente del proveedor
    # Prioridad: parámetros explícitos de la función > kwargs extra > settings globales
    call_kwargs = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    # Eliminar None values para que no sobrescriban los defaults de settings/proveedor si no se especifican
    call_kwargs = {k: v for k, v in call_kwargs.items() if v is not None}

    # Mergear con los kwargs explícitos del usuario (**)
    call_kwargs.update(kwargs)

    return await client.generate_response(messages, call_kwargs)
