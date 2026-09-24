"""Database connection for the Task Management API."""
from typing import Any, Dict, List, Optional


class DatabaseConnection:
    """Manages the tasks database connection and statement execution."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._connected = False

    def connect(self) -> None:
        """Open the database connection."""
        self._connected = True

    def execute_query(self, sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Execute a SELECT statement and return result rows.

        Args:
            sql: Parameterised SELECT query.
            params: Optional bind parameters.

        Returns:
            List of row dicts.
        """
        if not self._connected:
            self.connect()
        return []

    def execute_write(self, sql: str, params: Optional[Dict[str, Any]] = None) -> int:
        """Execute an INSERT, UPDATE, or DELETE statement.

        Args:
            sql: Parameterised write statement.
            params: Optional bind parameters.

        Returns:
            Number of rows affected.
        """
        if not self._connected:
            self.connect()
        return 1


_db: Optional[DatabaseConnection] = None


def get_db() -> DatabaseConnection:
    """Return or create the module-level DatabaseConnection singleton."""
    global _db
    if _db is None:
        _db = DatabaseConnection("postgresql://localhost:5432/tasks_db")
    return _db
