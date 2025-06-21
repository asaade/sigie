from typing import Literal, Optional
from pydantic import ConfigDict, Field
from pydantic_settings import BaseSettings

LLMProvider = Literal["openai", "ollama", "gemini"]

class Settings(BaseSettings):

    model_config = ConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    # Base de datos
    database_url: str = Field(..., env="DATABASE_URL")

    # Proveedor y modelo
    llm_provider: LLMProvider = Field(
        "openai", env="LLM_PROVIDER",
        description="Proveedor de LLM: openai, ollama o gemini"
    )
    llm_model: str = Field("gpt-4o-mini", env="LLM_MODEL")

    # Claves y endpoints
    llm_api_key: str = Field("", env="LLM_API_KEY")
    llm_base_url: Optional[str] = Field(None, env="LLM_BASE_URL")
    google_api_key: Optional[str] = Field(None, env="GOOGLE_API_KEY")

    # Control de calidad / resiliencia
    llm_max_retries: int = Field(3, env="LLM_MAX_RETRIES")
    llm_request_timeout: float = Field(60.0, env="LLM_REQUEST_TIMEOUT")
    ollama_host: str = Field("http://localhost:11434", env="OLLAMA_HOST")

    # Generación
    llm_max_tokens: int = Field(3000, env="LLM_MAX_TOKENS")
    prompt_version: str = Field("2025-07-01", env="PROMPT_VERSION")
    llm_temperature: float = Field(0.7, env="LLM_TEMPERATURE")

def get_settings() -> Settings:
    return Settings()
