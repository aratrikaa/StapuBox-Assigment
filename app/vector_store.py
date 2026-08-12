"""ChromaDB-backed retrieval for stable / historical sports facts.

Fast-changing information is handled by live web search (see web_search.py).
This module owns the other half: durable records, milestones and rules that
are worth embedding once and querying cheaply forever.
"""

from __future__ import annotations

import logging
import random
import threading

import chromadb
from chromadb.config import Settings as ChromaSettings

from .config import settings
from .knowledge_seed import SEED_DOCUMENTS, SPORTS
from .schemas import Source, SourceKind

log = logging.getLogger(__name__)

COLLECTION_NAME = "sports_knowledge"

# Query angles rotated between requests so repeated calls for the same sport
# surface different slices of the knowledge base — one of the levers that keeps
# generated content diverse across sessions.
QUERY_ANGLES = [
    "all-time records and milestones",
    "historic finals, championships and title wins",
    "legendary players and their signature achievements",
    "rules, formats and measurements of the game",
    "firsts, debuts and breakthrough moments",
    "statistical landmarks and numerical records",
    "iconic individual performances",
    "national teams and their tournament history",
]


class KnowledgeBase:
    """Thin wrapper around a persistent Chroma collection."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        settings.chroma_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(settings.chroma_dir),
            settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
        )
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        self.seed_if_empty()

    # ------------------------------------------------------------------ #
    # Indexing
    # ------------------------------------------------------------------ #

    def seed_if_empty(self) -> int:
        """Populate the collection on first run. Idempotent."""
        with self._lock:
            if self._collection.count() > 0:
                return 0
            ids = [d[0] for d in SEED_DOCUMENTS]
            metadatas = [{"sport": d[1], "category": d[2]} for d in SEED_DOCUMENTS]
            documents = [d[3] for d in SEED_DOCUMENTS]
            self._collection.add(ids=ids, metadatas=metadatas, documents=documents)
            log.info("Seeded ChromaDB with %d documents", len(ids))
            return len(ids)

    def add_document(self, doc_id: str, sport: str, category: str, text: str) -> None:
        with self._lock:
            self._collection.upsert(
                ids=[doc_id],
                metadatas=[{"sport": sport, "category": category}],
                documents=[text],
            )

    # ------------------------------------------------------------------ #
    # Retrieval
    # ------------------------------------------------------------------ #

    def retrieve(self, sport: str, n_results: int = 8, angle: str | None = None) -> list[Source]:
        """Fetch stable facts for a sport, biased by a rotating query angle."""
        angle = angle or random.choice(QUERY_ANGLES)
        query = f"{sport}: {angle}"

        known_sport = any(s.casefold() == sport.casefold() for s in self.sports())
        where = {"sport": self._canonical_sport(sport)} if known_sport else None

        with self._lock:
            try:
                res = self._collection.query(
                    query_texts=[query],
                    n_results=min(n_results, max(self._collection.count(), 1)),
                    where=where,
                )
            except Exception:  # pragma: no cover - defensive
                log.exception("Chroma query failed for %s", sport)
                return []

        docs = (res.get("documents") or [[]])[0]
        ids = (res.get("ids") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]

        sources: list[Source] = []
        for doc, doc_id, meta in zip(docs, ids, metas):
            sources.append(
                Source(
                    kind=SourceKind.VECTOR_DB,
                    title=f"{(meta or {}).get('sport', sport)} · "
                    f"{(meta or {}).get('category', 'fact')}",
                    reference=doc_id,
                    snippet=doc,
                )
            )
        # Shuffling the retrieved set stops the model anchoring on the same
        # top-ranked document every single request.
        random.shuffle(sources)
        return sources

    # ------------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------------ #

    def sports(self) -> list[str]:
        return list(SPORTS)

    def _canonical_sport(self, sport: str) -> str:
        for s in SPORTS:
            if s.casefold() == sport.casefold():
                return s
        return sport

    def stats(self) -> dict:
        with self._lock:
            return {
                "documents": self._collection.count(),
                "collection": COLLECTION_NAME,
                "path": str(settings.chroma_dir),
            }


_kb: KnowledgeBase | None = None
_kb_lock = threading.Lock()


def get_knowledge_base() -> KnowledgeBase:
    """Lazy singleton — the Chroma client is expensive to construct."""
    global _kb
    if _kb is None:
        with _kb_lock:
            if _kb is None:
                _kb = KnowledgeBase()
    return _kb
