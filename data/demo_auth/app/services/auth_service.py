"""Core authentication business logic."""
import hashlib
import secrets
import time
from typing import Optional, Tuple
from app.models import AuthToken, User
from app.config import get_settings
from app.repositories.user_repository import UserRepository


class AuthService:
    """Handles credential verification, token issuance, and session management."""

    def __init__(self) -> None:
        self._user_repo = UserRepository()
        self._settings = get_settings()

    def login(self, username: str, password: str) -> Tuple[Optional[AuthToken], str]:
        """Authenticate a user and issue a token on success.

        Steps:
        1. Retrieve user from UserRepository by username.
        2. Verify submitted password hash against stored hash.
        3. Issue a new AuthToken if credentials are valid.

        Args:
            username: The user's login identifier.
            password: The submitted plaintext password.

        Returns:
            Tuple of (AuthToken or None, status message).
        """
        user = self._user_repo.find_by_username(username)
        if user is None:
            return None, "User not found."

        if not self.verify_credentials(password, user.password_hash):
            return None, "Invalid credentials."

        token = AuthToken(
            token=secrets.token_hex(32),
            user_id=user.user_id,
            expires_at=time.time() + self._settings.token_expiry_seconds,
            issued_at=time.time(),
        )
        return token, "Login successful."

    def verify_credentials(self, password: str, stored_hash: str) -> bool:
        """Compare a submitted password against a stored hash.

        Args:
            password: Plaintext password submitted by user.
            stored_hash: Hash previously stored during registration.

        Returns:
            True if the hashes match; False otherwise.
        """
        submitted_hash = hashlib.sha256(password.encode()).hexdigest()
        return secrets.compare_digest(submitted_hash, stored_hash)
