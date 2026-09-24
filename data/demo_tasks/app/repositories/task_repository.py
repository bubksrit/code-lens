"""Persistence layer for Task entities."""
from typing import List, Optional
from app.models import Task
from app.database import get_db


class TaskRepository:
    """Reads and writes Task records from the database."""

    def save_task(self, task: Task) -> str:
        """Persist a new Task and return its task_id.

        Args:
            task: The Task object to insert.

        Returns:
            The task_id of the saved record.
        """
        db = get_db()
        db.execute_write(
            "INSERT INTO tasks (task_id, title, description, owner_id, status, priority, created_at) "
            "VALUES (:tid, :title, :desc, :owner, :status, :priority, :ts)",
            {
                "tid": task.task_id,
                "title": task.title,
                "desc": task.description,
                "owner": task.owner_id,
                "status": task.status,
                "priority": task.priority,
                "ts": task.created_at,
            },
        )
        return task.task_id

    def find_task(self, task_id: str) -> Optional[Task]:
        """Look up a Task by its unique identifier.

        Args:
            task_id: The task UUID to search for.

        Returns:
            Matching Task, or None if not found.
        """
        db = get_db()
        rows = db.execute_query("SELECT * FROM tasks WHERE task_id = :tid", {"tid": task_id})
        if not rows:
            return None
        r = rows[0]
        return Task(
            task_id=r["task_id"],
            title=r["title"],
            description=r["description"],
            owner_id=r["owner_id"],
            status=r["status"],
            priority=r["priority"],
        )

    def list_tasks(self, owner_id: Optional[str] = None, status: Optional[str] = None) -> List[Task]:
        """Return tasks, optionally filtered by owner or status.

        Args:
            owner_id: Filter by task owner.
            status: Filter by task status.

        Returns:
            List of matching Task objects.
        """
        db = get_db()
        if owner_id and status:
            rows = db.execute_query(
                "SELECT * FROM tasks WHERE owner_id = :owner AND status = :status",
                {"owner": owner_id, "status": status},
            )
        elif owner_id:
            rows = db.execute_query("SELECT * FROM tasks WHERE owner_id = :owner", {"owner": owner_id})
        elif status:
            rows = db.execute_query("SELECT * FROM tasks WHERE status = :status", {"status": status})
        else:
            rows = db.execute_query("SELECT * FROM tasks", {})
        return [
            Task(task_id=r["task_id"], title=r["title"], description=r["description"],
                 owner_id=r["owner_id"], status=r["status"], priority=r["priority"])
            for r in rows
        ]
