"""Persistence layer for User entities in the Authentication Service."""
from typing import Optional
from app.models import User
from app.database import get_db


class UserRepository:
    """Reads and writes User records."""

    def find_by_username(self, username: str) -> Optional[User]:
        """Retrieve a User record by their login username.

        Args:
            username: The login identifier to search for.

        Returns:
            The matching User, or None if not found.
        """
        db = get_db()
        rows = db.execute_query(
            "SELECT * FROM users WHERE username = :uname AND is_active = true",
            {"uname": username},
        )
        if not rows:
            return None
        r = rows[0]
        return User(
            user_id=r["user_id"],
            username=r["username"],
            password_hash=r["password_hash"],
            email=r["email"],
            is_active=r["is_active"],
        )

    def find_by_id(self, user_id: str) -> Optional[User]:
        """Retrieve a User by their unique identifier.

        Args:
            user_id: UUID of the user to find.

        Returns:
            Matching User, or None.
        """
        db = get_db()
        rows = db.execute_query("SELECT * FROM users WHERE user_id = :uid", {"uid": user_id})
        if not rows:
            return None
        r = rows[0]
        return User(
            user_id=r["user_id"],
            username=r["username"],
            password_hash=r["password_hash"],
            email=r["email"],
            is_active=r["is_active"],
        )

    def save_user(self, user: User) -> None:
        """Persist a new user record to the database."""
        db = get_db()
        db.execute_write(
            "INSERT INTO users (user_id, username, password_hash, email, is_active) VALUES (:uid, :uname, :hash, :email, :active)",
            {"uid": user.user_id, "uname": user.username, "hash": user.password_hash, "email": user.email, "active": user.is_active},
        )
