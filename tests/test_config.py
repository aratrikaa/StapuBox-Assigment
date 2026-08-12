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

from app.config import _bool, _env, _writable  # noqa: E402


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


def test_writable_keeps_the_configured_path_when_it_actually_works(tmp_path):
    configured = tmp_path / "chroma"
    result = _writable(configured, is_dir=True, tmp_name="unused-fallback")
    assert result == configured
    assert configured.is_dir()


def test_writable_falls_back_when_the_configured_path_cant_be_created(tmp_path):
    """Regression test for the exact production crash: CHROMA_DIR resolved
    to a read-only location (a serverless deployment bundle outside /tmp),
    and mkdir raised OSError before the app could serve a single request."""
    blocker = tmp_path / "not_a_directory"
    blocker.write_text("x")  # a file sitting where a directory is expected
    configured = blocker / "chroma"  # mkdir must fail: a path component is a file

    result = _writable(configured, is_dir=True, tmp_name="test-chroma-fallback")

    assert result != configured
    assert result.is_dir()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
