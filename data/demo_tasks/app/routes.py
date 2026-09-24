"""HTTP route handlers for the Task Management API."""
from typing import Any, Dict, List, Optional
from app.services.task_service import TaskService
from app.validation import validate_task_input

_task_service = TaskService()


def create_task_endpoint(request_body: Dict[str, Any]) -> Dict[str, Any]:
    """Handle POST /tasks — create a new task.

    Validates the request body and delegates to TaskService.create_task.

    Args:
        request_body: JSON body with 'title', 'owner_id', and optional fields.

    Returns:
        Dict with 'task_id', 'title', and 'status'.

    Raises:
        ValueError: Propagated from TaskService on validation failure.
    """
    task = _task_service.create_task(request_body)
    return {"task_id": task.task_id, "title": task.title, "status": task.status}


def get_task_endpoint(task_id: str) -> Dict[str, Any]:
    """Handle GET /tasks/{task_id} — retrieve a task.

    Args:
        task_id: The task identifier from the URL path.

    Returns:
        Serialised task dict.

    Raises:
        LookupError: If the task is not found.
    """
    task = _task_service.get_task(task_id)
    if task is None:
        raise LookupError(f"Task '{task_id}' not found.")
    return {"task_id": task.task_id, "title": task.title, "status": task.status, "priority": task.priority}


def list_tasks_endpoint(owner_id: Optional[str] = None, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """Handle GET /tasks — list tasks with optional filters.

    Args:
        owner_id: Optional owner filter.
        status_filter: Optional status filter string.

    Returns:
        List of serialised task dicts.
    """
    tasks = _task_service.list_tasks(owner_id=owner_id, status=status_filter)
    return [{"task_id": t.task_id, "title": t.title, "status": t.status} for t in tasks]
