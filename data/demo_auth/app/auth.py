"""Authentication middleware and token validation for the Auth Service."""
from typing import Optional, Tuple
from app.models import AuthToken, User
from app.repositories.user_repository import UserRepository


_active_tokens: dict = {}


def authenticate_user(username: str, password: str) -> Tuple[bool, str]:
    """Entry point to authenticate a user via submitted credentials.

    Delegates to AuthService.login for credential resolution.

    Args:
        username: User's login identifier.
        password: Submitted plaintext password.

    Returns:
        Tuple of (success_bool, message_string).
    """
    from app.services.auth_service import AuthService
    service = AuthService()
    token, msg = service.login(username, password)
    if token:
        _active_tokens[token.token] = token
        return True, msg
    return False, msg


def verify_token(token_str: str) -> Optional[AuthToken]:
    """Validate an authentication token string.

    Checks that the token exists in the active-session store and has
    not expired.

    Args:
        token_str: The raw token string from the Authorization header.

    Returns:
        The AuthToken if valid, or None if invalid or expired.
    """
    token = _active_tokens.get(token_str)
    if token is None:
        return None
    if token.is_expired():
        del _active_tokens[token_str]
        return None
    return token


def require_auth(token_str: Optional[str]) -> Tuple[bool, str]:
    """Middleware check that enforces authentication on protected routes.

    Args:
        token_str: Bearer token extracted from the Authorization header.

    Returns:
        Tuple of (is_authenticated, error_message_or_empty).
    """
    if not token_str:
        return False, "Missing Authorization header."
    token = verify_token(token_str)
    if token is None:
        return False, "Token is invalid or has expired."
    return True, ""
