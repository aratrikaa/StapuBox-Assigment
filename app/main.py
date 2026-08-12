"""FastAPI application: JSON API + the static dashboard."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import MAX_BATCH_SIZE, MIN_BATCH_SIZE, AgentError, SportsContentAgent, get_agent
from .config import settings
from .history import get_history
from .schemas import (
    CONTENT_TYPE_LABELS,
    RECOMMENDED_SURFACE,
    Batch,
    ContentItem,
    ContentType,
    Difficulty,
    Source,
)
from .vector_store import get_knowledge_base

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
)
log = logging.getLogger("sports_agent")

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm the vector store at boot so the first request isn't paying for
    # Chroma's client construction and embedding-model download.
    kb = get_knowledge_base()
    log.info("Knowledge base ready: %s", kb.stats())
    if not settings.configured:
        log.warning("GROQ_API_KEY is not set — generation endpoints will return 503.")
    yield


app = FastAPI(
    title="AI-Powered Sports Engagement Content Agent",
    description=(
        "Generates Instagram-ready sports quizzes, true/false challenges, opinion "
        "polls, fill-in-the-blanks and guess-the-number prompts, grounded in live "
        "web search and a ChromaDB knowledge base."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def no_cache_static(request, call_next):
    # This dashboard's JS/CSS changes constantly during development; a browser
    # serving a stale cached copy of app.js against the current index.html is
    # exactly how "works on the server, breaks in the browser" bugs happen —
    # a plain refresh doesn't necessarily revalidate a cached script/stylesheet.
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def _agent() -> SportsContentAgent:
    try:
        return get_agent()
    except AgentError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# --------------------------------------------------------------------------- #
# Request models
# --------------------------------------------------------------------------- #


class GenerateRequest(BaseModel):
    sport: str = Field(min_length=2, max_length=60)
    difficulty: Difficulty = Difficulty.MEDIUM
    types: list[ContentType] = Field(min_length=1)
    count: int = Field(default=5, ge=MIN_BATCH_SIZE, le=MAX_BATCH_SIZE)
    mixed: bool = False


class RegenerateItemRequest(BaseModel):
    batch_id: str
    item_id: str
    refresh_research: bool = True


class RegenerateBatchRequest(BaseModel):
    batch_id: str


class ItemResponse(BaseModel):
    item: ContentItem
    batch: Batch


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=200)


class SearchResponse(BaseModel):
    query: str
    answer: str
    sources: list[Source]
    fetched_at: str


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "api_key_configured": settings.configured,
        "model": settings.model,
        "research_model": settings.research_model,
        "temperature": settings.temperature,
        "reasoning_effort": settings.reasoning_effort,
        "web_search_enabled": settings.enable_web_search,
        "knowledge_base": get_knowledge_base().stats(),
        "history": get_history().stats(),
    }


@app.get("/api/meta")
async def meta() -> dict:
    """Everything the dashboard needs to render its controls."""
    return {
        "sports": get_knowledge_base().sports(),
        "difficulties": [d.value for d in Difficulty],
        "types": [
            {
                "value": t.value,
                "label": CONTENT_TYPE_LABELS[t],
                "surface": RECOMMENDED_SURFACE[t],
                "fact_checked": t != ContentType.POLL,
            }
            for t in ContentType
        ],
        "batch_size": {"min": MIN_BATCH_SIZE, "max": MAX_BATCH_SIZE},
        "api_key_configured": settings.configured,
    }


@app.post("/api/generate", response_model=Batch)
async def generate(req: GenerateRequest) -> Batch:
    try:
        return await _agent().generate_batch(
            sport=req.sport.strip(),
            difficulty=req.difficulty,
            types=req.types,
            count=req.count,
            mixed=req.mixed,
        )
    except AgentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - surfaced to the dashboard
        log.exception("Batch generation failed")
        raise HTTPException(status_code=500, detail=f"Generation failed: {exc}") from exc


@app.post("/api/regenerate-item", response_model=ItemResponse)
async def regenerate_item(req: RegenerateItemRequest) -> ItemResponse:
    try:
        item, batch = await _agent().regenerate_item(
            req.batch_id, req.item_id, req.refresh_research
        )
        return ItemResponse(item=item, batch=batch)
    except AgentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        log.exception("Item regeneration failed")
        raise HTTPException(status_code=500, detail=f"Regeneration failed: {exc}") from exc


@app.post("/api/regenerate-batch", response_model=Batch)
async def regenerate_batch(req: RegenerateBatchRequest) -> Batch:
    try:
        return await _agent().regenerate_batch(req.batch_id)
    except AgentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        log.exception("Batch regeneration failed")
        raise HTTPException(status_code=500, detail=f"Regeneration failed: {exc}") from exc


@app.post("/api/search", response_model=SearchResponse)
async def search(req: SearchRequest) -> SearchResponse:
    """Ad hoc live web search — every call fetches fresh, nothing is cached."""
    try:
        answer, sources = await _agent().search_web(req.query.strip())
    except Exception as exc:  # pragma: no cover - surfaced to the dashboard
        log.exception("Web search failed")
        raise HTTPException(status_code=500, detail=f"Search failed: {exc}") from exc
    return SearchResponse(
        query=req.query.strip(),
        answer=answer,
        sources=sources,
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


@app.get("/api/history")
async def history(sport: str | None = None, limit: int = 50) -> dict:
    store = get_history()
    if sport:
        rows = store.recent(sport, limit)
        return {"sport": sport, "items": [dict(r) for r in rows], "stats": store.stats()}
    return {"stats": store.stats()}


@app.delete("/api/history")
async def clear_history(sport: str | None = None) -> dict:
    removed = get_history().clear(sport)
    return {"removed": removed, "sport": sport}


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
