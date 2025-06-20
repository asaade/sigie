import os
from pydantic import BaseSettings, Field

class Settings(BaseSettings):
    llm_provider: str = Field('openai', env='LLM_PROVIDER')
    llm_model: str = Field('gpt-4o', env='LLM_MODEL')
    llm_temperature: float = Field(0.7, env='LLM_TEMPERATURE')
    llm_max_tokens: int = Field(512, env='LLM_MAX_TOKENS')
    llm_max_retries: int = Field(3, env='LLM_MAX_RETRIES')

    # --- Provider‑specific ---
    # OpenAI
    openai_api_key: str = Field('', env='OPENAI_API_KEY')
    openai_base_url: str = Field('', env='OPENAI_BASE_URL')

    # Gemini / Gen AI – both names accepted
    google_api_key: str = Field('', env='GOOGLE_API_KEY')
    gemini_api_key: str = Field('', env='GEMINI_API_KEY')

    # Ollama
    ollama_host: str = Field('http://localhost:11434', env='OLLAMA_HOST')

    class Config:
        env_file = '.env'
        env_prefix = ''
