"""Data models for the Task Management API."""
from dataclasses import dataclass, field
from typing import List, Optional
import time


@dataclass
class Task:
    task_id: str
    title: str
    description: str
    owner_id: str
    status: str = "todo"  # todo | in_progress | done
    priority: str = "medium"  # low | medium | high
    tags: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None

    def mark_done(self) -> None:
        """Mark this task as completed and record the completion timestamp."""
        self.status = "done"
        self.completed_at = time.time()
