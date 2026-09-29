import os

import pytest

from app.core.config import get_settings
from app.db.session import get_engine, get_session_factory


def _clear_caches() -> None:
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch):
    """Each test sees settings built from its own environment, never a developer's .env."""
    monkeypatch.chdir(os.path.dirname(__file__))  # no .env file here
    for key in list(os.environ):
        if key.endswith("_API_KEY") or key == "SEC_USER_AGENT":
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("APP_ENV", "test")
    _clear_caches()
    yield
    _clear_caches()
