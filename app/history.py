"""Cross-session freshness store.

The assignment asks for "fresh and diverse content on every request — avoid
repeating the same question/fact across sessions". Prompting alone can't do
that: the model has no memory of what it produced yesterday. So every accepted
item is fingerprinted and persisted to SQLite, and the store is used twice:

1. **Before** generation — the last N subjects for that sport are injected into
   the prompt as an explicit avoid-list.
2. **After** generation — the new item is compared against history by token
   overlap; a near-duplicate is rejected and regenerated with a tighter
   avoid-list.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from .config import settings

# Words that carry no topical signal and would inflate similarity between two
# unrelated questions.
STOPWORDS = {
    "a", "an", "and", "any", "are", "as", "at", "be", "been", "but", "by", "did",
    "do", "does", "for", "from", "had", "has", "have", "he", "her", "his", "how",
    "in", "is", "it", "its", "many", "most", "of", "on", "one", "or", "she",
    "that", "the", "their", "there", "these", "they", "this", "to", "was", "were",
    "what", "when", "where", "which", "who", "whom", "whose", "why", "will",
    "with", "you", "your", "ever", "only", "than", "then", "first", "true",
    "false", "following", "player", "team", "match", "game", "___",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS generated_items (
    id          TEXT PRIMARY KEY,
    sport       TEXT NOT NULL,
    type        TEXT NOT NULL,
    difficulty  TEXT,
    subject     TEXT NOT NULL,
    tokens      TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_sport ON generated_items (sport, created_at DESC);
"""


def tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.casefold())
    return {w for w in words if w not in STOPWORDS and len(w) > 2}


def similarity(a: set[str], b: set[str]) -> float:
    """Jaccard overlap. 1.0 = identical topic, 0.0 = nothing in common."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class HistoryStore:
    def __init__(self, path=None) -> None:
        self._path = str(path or settings.history_db)
        settings.history_db.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open a connection, commit on success, and always close.

        Note that ``with sqlite3.connect(...)`` alone manages the *transaction*
        but leaves the connection open — on Windows that keeps a file handle
        alive and blocks the database file from being deleted.
        """
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #

    def record(self, item_id: str, sport: str, ctype: str, difficulty: str | None, subject: str):
        toks = tokenize(subject)
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO generated_items "
                "(id, sport, type, difficulty, subject, tokens, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    item_id,
                    sport,
                    ctype,
                    difficulty,
                    subject,
                    " ".join(sorted(toks)),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def forget(self, item_id: str) -> None:
        """Drop an item — used when the user regenerates it away."""
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM generated_items WHERE id = ?", (item_id,))

    def clear(self, sport: str | None = None) -> int:
        with self._lock, self._connect() as conn:
            if sport:
                cur = conn.execute("DELETE FROM generated_items WHERE sport = ?", (sport,))
            else:
                cur = conn.execute("DELETE FROM generated_items")
            return cur.rowcount

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #

    def recent(self, sport: str, limit: int | None = None) -> list[sqlite3.Row]:
        limit = limit or settings.avoid_list_size
        with self._lock, self._connect() as conn:
            return conn.execute(
                "SELECT * FROM generated_items WHERE sport = ? ORDER BY created_at DESC LIMIT ?",
                (sport, limit),
            ).fetchall()

    def avoid_list(self, sport: str, limit: int | None = None) -> list[str]:
        return [r["subject"] for r in self.recent(sport, limit)]

    def is_duplicate(
        self, sport: str, subject: str, threshold: float | None = None
    ) -> tuple[bool, str | None, float]:
        """Compare a candidate subject against this sport's recent history."""
        threshold = threshold if threshold is not None else settings.dedupe_threshold
        candidate = tokenize(subject)
        best_score, best_subject = 0.0, None
        for row in self.recent(sport, limit=200):
            score = similarity(candidate, set(row["tokens"].split()))
            if score > best_score:
                best_score, best_subject = score, row["subject"]
        return best_score >= threshold, best_subject, best_score

    def stats(self) -> dict:
        with self._lock, self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) c FROM generated_items").fetchone()["c"]
            by_sport = {
                r["sport"]: r["c"]
                for r in conn.execute(
                    "SELECT sport, COUNT(*) c FROM generated_items GROUP BY sport ORDER BY c DESC"
                )
            }
            by_type = {
                r["type"]: r["c"]
                for r in conn.execute(
                    "SELECT type, COUNT(*) c FROM generated_items GROUP BY type ORDER BY c DESC"
                )
            }
        return {"total": total, "by_sport": by_sport, "by_type": by_type, "path": self._path}


_store: HistoryStore | None = None
_store_lock = threading.Lock()


def get_history() -> HistoryStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = HistoryStore()
    return _store
