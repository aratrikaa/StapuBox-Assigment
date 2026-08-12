"""Unit tests for the env-var parsing helpers in config.py.

Regression coverage for a real production bug: a hosting dashboard (Vercel)
left SPORTS_AGENT_TEMPERATURE *present* with an empty value rather than
unset. `os.getenv(name, default)` only falls back to `default` when the var
is entirely absent, so `float(os.getenv(...))` crashed on `float("")` and
took the whole app down before it could serve a single request.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from app.config import _bool, _env  # noqa: E402


def test_env_falls_back_on_missing_var(monkeypatch):
    monkeypatch.delenv("SOME_UNSET_VAR", raising=False)
    assert _env("SOME_UNSET_VAR", "default") == "default"


def test_env_falls_back_on_blank_var(monkeypatch):
    monkeypatch.setenv("SOME_VAR", "")
    assert _env("SOME_VAR", "default") == "default"


def test_env_falls_back_on_whitespace_only_var(monkeypatch):
    monkeypatch.setenv("SOME_VAR", "   ")
    assert _env("SOME_VAR", "default") == "default"


def test_env_uses_real_value_when_present(monkeypatch):
    monkeypatch.setenv("SOME_VAR", "0.9")
    assert _env("SOME_VAR", "0.6") == "0.9"


def test_blank_temperature_env_var_no_longer_crashes(monkeypatch):
    """The exact failure mode seen in production: present but empty."""
    monkeypatch.setenv("SPORTS_AGENT_TEMPERATURE", "")
    assert float(_env("SPORTS_AGENT_TEMPERATURE", "0.6")) == 0.6


def test_bool_falls_back_on_blank_var(monkeypatch):
    monkeypatch.setenv("ENABLE_WEB_SEARCH", "")
    assert _bool("ENABLE_WEB_SEARCH", True) is True


def test_bool_still_parses_real_values(monkeypatch):
    monkeypatch.setenv("ENABLE_WEB_SEARCH", "0")
    assert _bool("ENABLE_WEB_SEARCH", True) is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
