"""Runtime configuration, loaded once from the environment / .env file."""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

log = logging.getLogger(__name__)

# ChromaDB's default embedding function caches its downloaded ONNX model at a
# HARDCODED `Path.home() / ".cache" / "chroma" / ...` — not something either
# CHROMA_DIR or HISTORY_DB controls. On a serverless host (Vercel, and likely
# others) only /tmp is writable, so an unwritable $HOME crashes the app
# before it ever serves a request. /tmp always exists and is always writable
# on POSIX; on Windows Path.home() doesn't consult $HOME at all, so this is a
# no-op for local dev.
if os.name == "posix":
    os.environ["HOME"] = "/tmp"

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str) -> str:
    """Read an env var, falling back to `default` when unset OR blank.

    A hosting dashboard (Render, Vercel, ...) can leave a variable *present*
    with an empty value rather than not set at all — `os.getenv(name,
    default)` only falls back on the latter, so a blank-but-present
    SPORTS_AGENT_TEMPERATURE crashed the whole app on `float("")` in
    production. Every optional setting below goes through this instead.
    """
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip()


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _path(name: str, default: str) -> Path:
    p = Path(_env(name, default))
    return p if p.is_absolute() else ROOT / p


def _writable(configured: Path, *, is_dir: bool, tmp_name: str) -> Path:
    """Use `configured` if its directory is actually writable; otherwise
    fall back to the OS temp dir and keep going.

    A serverless host's deployment bundle is read-only outside of a temp
    directory — CHROMA_DIR / HISTORY_DB are meant to be pointed at that temp
    directory via env vars there, but a misconfigured or unset override
    crashed the whole app on `mkdir` before it could serve a single request.
    Checking and falling back here means a wrong or missing env var degrades
    to disposable temp storage instead of an outright crash, on any host.
    """
    check_dir = configured if is_dir else configured.parent
    try:
        check_dir.mkdir(parents=True, exist_ok=True)
        probe = check_dir / ".write_test"
        probe.touch()
        probe.unlink()
        return configured
    except OSError:
        fallback = Path(tempfile.gettempdir()) / tmp_name
        (fallback if is_dir else fallback.parent).mkdir(parents=True, exist_ok=True)
        log.warning(
            "%s isn't writable — falling back to %s. Set the env var to a "
            "writable path (e.g. /tmp/...) to avoid this on a serverless host.",
            configured, fallback,
        )
        return fallback


def _real_key(raw: str | None) -> str | None:
    """Reject the .env.example placeholder so it can't masquerade as a real key."""
    if not raw or raw.strip() in {"", "gsk_...", "your-api-key"}:
        return None
    return raw.strip()


@dataclass(frozen=True)
class Settings:
    api_key: str | None = field(default_factory=lambda: _real_key(os.getenv("GROQ_API_KEY")))

    # Structured-JSON generation calls one model; the research call uses a
    # separate "compound" model that gets built-in, automatic web search —
    # Groq does not document response_format support on compound models, so
    # the two calls are kept on different models rather than one shared one.
    model: str = field(
        default_factory=lambda: _env("SPORTS_AGENT_MODEL", "openai/gpt-oss-20b")
    )
    research_model: str = field(
        default_factory=lambda: _env("SPORTS_AGENT_RESEARCH_MODEL", "groq/compound-mini")
    )
    temperature: float = field(
        default_factory=lambda: float(_env("SPORTS_AGENT_TEMPERATURE", "0.6"))
    )
    # openai/gpt-oss-* models spend completion tokens on hidden chain-of-thought
    # before the final JSON. "low" is enough for a single structured quiz item
    # and leaves headroom under max_completion_tokens for the actual answer —
    # at "medium"/"high" the reasoning trace can consume the whole budget and
    # Groq's strict-mode validator then rejects the truncated, empty response.
    reasoning_effort: str = field(
        default_factory=lambda: _env("SPORTS_AGENT_REASONING_EFFORT", "low")
    )

    chroma_dir: Path = field(
        default_factory=lambda: _writable(
            _path("CHROMA_DIR", "app/data/chroma"), is_dir=True, tmp_name="chroma"
        )
    )
    history_db: Path = field(
        default_factory=lambda: _writable(
            _path("HISTORY_DB", "app/data/history.sqlite3"),
            is_dir=False,
            tmp_name="history.sqlite3",
        )
    )
    dedupe_threshold: float = field(
        default_factory=lambda: float(_env("DEDUPE_THRESHOLD", "0.55"))
    )
    enable_web_search: bool = field(default_factory=lambda: _bool("ENABLE_WEB_SEARCH", True))

    # Batch items generate concurrently, but Groq enforces a *per-minute*
    # token budget shared across simultaneous requests — firing a whole
    # 5-item batch at once can trip it immediately on lower tiers. This caps
    # how many generation calls are in flight at a time; regeneration and
    # research calls are unaffected.
    max_concurrent_generation: int = field(
        default_factory=lambda: int(_env("SPORTS_AGENT_MAX_CONCURRENCY", "2"))
    )

    # How many stored items to feed back into the prompt as an "already used" avoid-list.
    avoid_list_size: int = 40
    # How many times a single item is re-generated when it collides with history.
    max_dedupe_retries: int = 2

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


settings = Settings()
