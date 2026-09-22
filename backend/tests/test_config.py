import os
from unittest import mock
from backend.app.config import Settings


def test_default_configuration_values():
    """Verify default settings values when no environment variables are passed."""
    with mock.patch.dict(os.environ, {}, clear=True):
        config = Settings(_env_file=None)
        assert config.app_name == "PRISM Agentic Code Intelligence"
        assert config.app_env == "development"
        assert config.debug is True
        assert config.host == "0.0.0.0"
        assert config.port == 8000


def test_missing_optional_environment_variables():
    """Verify missing optional API keys default to None without raising validation errors."""
    with mock.patch.dict(os.environ, {}, clear=True):
        config = Settings(_env_file=None)
        assert config.gemini_api_key is None
        assert config.openai_api_key is None


def test_override_environment_variables():
    """Verify environment variables successfully override defaults."""
    env_overrides = {
        "APP_NAME": "Custom Agent Title",
        "APP_ENV": "production",
        "DEBUG": "false",
        "PORT": "9000",
        "GEMINI_API_KEY": "test_gemini_key_123",
    }
    with mock.patch.dict(os.environ, env_overrides, clear=True):
        config = Settings(_env_file=None)
        assert config.app_name == "Custom Agent Title"
        assert config.app_env == "production"
        assert config.debug is False
        assert config.port == 9000
        assert config.gemini_api_key == "test_gemini_key_123"
        assert config.openai_api_key is None
