"""
Pinpoint API
============

Exposes the scanning surface over FastAPI.

Design notes
------------
* The engine is fully blocking (network calls, sleeps, geocoding), so every
  scan is dispatched to a worker thread via ``run_in_threadpool``. The event
  loop stays free to serve other operators.
* Uploads are size-capped while being read, so an oversized file never lands
  in memory.
* Bring-your-own-key values arrive per request, are validated, and are
  forwarded to the provider. They are never written to the vault, the cache,
  or the logs.
"""

from __future__ import annotations

import os
import time
from collections import deque
from contextlib import asynccontextmanager
from itertools import count
from typing import Annotated

import requests
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from app.ai_engine import (
    MODEL_CHOICES,
    PROVIDERS,
    REAL_WORLD_TIERS,
    AIEngine,
    KeyValidationError,
    catalogue_for_api,
    get_engine,
    local_model_available,
    parse_model_selection,
    validate_key,
    warm_local_bunker,
)

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "12")) * 1024 * 1024
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "30"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))


def _allowed_origins() -> list[str]:
    """CORS policy.

    The API is public by design, so the default is a permissive read policy
    with credentials disabled -- a browser on any origin may call it, but no
    cookies or Authorization headers are ever attached on the operator's
    behalf. Set ``ALLOWED_ORIGINS`` to a comma-separated list to narrow it
    to your own deployment.
    """
    configured = os.getenv("ALLOWED_ORIGINS")
    if configured is None:
        return ["*"]
    origins = [origin.strip() for origin in configured.split(",") if origin.strip()]
    return origins or ["*"]


@asynccontextmanager
async def _lifespan(app: FastAPI):
    try:
        get_engine()
    except Exception as exc:  # pragma: no cover - startup diagnostics
        print(f"[startup] AI engine unavailable: {type(exc).__name__}: {exc}")
    if os.getenv("WARM_LOCAL_BUNKER", "1") == "1":
        warm_local_bunker()
    yield


app = FastAPI(
    title="Pinpoint AI Engine",
    version="2.0.0",
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# Discovery vault (in-process, ephemeral)
# --------------------------------------------------------------------------

#: Bounded so a long-lived process cannot grow without limit. Entries are
#: per-process: on a multi-worker or serverless deployment the vault is not
#: shared between workers and does not survive a restart.
discovery_vault: deque[dict] = deque(maxlen=200)
_vault_counter = count(1)


# --------------------------------------------------------------------------
# Rate limiting
# --------------------------------------------------------------------------

_request_log: dict[str, deque[float]] = {}


def _rate_limit(request: Request) -> None:
    client = request.client.host if request.client else "unknown"
    now = time.monotonic()
    window = _request_log.setdefault(client, deque())
    while window and now - window[0] > RATE_LIMIT_WINDOW_SECONDS:
        window.popleft()
    if len(window) >= RATE_LIMIT_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Rate limit reached ({RATE_LIMIT_REQUESTS} requests per "
                f"{RATE_LIMIT_WINDOW_SECONDS}s). Slow down or bring your own key."
            ),
        )
    window.append(now)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


async def _read_capped(file: UploadFile) -> bytes:
    """Read an upload, rejecting anything over the configured cap."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 256)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Image exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
            )
        chunks.append(chunk)
    if total == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    return b"".join(chunks)


def _collect_keys(
    groq_key: str, gemini_key: str, openai_key: str
) -> dict[str, str]:
    """Validate the BYOK fields, raising a 400 for anything malformed."""
    supplied = {
        "groq": groq_key,
        "gemini": gemini_key,
        "openai": openai_key,
    }
    validated: dict[str, str] = {}
    for slug, raw in supplied.items():
        try:
            key = validate_key(slug, raw)
        except KeyValidationError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid API key -- {exc.reason}") from exc
        if key:
            validated[slug] = key
    return validated


def _vault_entry(result: dict) -> dict:
    """Build a vault entry. Never contains API keys or image bytes."""
    return {
        "id": next(_vault_counter),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "location": result.get("location"),
        "coordinates": result.get("coordinates"),
        "mode": result.get("mode"),
        "confidence": result.get("confidence"),
        "source": result.get("source"),
        "tier": result.get("tier"),
        "game": result.get("game"),
        "seed": result.get("seed"),
    }


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


@app.get("/")
async def root():
    return {"status": "online", "model": "StreetCLIP-V4", "version": app.version}


@app.get("/health")
async def health():
    engine = get_engine()
    return {
        "status": "online",
        "version": app.version,
        "redis": engine.redis is not None,
        "tiers": len(REAL_WORLD_TIERS),
        "local_bunker": local_model_available(),
    }


@app.get("/models")
async def list_models():
    """The models this build can use, grouped by provider.

    The frontend builds its model picker from this, so a model can never be
    offered that the engine cannot actually reach.
    """
    return catalogue_for_api()


@app.get("/history")
async def get_history():
    return list(discovery_vault)[-10:]


@app.post("/keys/verify")
async def verify_keys(
    request: Request,
    groq_key: Annotated[str, Form()] = "",
    gemini_key: Annotated[str, Form()] = "",
    openai_key: Annotated[str, Form()] = "",
):
    """Check that each supplied key actually reaches its provider.

    Sends a one-token probe per provider. Keys are used for the probe only.
    """
    _rate_limit(request)
    supplied = _collect_keys(groq_key, gemini_key, openai_key)
    # Test the *effective* keys: an operator-supplied key, or the server's
    # key when the operator did not supply one.
    effective, _ = AIEngine._resolve_keys(supplied)
    engine = get_engine()
    results = await run_in_threadpool(_verify_provider_keys, engine, effective)
    return {"providers": results}


def _verify_provider_keys(engine: AIEngine, keys: dict[str, str]) -> list[dict]:
    """Probe each provider with a minimal text request."""
    probes = {
        "groq": "https://api.groq.com/openai/v1/chat/completions",
        "openai": "https://api.openai.com/v1/chat/completions",
    }
    out: list[dict] = []
    for slug, provider in PROVIDERS.items():
        if provider.env_key is None:
            continue
        key = keys.get(slug)
        if not key:
            out.append({"provider": slug, "label": provider.label, "status": "unset"})
            continue
        try:
            if provider.style == "gemini":
                url = provider.endpoint.format(model="gemini-2.5-flash-lite")
                response = requests.post(
                    f"{url}?key={key}",
                    json={"contents": [{"parts": [{"text": "ping"}]}]},
                    headers={"Content-Type": "application/json"},
                    timeout=15,
                )
            else:
                headers = {
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    **{n: v for n, v in provider.extra_headers},
                }
                response = requests.post(
                    probes[slug],
                    json={
                        "model": _probe_model(slug),
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 4,
                    },
                    headers=headers,
                    timeout=15,
                )
        except Exception as exc:
            out.append(
                {"provider": slug, "label": provider.label, "status": "error", "detail": type(exc).__name__}
            )
            continue
        if response.status_code == 200:
            out.append({"provider": slug, "label": provider.label, "status": "ok"})
        else:
            out.append(
                {
                    "provider": slug,
                    "label": provider.label,
                    "status": "error",
                    "detail": f"HTTP {response.status_code}",
                }
            )
    return out


def _probe_model(slug: str) -> str:
    return {
        "groq": "qwen/qwen3.8-27b",
        "openai": "gpt-4o-mini",
    }[slug]


@app.post("/scan")
async def scan_image(
    request: Request,
    file: Annotated[UploadFile, File()],
    mode: Annotated[str, Form()] = "real-world",
    game: Annotated[str | None, Form()] = None,
    model: Annotated[str, Form()] = "auto",
    groq_key: Annotated[str, Form()] = "",
    gemini_key: Annotated[str, Form()] = "",
    openai_key: Annotated[str, Form()] = "",
    models: Annotated[str, Form()] = "",
):
    _rate_limit(request)

    if model not in MODEL_CHOICES:
        raise HTTPException(status_code=400, detail=f"Unknown model '{model}'.")
    if mode not in ("real-world", "game"):
        raise HTTPException(status_code=400, detail=f"Unknown mode '{mode}'.")

    contents = await _read_capped(file)
    keys = _collect_keys(groq_key, gemini_key, openai_key)
    selection = parse_model_selection(models)

    engine = get_engine()
    try:
        if mode == "real-world":
            result = await run_in_threadpool(
                engine.scan_real_world, contents, model, keys, selection
            )
        else:
            result = await run_in_threadpool(
                engine.scan_game, contents, game or "Generic", model, keys
            )
    except Exception as exc:
        print(f"[scan] failed: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=500, detail="Scan failed unexpectedly.") from exc

    if "error" not in result:
        discovery_vault.append(_vault_entry(result))

    return result
