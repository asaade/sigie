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

    def _clean_kwargs(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        kwargs.pop("prompt", None)
        kwargs.pop("provider", None)
        return kwargs

    async def generate_response(
        self,
        messages: List[Dict[str, str]],
        kwargs: Optional[Dict[str, Any]] = None
    ) -> LLMResponse:
        self.logger.debug("→ Generando %d mensajes", len(messages))
        kwargs = kwargs or {}

        try:
            cleaned_kwargs = self._clean_kwargs(kwargs.copy())
            provider_resp = await self._retry(self._call)(messages, cleaned_kwargs)
            return self._parse_response(provider_resp, model_name=kwargs.get("model", "unknown"))
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

    async def _call(self, messages: List[Dict[str, Any]], kwargs: Dict[str, Any]) -> Any:
        raise NotImplementedError

    def _parse_response(self, provider_resp: Any, model_name: str) -> LLMResponse:
        raise NotImplementedError

from openai import AsyncOpenAI, APIError, RateLimitError, APITimeoutError, AuthenticationError

@register_provider("openai")
class OpenAIClient(BaseLLMClient):
    @classmethod
    def retry_exceptions(cls):
        return (RateLimitError, APIError, APITimeoutError, AuthenticationError)

    async def _call(self, messages: List[Dict[str, Any]], kwargs: Dict[str, Any]) -> Any:
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

    def _parse_response(self, res: Any, model_name: str) -> LLMResponse:
        usage = getattr(res, "usage", None)
        return LLMResponse(
            text=res.choices[0].message.content or "",
            model=res.model or model_name,
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

    async def _call(self, messages: List[Dict[str, Any]], kwargs: Dict[str, Any]) -> Any:
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
from google.api_core.exceptions import ResourceExhausted, InternalServerError, Aborted, DeadlineExceeded, GoogleAPICallError

@register_provider("gemini")
class GeminiClient(BaseLLMClient):
    @classmethod
    def retry_exceptions(cls):
        return (ResourceExhausted, InternalServerError, Aborted, DeadlineExceeded, GoogleAPICallError)

    def __init__(self, settings: Settings):
        super().__init__(settings)
        # Initialize the client as shown in README.md
        # This client object will then expose .models (sync) and .aio (async)
        self.client = genai.Client(api_key=self.settings.google_api_key)

    async def _call(self, messages: List[Dict[str, Any]], kwargs: Dict[str, Any]) -> Any:
        # Extract system instruction and user content separately
        system_instruction_content = next((msg["content"] for msg in messages if msg["role"] == "system"), None)

        # Convert user messages to types.Part explicitly, as per README examples
        user_parts = [types.Part(text=msg["content"]) for msg in messages if msg["role"] == "user"]

        # Combine user parts into a single types.UserContent as per README.md examples
        if user_parts:
            gemini_contents = [types.UserContent(parts=user_parts)]
        else:
            gemini_contents = []

        model_name = kwargs.pop("model", self.settings.llm_model)

        config_params = {
            "temperature": kwargs.pop("temperature", self.settings.llm_temperature),
            "max_output_tokens": kwargs.pop("max_tokens", self.settings.llm_max_tokens),
            "system_instruction": system_instruction_content # Pass system_instruction here
        }
        config_params = {k: v for k, v in config_params.items() if v is not None}

        generation_config = types.GenerateContentConfig(**config_params)

        # Use self.client.aio.models.generate_content for asynchronous calls
        return await self.client.aio.models.generate_content(
             model=model_name,
             contents=gemini_contents,
             config=generation_config,
             **kwargs
        )

    def _parse_response(self, res: Any, model_name: str) -> LLMResponse:
        text_content = ""
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        success = True  # Default to success
        error_message = None # Default to no error message

        try:
            # First, try to get text directly from res.text as per README.md examples
            if hasattr(res, 'text'):
                text_content = res.text

            # If res.text is empty, iterate through candidates and their parts to find text content.
            # This handles cases where text might be in parts (e.g., multi-part responses)
            if not text_content and hasattr(res, 'candidates') and res.candidates:
                for candidate in res.candidates:
                    if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                        for part in candidate.content.parts:
                            if hasattr(part, 'text') and part.text:
                                text_content = part.text
                                break # Found text, exit inner loop
                    if text_content:
                        break # Found text, exit outer loop

            # If after all attempts, text_content is still empty, mark as a failure
            if not text_content:
                success = False
                error_message = "LLM response contained no usable text content or was blocked."
                self.logger.warning(f"[_parse_response] {error_message}")

        except Exception as e: # Catch any unexpected errors during text extraction
            success = False
            error_message = f"[_parse_response] Error extracting text from LLM response: {e}"
            self.logger.error(error_message, exc_info=True)

        # Extract usage metadata if available
        if hasattr(res, 'usage_metadata') and res.usage_metadata:
             total_tokens = getattr(res.usage_metadata, 'total_token_count', 0)
             prompt_tokens = getattr(res.usage_metadata, 'prompt_token_count', 0)
             completion_tokens = getattr(res.usage_metadata, 'candidates_token_count', 0)

        # Return LLMResponse with appropriate success status and error message
        return LLMResponse(
            text=text_content,
            model=model_name,
            usage={"prompt": prompt_tokens, "completion": completion_tokens, "total": total_tokens},
            extra={},
            success=success,
            error_message=error_message
        )


import ollama

@register_provider("ollama")
class OllamaClient(BaseLLMClient):
    @classmethod
    def retry_exceptions(cls):
        return (ollama.ResponseError, ConnectionError, TimeoutError)

    async def _call(self, messages: List[Dict[str, Any]], kwargs: Dict[str, Any]) -> Any:
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

        if 'timeout' in chat_params:
            chat_params.pop("timeout")

        return await client.chat(**chat_params)

    def _parse_response(self, res: Any, model_name: str) -> LLMResponse:
        text_content = res.get("message", {}).get("content", "")
        prompt_tokens = res.get("prompt_eval_count", 0)
        completion_tokens = res.get("eval_count", 0)
        total_tokens = prompt_tokens + completion_tokens

        return LLMResponse(
            text=text_content,
            model=model_name,
            usage={"prompt": prompt_tokens, "completion": completion_tokens, "total": total_tokens},
            extra={},
            success=True
        )

async def generate_response(
    messages: List[Dict[str, Any]],
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    provider: Optional[str] = None,
    **kwargs: Any,
) -> LLMResponse:
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
