"""Database layer for the Authentication Service."""
from typing import Any, Dict, List, Optional


class DatabaseConnection:
    """Thin wrapper around the auth service's database."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._connected = False

    def connect(self) -> None:
        """Open the database connection."""
        self._connected = True

    def execute_query(self, sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Run a parameterised SELECT and return matching rows.

        Args:
            sql: SQL SELECT statement with named placeholders.
            params: Bind parameters dict.

        Returns:
            List of row dicts.
        """
        if not self._connected:
            self.connect()
        return []

    def execute_write(self, sql: str, params: Optional[Dict[str, Any]] = None) -> int:
        """Execute an INSERT or UPDATE statement.

        Returns:
            Number of rows affected.
        """
        if not self._connected:
            self.connect()
        return 1


_db: Optional[DatabaseConnection] = None


def get_db() -> DatabaseConnection:
    """Return the module-level singleton DatabaseConnection."""
    global _db
    if _db is None:
        _db = DatabaseConnection("postgresql://localhost:5432/auth_service")
    return _db
