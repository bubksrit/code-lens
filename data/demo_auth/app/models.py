"""Data models for the Authentication Service."""
from dataclasses import dataclass
from typing import Optional
import time


@dataclass
class User:
    user_id: str
    username: str
    password_hash: str
    email: str
    is_active: bool = True
    created_at: float = 0.0


@dataclass
class AuthToken:
    token: str
    user_id: str
    expires_at: float
    issued_at: float = 0.0

    def is_expired(self) -> bool:
        """Return True if this token has passed its expiry time."""
        return time.time() > self.expires_at
