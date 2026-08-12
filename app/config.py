"""Runtime configuration, loaded once from the environment / .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _path(name: str, default: str) -> Path:
    p = Path(os.getenv(name, default))
    return p if p.is_absolute() else ROOT / p


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
        default_factory=lambda: os.getenv("SPORTS_AGENT_MODEL", "openai/gpt-oss-20b")
    )
    research_model: str = field(
        default_factory=lambda: os.getenv("SPORTS_AGENT_RESEARCH_MODEL", "groq/compound-mini")
    )
    temperature: float = field(
        default_factory=lambda: float(os.getenv("SPORTS_AGENT_TEMPERATURE", "0.6"))
    )
    # openai/gpt-oss-* models spend completion tokens on hidden chain-of-thought
    # before the final JSON. "low" is enough for a single structured quiz item
    # and leaves headroom under max_completion_tokens for the actual answer —
    # at "medium"/"high" the reasoning trace can consume the whole budget and
    # Groq's strict-mode validator then rejects the truncated, empty response.
    reasoning_effort: str = field(
        default_factory=lambda: os.getenv("SPORTS_AGENT_REASONING_EFFORT", "low")
    )

    chroma_dir: Path = field(default_factory=lambda: _path("CHROMA_DIR", "app/data/chroma"))
    history_db: Path = field(default_factory=lambda: _path("HISTORY_DB", "app/data/history.sqlite3"))
    dedupe_threshold: float = field(
        default_factory=lambda: float(os.getenv("DEDUPE_THRESHOLD", "0.55"))
    )
    enable_web_search: bool = field(default_factory=lambda: _bool("ENABLE_WEB_SEARCH", True))

    # Batch items generate concurrently, but Groq enforces a *per-minute*
    # token budget shared across simultaneous requests — firing a whole
    # 5-item batch at once can trip it immediately on lower tiers. This caps
    # how many generation calls are in flight at a time; regeneration and
    # research calls are unaffected.
    max_concurrent_generation: int = field(
        default_factory=lambda: int(os.getenv("SPORTS_AGENT_MAX_CONCURRENCY", "2"))
    )

    # How many stored items to feed back into the prompt as an "already used" avoid-list.
    avoid_list_size: int = 40
    # How many times a single item is re-generated when it collides with history.
    max_dedupe_retries: int = 2

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


settings = Settings()
