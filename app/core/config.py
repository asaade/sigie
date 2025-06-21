# app/core/config.py
from typing import Literal, Optional
from pydantic import ConfigDict, Field
from pydantic_settings import BaseSettings

# Actualizamos LLMProvider para incluir OpenRouter
LLMProvider = Literal["openai", "ollama", "gemini", "openrouter"]

class Settings(BaseSettings):

    model_config = ConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    # Base de datos
    database_url: str = Field(..., env="DATABASE_URL")
    psql_database_url: Optional[str] = Field(None, env="PSQL_DATABASE_URL") # Añadido si se usa una variable separada

    # Proveedor general
    llm_provider: LLMProvider = Field(
        "openai", env="LLM_PROVIDER",
        description="Proveedor de LLM: openai, ollama, gemini o openrouter"
    )
    llm_model: str = Field("gpt-4o-mini", env="LLM_MODEL") # Modelo por defecto para el proveedor general

    # --- Claves y endpoints específicos por proveedor ---

    # OpenAI
    openai_api_key: Optional[str] = Field(None, env="OPENAI_API_KEY")
    openai_base_url: Optional[str] = Field(None, env="OPENAI_BASE_URL") # Para custom endpoints de OpenAI o proxies

    # OpenRouter
    openrouter_api_key: Optional[str] = Field(None, env="OPENROUTER_API_KEY") # Añadido
    openrouter_base_url: Optional[str] = Field("https://openrouter.ai/api/v1", env="OPENROUTER_BASE_URL") # Añadido URL por defecto

    # Gemini / Google GenAI
    google_api_key: Optional[str] = Field(None, env="GOOGLE_API_KEY")
    gemini_base_url: Optional[str] = Field(None, env="GEMINI_BASE_URL") # Añadido si Gemini usa un base_url distinto a Google API

    # Ollama
    ollama_host: str = Field("http://localhost:11434", env="OLLAMA_HOST")

    # --- Control de calidad / resiliencia ---
    llm_max_retries: int = Field(3, env="LLM_MAX_RETRIES")
    llm_request_timeout: float = Field(60.0, env="LLM_REQUEST_TIMEOUT") # Usado en Ollama

    # --- Generación ---
    llm_max_tokens: int = Field(3000, env="LLM_MAX_TOKENS")
    prompt_version: str = Field("2025-07-01", env="PROMPT_VERSION")
    llm_temperature: float = Field(0.7, env="LLM_TEMPERATURE")

def get_settings() -> Settings:
    return Settings()
