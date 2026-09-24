"""Business logic for Task operations."""
import uuid
from typing import List, Optional
from app.models import Task
from app.validation import validate_task_input
from app.repositories.task_repository import TaskRepository


class TaskService:
    """Orchestrates task creation, retrieval, and listing."""

    def __init__(self) -> None:
        self._task_repo = TaskRepository()

    def create_task(self, payload: dict) -> Task:
        """Validate and persist a new task.

        Steps:
        1. Validate payload with validate_task_input.
        2. Create a Task model.
        3. Save via TaskRepository.save_task.

        Args:
            payload: Dict with 'title', 'description', 'owner_id', and optional fields.

        Returns:
            The newly created Task.

        Raises:
            ValueError: If validation fails.
        """
        is_valid, errors = validate_task_input(payload)
        if not is_valid:
            raise ValueError(f"Task validation failed: {'; '.join(errors)}")

        task = Task(
            task_id=str(uuid.uuid4()),
            title=payload["title"],
            description=payload.get("description", ""),
            owner_id=payload["owner_id"],
            status=payload.get("status", "todo"),
            priority=payload.get("priority", "medium"),
            tags=payload.get("tags", []),
        )
        self._task_repo.save_task(task)
        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        """Retrieve a task by its identifier.

        Args:
            task_id: The task UUID.

        Returns:
            Matching Task, or None.
        """
        return self._task_repo.find_task(task_id)

    def list_tasks(self, owner_id: Optional[str] = None, status: Optional[str] = None) -> List[Task]:
        """Return all tasks, with optional filters.

        Args:
            owner_id: Filter by task owner (optional).
            status: Filter by status string (optional).

        Returns:
            List of Task objects.
        """
        return self._task_repo.list_tasks(owner_id=owner_id, status=status)
