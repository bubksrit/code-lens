"""Application configuration for the E-Commerce API."""
from dataclasses import dataclass

@dataclass
class Settings:
    database_url: str = "postgresql://localhost:5432/ecommerce"
    max_order_items: int = 50
    min_stock_threshold: int = 0
    currency: str = "USD"

def get_settings() -> Settings:
    """Return the singleton application settings instance."""
    return Settings()
