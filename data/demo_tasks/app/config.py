"""Configuration settings for the Task Management API."""
from dataclasses import dataclass


@dataclass
class Settings:
    database_url: str = "postgresql://localhost:5432/tasks_db"
    max_tags_per_task: int = 10
    title_max_length: int = 200
    allowed_priorities: tuple = ("low", "medium", "high")
    allowed_statuses: tuple = ("todo", "in_progress", "done")


def get_settings() -> Settings:
    """Return the singleton application Settings."""
    return Settings()
