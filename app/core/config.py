# app/core/config.py
from typing import Literal, Optional
from pydantic import ConfigDict, Field
from pydantic_settings import BaseSettings

LLMProvider = Literal["openai", "ollama", "gemini", "openrouter"]

class Settings(BaseSettings):

    model_config = ConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = Field(..., env="DATABASE_URL")
    psql_database_url: Optional[str] = Field(None, env="PSQL_DATABASE_URL")

    llm_provider: LLMProvider = Field(
        "openai", env="LLM_PROVIDER",
        description="Proveedor de LLM: openai, ollama, gemini o openrouter"
    )
    llm_model: str = Field("gpt-4o-mini", env="LLM_MODEL")

    openai_api_key: Optional[str] = Field(None, env="OPENAI_API_KEY")
    openai_base_url: Optional[str] = Field(None, env="OPENAI_BASE_URL")

    openrouter_api_key: Optional[str] = Field(None, env="OPENROUTER_API_KEY")
    openrouter_base_url: Optional[str] = Field("https://openrouter.ai/api/v1", env="OPENROUTER_BASE_URL")

    google_api_key: Optional[str] = Field(None, env="GOOGLE_API_KEY")
    gemini_base_url: Optional[str] = Field(None, env="GEMINI_BASE_url")

    ollama_host: str = Field("http://localhost:11434", env="OLLAMA_HOST")

    llm_max_retries: int = Field(3, env="LLM_MAX_RETRIES")
    llm_request_timeout: float = Field(60.0, env="LLM_REQUEST_TIMEOUT")

    llm_max_tokens: int = Field(3000, env="LLM_MAX_TOKENS")
    prompt_version: str = Field("2025-07-01", env="PROMPT_VERSION")
    llm_temperature: float = Field(0.7, env="LLM_TEMPERATURE")

def get_settings() -> Settings:
    return Settings()
