"""Configuration for the Authentication Service."""
from dataclasses import dataclass


@dataclass
class Settings:
    secret_key: str = "change-me-in-production"
    token_expiry_seconds: int = 3600
    algorithm: str = "HS256"
    max_login_attempts: int = 5
    password_min_length: int = 8


def get_settings() -> Settings:
    """Return the singleton Settings instance."""
    return Settings()
