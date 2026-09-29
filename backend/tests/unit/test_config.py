from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_defaults_are_paper_mode_with_decimal_capital():
    s = Settings()
    assert s.trading_mode == "paper"
    assert s.paper_initial_capital == Decimal("10000")
    assert isinstance(s.paper_initial_capital, Decimal)


def test_live_trading_mode_is_rejected(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "live")
    with pytest.raises(ValidationError):
        Settings()


def test_capital_from_env_keeps_exact_decimal(monkeypatch):
    monkeypatch.setenv("PAPER_INITIAL_CAPITAL", "10000.10")
    assert Settings().paper_initial_capital == Decimal("10000.10")


@pytest.mark.parametrize("value", ["0", "-5", "abc"])
def test_invalid_capital_is_rejected(monkeypatch, value):
    monkeypatch.setenv("PAPER_INITIAL_CAPITAL", value)
    with pytest.raises(ValidationError):
        Settings()


def test_float_capital_is_rejected_when_passed_in_code():
    with pytest.raises(ValidationError):
        Settings(paper_initial_capital=10000.1)


def test_blank_api_key_counts_as_not_configured(monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "   ")
    assert Settings().provider_status()["tiingo"] is False


def test_provider_status_reports_presence_not_values(monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "super-secret-value")
    status = Settings().provider_status()
    assert status["tiingo"] is True
    assert status["coinbase"] is True  # public data, no key
    assert "super-secret-value" not in repr(status)


def test_secret_is_masked_in_repr(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    assert "sk-should-not-leak" not in repr(Settings())


def test_sec_user_agent_requires_contact_email(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "MarketOS")
    with pytest.raises(ValidationError):
        Settings()
    monkeypatch.setenv("SEC_USER_AGENT", "MarketOS research me@example.com")
    assert Settings().provider_status()["sec_edgar"] is True


def test_cors_origins_split_from_comma_list(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test")
    assert Settings().cors_origins == ["http://a.test", "http://b.test"]


def test_heartbeat_interval_has_a_floor(monkeypatch):
    monkeypatch.setenv("SCHEDULE_HEARTBEAT_SECONDS", "1")
    with pytest.raises(ValidationError):
        Settings()
