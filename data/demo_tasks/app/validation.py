"""Input validation for the Task Management API."""
from typing import Dict, List, Tuple
from app.config import get_settings


def validate_task_input(payload: Dict) -> Tuple[bool, List[str]]:
    """Validate a task creation or update payload.

    Checks:
    - title is present and within length limit
    - priority is one of the allowed values
    - status is one of the allowed values
    - tags list does not exceed the maximum count

    Args:
        payload: Raw dict with task fields.

    Returns:
        Tuple of (is_valid, error_messages).
    """
    settings = get_settings()
    errors: List[str] = []

    title = payload.get("title", "")
    if not title:
        errors.append("title is required.")
    elif len(title) > settings.title_max_length:
        errors.append(f"title must not exceed {settings.title_max_length} characters.")

    priority = payload.get("priority", "medium")
    if priority not in settings.allowed_priorities:
        errors.append(f"priority must be one of: {settings.allowed_priorities}.")

    status = payload.get("status", "todo")
    if status not in settings.allowed_statuses:
        errors.append(f"status must be one of: {settings.allowed_statuses}.")

    tags = payload.get("tags", [])
    if len(tags) > settings.max_tags_per_task:
        errors.append(f"A task cannot have more than {settings.max_tags_per_task} tags.")

    return (len(errors) == 0, errors)
