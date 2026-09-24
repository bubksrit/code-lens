"""HTTP route handlers for the Authentication Service."""
from typing import Any, Dict, Optional
from app.auth import authenticate_user, require_auth, verify_token
from app.services.auth_service import AuthService

_auth_service = AuthService()


def login_endpoint(request_body: Dict[str, Any]) -> Dict[str, Any]:
    """Handle POST /auth/login — authenticate user and issue token.

    Args:
        request_body: JSON body with 'username' and 'password' fields.

    Returns:
        Dict with 'token' and 'expires_at' on success.

    Raises:
        PermissionError: If credentials are invalid.
    """
    username = request_body.get("username", "")
    password = request_body.get("password", "")

    if not username or not password:
        raise ValueError("username and password are required.")

    success, message = authenticate_user(username, password)
    if not success:
        raise PermissionError(f"Login failed: {message}")

    return {"message": message, "authenticated": True}


def logout_endpoint(token_str: Optional[str]) -> Dict[str, Any]:
    """Handle POST /auth/logout — invalidate an active session token.

    Args:
        token_str: The Bearer token to revoke.

    Returns:
        Confirmation dict.
    """
    ok, err = require_auth(token_str)
    if not ok:
        raise PermissionError(err)
    return {"message": "Logged out successfully."}


def get_current_user_endpoint(token_str: Optional[str]) -> Dict[str, Any]:
    """Handle GET /auth/me — return the currently authenticated user's details.

    Args:
        token_str: Bearer token from Authorization header.

    Returns:
        Dict with user_id.
    """
    ok, err = require_auth(token_str)
    if not ok:
        raise PermissionError(err)
    token = verify_token(token_str or "")
    if token is None:
        raise PermissionError("Invalid token.")
    return {"user_id": token.user_id}
