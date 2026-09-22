from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings using Pydantic v2 BaseSettings."""
    
    app_name: str = "PRISM Agentic Code Intelligence"
    app_env: str = "development"
    debug: bool = True
    log_level: str = "INFO"
    
    host: str = "0.0.0.0"
    port: int = 8000
    
    # Optional external API keys (defaults to None / empty if omitted)
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
