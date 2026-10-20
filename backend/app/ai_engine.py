"""
Pinpoint AI Engine
==================

Provider abstraction over a tiered fallback cascade, with two tiers of key
supply:

* **Server keys** -- read from the environment (``GROQ_API_KEY``,
  ``GOOGLE_API_KEY``, ``OPENAI_API_KEY``, ``GITHUB_API_KEY``).
* **BYOK keys** -- supplied per request by the operator. They take precedence
  over the matching server key for that request only.

BYOK keys are never persisted: not to Redis, not to the discovery vault, not to
logs, not to the cache key namespace beyond a one-way fingerprint used to keep
operator-specific results from leaking into a shared cache.

Every network call in this module is blocking, so the engine is designed to be
invoked from a worker thread (see ``main.py``).
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Sequence

import requests
from dotenv import load_dotenv
from geopy.geocoders import Nominatim
from PIL import Image

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

#: Where the local CLIP bunker keeps its weights (matches CONTEXT.md).
MODEL_CACHE_DIR = os.path.join(ROOT_DIR, "backend", "models")

#: Per-request wall-clock budget for the whole cascade.
SCAN_DEADLINE_SECONDS = float(os.getenv("SCAN_DEADLINE_SECONDS", "90"))

#: Geocoding cache + image cache TTLs.
GEO_TTL_SECONDS = 60 * 60 * 24 * 30
IMAGE_TTL_SECONDS = 60 * 60 * 24 * 7

#: Nominatim asks for at most one request per second, per policy.
NOMINATIM_MIN_INTERVAL = 1.05

#: How many geocoding candidates a single scan may try.
MAX_GEOCODE_ATTEMPTS = 6


# --------------------------------------------------------------------------
# Provider registry
# --------------------------------------------------------------------------

OPENAI_CHAT = "openai_chat"
GEMINI = "gemini"
LOCAL = "local"


@dataclass(frozen=True)
class Provider:
    """A cloud (or local) inference backend."""

    slug: str
    label: str
    env_key: str | None
    endpoint: str
    style: str
    extra_headers: tuple[tuple[str, str], ...] = ()


PROVIDERS: dict[str, Provider] = {
    "gemini": Provider(
        slug="gemini",
        label="Gemini",
        env_key="GOOGLE_API_KEY",
        endpoint="https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        style=GEMINI,
    ),
    "groq": Provider(
        slug="groq",
        label="Groq",
        env_key="GROQ_API_KEY",
        endpoint="https://api.groq.com/openai/v1/chat/completions",
        style=OPENAI_CHAT,
    ),
    "openai": Provider(
        slug="openai",
        label="OpenAI",
        env_key="OPENAI_API_KEY",
        endpoint="https://api.openai.com/v1/chat/completions",
        style=OPENAI_CHAT,
    ),
    "local": Provider(
        slug="local",
        label="Local CLIP",
        env_key=None,
        endpoint="",
        style=LOCAL,
    ),
}


@dataclass(frozen=True)
class Tier:
    """One rung of the fallback ladder."""

    index: int
    provider: Provider
    model: str
    game_capable: bool = True


def _tier(index: int, slug: str, model: str, game_capable: bool = True) -> Tier:
    return Tier(index=index, provider=PROVIDERS[slug], model=model, game_capable=game_capable)


#: The canonical 14-rung ladder for real-world scans.
#:
#: Ordering is deliberate: the fastest reliable model that is good enough
#: goes first, the strongest vision models follow, and the local bunker is
#: always last so a fully offline machine still produces an answer.
#:
#: Note: the former "GitHub Models" rungs were removed. GitHub retired the
#: whole GitHub Models service (playground, catalog, inference API and BYOK)
#: on 2026-07-30, so those rungs could never fire again. Their slots are
#: taken by current Gemini models and by OpenAI.
REAL_WORLD_TIERS: tuple[Tier, ...] = (
    _tier(1, "gemini", "gemini-3.1-flash-lite"),
    _tier(2, "groq", "qwen/qwen3.8-27b"),
    _tier(3, "openai", "gpt-4o"),
    _tier(4, "openai", "gpt-4o-mini"),
    _tier(5, "gemini", "gemini-3.6-flash"),
    _tier(6, "gemini", "gemini-3.5-flash"),
    _tier(7, "gemini", "gemini-3.7-flash"),
    _tier(8, "gemini", "gemini-3.8-flash"),
    _tier(9, "gemini", "gemini-3.5-flash-lite"),
    _tier(10, "gemini", "gemini-3-flash-preview"),
    _tier(11, "gemini", "gemini-2.5-flash"),
    _tier(12, "gemini", "gemini-2.5-flash-lite"),
    _tier(13, "gemini", "gemini-3.1-pro-preview"),
    _tier(14, "local", "clip-vit-base-patch32", game_capable=False),
)

#: Game mode reorders the ladder: the local bunker cannot crack a seed, and
#: the fastest vision model is the best first guess.
GAME_TIERS: tuple[Tier, ...] = (
    _tier(1, "groq", "qwen/qwen3.8-27b"),
    _tier(2, "openai", "gpt-4o"),
    _tier(3, "openai", "gpt-4o-mini"),
    _tier(4, "gemini", "gemini-3.1-flash-lite"),
    _tier(5, "gemini", "gemini-3.6-flash"),
    _tier(6, "gemini", "gemini-3.5-flash"),
    _tier(7, "gemini", "gemini-3.7-flash"),
    _tier(8, "gemini", "gemini-3.8-flash"),
    _tier(9, "gemini", "gemini-3.5-flash-lite"),
    _tier(10, "gemini", "gemini-3-flash-preview"),
    _tier(11, "gemini", "gemini-2.5-flash"),
    _tier(12, "gemini", "gemini-2.5-flash-lite"),
    _tier(13, "gemini", "gemini-3.1-pro-preview"),
)

#: ``model`` values the API accepts.
MODEL_CHOICES: tuple[str, ...] = (
    "auto",
    "gemini-only",
    "groq-only",
    "openai-only",
    "local-only",
)

_PROVIDER_FOR_MODE = {
    "gemini-only": "gemini",
    "groq-only": "groq",
    "openai-only": "openai",
    "local-only": "local",
}


# --------------------------------------------------------------------------
# Key handling
# --------------------------------------------------------------------------

#: The BYOK form field a provider's key arrives in.
BYOK_FIELD_FOR_PROVIDER = {
    "gemini": "gemini_key",
    "groq": "groq_key",
    "openai": "openai_key",
}

#: Well-known key prefixes, used to reject obvious garbage before a key is
#: ever placed in a URL, a header or a log line.
KEY_PREFIXES = {
    "groq": "gsk_",
    "gemini": "AIza",
    "openai": "sk-",
}

_KEY_BODY_RE = re.compile(r"^[A-Za-z0-9_\-]{8,}$")


class KeyValidationError(ValueError):
    """Raised when an operator-supplied key is malformed."""

    def __init__(self, provider: str, reason: str) -> None:
        super().__init__(reason)
        self.provider = provider
        self.reason = reason


def validate_key(provider_slug: str, raw: str | None) -> str | None:
    """Validate a BYOK key.

    Returns the cleaned key, or ``None`` when no key was supplied. Raises
    :class:`KeyValidationError` for a key that is present but malformed --
    silently ignoring a typo'd key would hide the reason a scan failed.
    """
    if raw is None:
        return None
    key = raw.strip()
    if not key:
        return None
    if len(key) > 300:
        raise KeyValidationError(provider_slug, "key is implausibly long")
    prefix = KEY_PREFIXES.get(provider_slug)
    if prefix and not key.startswith(prefix):
        raise KeyValidationError(
            provider_slug,
            f"key does not look like a {PROVIDERS[provider_slug].label} key "
            f"(expected a {prefix!r} prefix)",
        )
    body = key[len(prefix):] if prefix else key
    if not _KEY_BODY_RE.match(body):
        raise KeyValidationError(
            provider_slug, "key contains characters that are not valid in an API key"
        )
    return key


def _fingerprint(key: str) -> str:
    """One-way, non-reversible fingerprint used for cache namespacing."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def key_scope(effective_keys: dict[str, str]) -> str:
    """Namespace tag for cache entries.

    Results produced with an operator's own key are kept apart from results
    produced with the deployment's shared keys, so a BYOK scan never serves
    (or overwrites) a shared-cache entry and vice versa.
    """
    parts = sorted(f"{slug}:{_fingerprint(key)}" for slug, key in effective_keys.items() if key)
    if not parts:
        return "server"
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------

REAL_WORLD_PROMPT = (
    "Identify the location in this image. You MUST respond with ONLY the location "
    "name in this exact format: [NAME: City, Country]. Do NOT provide any description, "
    "reasoning, or extra text."
)


def game_prompt(game: str) -> str:
    return (
        f"Analyze this {game} screenshot. Identify the exact natural biome or terrain "
        "type (e.g., Plains Coast, Ocean, Forest), explicitly ignoring player-built "
        "structures for the location. Estimate the specific game version based on "
        "textures/lighting (e.g., Alpha 1.2, Java 1.20), dimension, XYZ coordinates, "
        "and generate a highly unique 10-digit World Seed based on the natural terrain "
        "generation. Format strictly: [LOC: Natural Biome/Terrain] [X: int] [Y: int] "
        "[Z: int] [VER: Specific Version] [DIM: Dimension] [SEED: unique 10-digit number]"
    )


# --------------------------------------------------------------------------
# Local CLIP bunker
# --------------------------------------------------------------------------

#: A deliberately wide, visually distinctive label set. CLIP is a *weak*
#: geolocator, so the label set is the main lever on its accuracy.
LOCAL_LABELS: tuple[str, ...] = (
    "Manarola, Italy",
    "Cinque Terre, Italy",
    "Santorini, Greece",
    "Sagrada Familia, Barcelona, Spain",
    "Alhambra, Granada, Spain",
    "Colosseum, Rome, Italy",
    "Eiffel Tower, Paris, France",
    "Louvre, Paris, France",
    "Big Ben, London, United Kingdom",
    "Tower Bridge, London, United Kingdom",
    "Times Square, New York, United States",
    "Golden Gate Bridge, San Francisco, United States",
    "Statue of Liberty, New York, United States",
    "Grand Canyon, Arizona, United States",
    "Hollywood Sign, Los Angeles, United States",
    "CN Tower, Toronto, Canada",
    "Christ the Redeemer, Rio de Janeiro, Brazil",
    "Machu Picchu, Peru",
    "Taj Mahal, Agra, India",
    "Great Wall of China, China",
    "Forbidden City, Beijing, China",
    "Temple of Angkor Wat, Cambodia",
    "Sydney Opera House, Australia",
    "Uluru, Australia",
    "Hagia Sophia, Istanbul, Turkey",
    "Petra, Jordan",
    "Pyramids of Giza, Egypt",
    "Burj Khalifa, Dubai, United Arab Emirates",
    "Burj Al Arab, Dubai, United Arab Emirates",
    "Tower of London, London, United Kingdom",
    "Brandenburg Gate, Berlin, Germany",
    "Neuschwanstein Castle, Germany",
    "Charles Bridge, Prague, Czech Republic",
    "Trevi Fountain, Rome, Italy",
    "Rialto Bridge, Venice, Italy",
    "Pompeii, Italy",
    "Sagrada Familia, Barcelona, Spain",
    "Acropolis, Athens, Greece",
    "Blue Mosque, Istanbul, Turkey",
    "Cappadocia, Turkey",
    "Hobbiton, New Zealand",
    "Uluru Kata Tjuta, Australia",
    "Cape Town, South Africa",
    "Table Mountain, Cape Town, South Africa",
    "Kruger National Park, South Africa",
    "Serra do Cipó, Brazil",
    "Iguazu Falls, Argentina",
    "Perito Moreno Glacier, Argentina",
    "Torres del Paine, Chile",
    "Hanoi, Vietnam",
    "Angkor Wat, Cambodia",
    "Shibuya Crossing, Tokyo, Japan",
    "Fushimi Inari, Kyoto, Japan",
    "Mount Fuji, Japan",
    "Itsukushima Shrine, Japan",
    "Seoul, South Korea",
    "Bangkok, Thailand",
    "Singapore, Singapore",
    "Kuala Lumpur, Malaysia",
    "Luang Prabang, Laos",
    "Hanoi Old Quarter, Vietnam",
    "Bagan, Myanmar",
    "Taj Mahal, Agra, India",
    "Gateway of India, Mumbai, India",
    "Varanasi, India",
    "Marrakesh, Morocco",
    "Chefchaouen, Morocco",
    "Fes, Morocco",
    "Cape Town Stadium, South Africa",
    "Cliffs of Moher, Ireland",
    "Giant's Causeway, Ireland",
    "Edinburgh Castle, Scotland",
    "Lake District, England",
    "Venice Grand Canal, Italy",
    "Amsterdam Canals, Netherlands",
    "Krujë Castle, Albania",
    "Plitvice Lakes, Croatia",
    "Kotor, Montenegro",
    "Hallstatt, Austria",
    "Salzburg, Austria",
    "Matterhorn, Switzerland",
    "Interlaken, Switzerland",
    "Lofoten Islands, Norway",
    "Bergen, Norway",
    "Stockholm, Sweden",
    "Copenhagen, Denmark",
    "Kronborg Castle, Denmark",
    "Palace of the Lost City of Petra, Jordan",
    "Easter Island, Chile",
    "Machu Picchu, Cusco Region, Peru",
    "Salar de Uyuni, Bolivia",
    "Atacama Desert, Chile",
)

#: Prompt ensemble -- averaging several phrasings measurably improves CLIP
#: zero-shot accuracy over a single template.
LOCAL_TEMPLATES: tuple[str, ...] = (
    "a photo of {}",
    "a photo taken in {}",
    "a photo of the landmark {}",
)

_LOCAL_MODEL = None
_LOCAL_PROCESSOR = None
_LOCAL_LOCK = threading.Lock()


def local_model_available() -> bool:
    """True when the optional local-model extras are importable."""
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except Exception:
        return False
    return True


def _init_local_bunker():
    """Lazily load CLIP. Returns ``(model, processor)`` or ``(None, None)``."""
    global _LOCAL_MODEL, _LOCAL_PROCESSOR
    if _LOCAL_MODEL is not None:
        return _LOCAL_MODEL, _LOCAL_PROCESSOR
    with _LOCAL_LOCK:
        if _LOCAL_MODEL is not None:
            return _LOCAL_MODEL, _LOCAL_PROCESSOR
        try:
            os.makedirs(MODEL_CACHE_DIR, exist_ok=True)
            os.environ.setdefault("HF_HOME", MODEL_CACHE_DIR)
            os.environ.setdefault("HUGGINGFACE_HUB_CACHE", os.path.join(MODEL_CACHE_DIR, "hub"))
            os.environ.setdefault("TRANSFORMERS_CACHE", os.path.join(MODEL_CACHE_DIR, "transformers"))
            from transformers import CLIPModel, CLIPProcessor

            model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
            processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
            model.eval()
            _LOCAL_MODEL, _LOCAL_PROCESSOR = model, processor
        except Exception as exc:  # pragma: no cover - environment dependent
            print(f"[local] bunker unavailable: {type(exc).__name__}: {exc}")
            return None, None
    return _LOCAL_MODEL, _LOCAL_PROCESSOR


def _as_feature_tensor(output):
    """Extract the feature tensor from a CLIP output.

    ``transformers`` v5 returns a ``BaseModelOutputWithPooling`` whose
    ``pooler_output`` holds the projected features; v4 returned the tensor
    directly. Support both so the bunker is not pinned to one release.
    """
    import torch

    if isinstance(output, torch.Tensor):
        return output
    for attribute in ("pooler_output", "last_hidden_state", "text_embeds", "image_embeds"):
        value = getattr(output, attribute, None)
        if isinstance(value, torch.Tensor):
            return value
    if isinstance(output, (tuple, list)) and output and isinstance(output[0], torch.Tensor):
        return output[0]
    raise TypeError(f"unrecognised CLIP feature output: {type(output).__name__}")


def call_local_engine(image_bytes: bytes) -> tuple[str | None, float]:
    """Classify an image with the local CLIP bunker.

    Returns ``(label, score)`` where ``score`` is the model's confidence in
    that label, or ``(None, 0.0)`` when the bunker is unavailable.
    """
    model, processor = _init_local_bunker()
    if model is None or processor is None:
        return None, 0.0
    try:
        import torch

        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        prompts = [tpl.format(label) for label in LOCAL_LABELS for tpl in LOCAL_TEMPLATES]
        text_inputs = processor(text=prompts, return_tensors="pt", padding=True)
        image_inputs = processor(images=image, return_tensors="pt")

        with torch.no_grad():
            text_features = _as_feature_tensor(model.get_text_features(**text_inputs))
            image_features = _as_feature_tensor(model.get_image_features(**image_inputs))

            n_templates = len(LOCAL_TEMPLATES)
            text_features = text_features / text_features.norm(dim=-1, keepdim=True)
            text_features = text_features.reshape(len(LOCAL_LABELS), n_templates, -1).mean(dim=1)
            text_features = text_features / text_features.norm(dim=-1, keepdim=True)

            image_features = image_features / image_features.norm(dim=-1, keepdim=True)
            logits = (image_features @ text_features.T) * 100.0
            probs = logits.softmax(dim=-1)[0]
            best_idx = int(probs.argmax().item())

        return LOCAL_LABELS[best_idx], float(probs[best_idx].item())
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"[local] inference failed: {type(exc).__name__}: {exc}")
        return None, 0.0


# --------------------------------------------------------------------------
# Location parsing
# --------------------------------------------------------------------------

_PLACE_WORD = r"[A-Z][\w'’\-\.]*"
_PLACE_PHRASE = rf"{_PLACE_WORD}(?:[ \-]{_PLACE_WORD})*"
#: A place name may carry several comma-separated levels
#: ("Eiffel Tower, Paris, France"), so match the whole chain rather than a
#: fixed pair -- otherwise the country is dropped from the candidate.
_PLACE_SEQUENCE = rf"{_PLACE_PHRASE}(?:\s*,\s*{_PLACE_PHRASE}){{1,3}}"

#: Conversational lead-ins, longest first so that "is located in" wins over
#: a bare "in". ``\b`` on both sides stops the match from firing inside a
#: longer word.
_LEAD_INS = (
    "is located in",
    "was taken in",
    "was taken at",
    "located in",
    "located at",
    "taken at",
    "taken in",
    "shot in",
    "photographed in",
    "captured in",
    "this is",
    "is in",
    "at",
    "in",
    "of",
)
_LEAD_IN_RE = "|".join(re.escape(x) for x in _LEAD_INS)


def _clean_place(raw: str) -> str:
    return re.sub(r"\s+", " ", raw).strip(" .,;:'\"()[]")


#: Strings a model emits when it cannot name a place. These must never be
#: geocoded: Nominatim will happily resolve "N/A, N/A" to some arbitrary
#: village, and the operator would be shown a confident pin in the wrong
#: country.
_PLACEHOLDER_TOKENS = frozenset(
    {
        "n/a",
        "na",
        "n.a.",
        "n a",
        "none",
        "null",
        "nil",
        "unknown",
        "unknowable",
        "undetermined",
        "unidentified",
        "indeterminate",
        "not sure",
        "unsure",
        "no location",
        "not identifiable",
        "cannot identify",
        "can not identify",
        "no location identifiable",
        "cannot be determined",
        "not available",
        "unavailable",
        "no answer",
        "not specified",
        "unspecified",
        "undefined",
        "error",
        "blank",
        "empty",
        "the image",
        "the picture",
        "the photo",
        "the screenshot",
        "this image",
        "image",
        "earth",
        "world",
        "globe",
    }
)

_PLACEHOLDER_PHRASES = (
    "cannot identify",
    "can not identify",
    "no location identifiable",
    "cannot be determined",
    "unable to determine",
    "not enough information",
    "not possible to determine",
    "i cannot",
    "i'm unable",
    "i am unable",
)


def _is_placeholder(candidate: str) -> bool:
    """True when a candidate is a non-answer rather than a place name."""
    normalised = candidate.strip().lower()
    if not normalised:
        return True
    if any(phrase in normalised for phrase in _PLACEHOLDER_PHRASES):
        return True
    parts = [part.strip(" .") for part in normalised.split(",")]
    parts = [part for part in parts if part]
    if not parts:
        return True
    return all(part in _PLACEHOLDER_TOKENS for part in parts)


def extract_location_candidates(text: str) -> list[str]:
    """Rank plausible place names mentioned in a model response.

    Returns candidates best-first. A model that follows the prompt yields
    exactly one candidate via the ``[NAME: ...]`` tag; a model that rambles
    still yields usable candidates via the conversational and
    "City, Country" fallbacks. Non-answers ("N/A", "Unknown") are dropped.
    """
    if not text:
        return []

    candidates: list[str] = []
    rejected: list[str] = []
    tag_seen = False

    def add(candidate: str) -> None:
        cleaned = _clean_place(candidate)
        if not cleaned:
            return
        lowered = cleaned.lower()
        if _is_placeholder(cleaned):
            # Remember it: a looser regex will often re-find a fragment of a
            # rejected answer ("A, N" inside "N/A, N/A"), and that fragment
            # must not slip through as a place name.
            rejected.append(lowered)
            return
        if any(lowered in previous for previous in rejected):
            return
        if cleaned in candidates:
            return
        candidates.append(cleaned)

    # 1. Explicit tag -- the contract every prompt asks for.
    for match in re.finditer(r"\[NAME:\s*([^\]]+)\]", text, re.IGNORECASE):
        tag_seen = True
        add(match.group(1))

    # 2. Other bracketed location tags some models prefer.
    for match in re.finditer(r"\[(?:LOCATION|PLACE|CITY|COUNTRY)\s*:\s*([^\]]+)\]", text, re.IGNORECASE):
        tag_seen = True
        add(match.group(1))

    # 3. Conversational lead-in. Requires a capitalised "A, B" pair so that
    #    filler ("in the middle of the city") cannot masquerade as a place.
    for match in re.finditer(
        rf"\b(?:{_LEAD_IN_RE})\s+({_PLACE_SEQUENCE})",
        text,
    ):
        add(match.group(1))

    # 4. Generic comma-separated place names anywhere in the text.
    for match in re.finditer(rf"\b({_PLACE_SEQUENCE})\b", text):
        add(match.group(1))

    # 5. Last resort: the first non-empty line, cleaned of markdown. Skipped
    #    when the model used a tag, because the tag content was already
    #    considered (and rejected if it was a non-answer).
    if not candidates and not tag_seen:
        for line in text.splitlines():
            stripped = _clean_place(line.replace("**", ""))
            if stripped:
                add(stripped)
                break

    # 6. Degrade a three-level name to its last two levels, so a candidate
    #    like "Eiffel Tower, Paris, France" also yields "Paris, France".
    for candidate in list(candidates):
        parts = [part.strip() for part in candidate.split(",") if part.strip()]
        if len(parts) >= 3:
            add(", ".join(parts[-2:]))

    return candidates[:8]


def _comma_variants(candidate: str) -> list[str]:
    """Progressively looser forms of a comma-separated place name.

    Ordered best-first: the full name, then the last two levels (usually
    "City, Country", which geocodes far better than a landmark name paired
    with a country), then the first two levels, then the outermost pair.
    """
    parts = [p.strip() for p in candidate.split(",") if p.strip()]
    variants: list[str] = [candidate]
    if len(parts) >= 3:
        variants.append(", ".join(parts[-2:]))
        variants.append(", ".join(parts[:2]))
        variants.append(f"{parts[0]}, {parts[-1]}")
        variants.append(", ".join(parts[1:]))
    elif len(parts) == 2:
        variants.append(f"{parts[0]}, {parts[-1]}")

    deduped: list[str] = []
    for variant in variants:
        if variant and variant not in deduped:
            deduped.append(variant)
    return deduped


def parse_game_response(
    text: str, game: str
) -> tuple[str, int, int, int, str, str, str, int]:
    """Extract the structured game fields from a model response.

    The eighth element counts how many fields actually parsed, so the caller
    can report an honest confidence instead of a flat number.
    """
    loc = f"Procedural Sector ({game})"
    x, y, z = 0, 64, 0
    ver, dim, seed = "Unknown", "Unknown", "0000000000"
    complete = 0

    def grab(pattern: str) -> str | None:
        match = re.search(pattern, text, re.IGNORECASE)
        return match.group(1).strip() if match else None

    loc_value = grab(r"\[LOC:\s*(.*?)\]")
    x_value = grab(r"\[X:\s*(-?\d+)\]")
    y_value = grab(r"\[Y:\s*(-?\d+)\]")
    z_value = grab(r"\[Z:\s*(-?\d+)\]")
    ver_value = grab(r"\[VER:\s*(.*?)\]")
    dim_value = grab(r"\[DIM:\s*(.*?)\]")
    seed_value = grab(r"\[SEED:\s*(-?\d+)\]")

    if loc_value:
        loc = loc_value
        complete += 1
    if x_value:
        x = int(x_value)
        complete += 1
    if y_value:
        y = int(y_value)
        complete += 1
    if z_value:
        z = int(z_value)
        complete += 1
    if ver_value:
        ver = ver_value
        complete += 1
    if dim_value:
        dim = dim_value
        complete += 1
    if seed_value:
        seed = seed_value
        complete += 1

    return loc, x, y, z, ver, dim, seed, complete


# --------------------------------------------------------------------------
# Rate-limited geocoder
# --------------------------------------------------------------------------


class Geocoder:
    """Nominatim wrapper that honours the one-request-per-second policy."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_request = 0.0
        self._geolocator = Nominatim(user_agent="pinpoint-os/2.0 (+https://github.com/velo4705)")

    def _wait_turn(self) -> None:
        with self._lock:
            delta = time.monotonic() - self._last_request
            if delta < NOMINATIM_MIN_INTERVAL:
                time.sleep(NOMINATIM_MIN_INTERVAL - delta)
            self._last_request = time.monotonic()

    def geocode(self, query: str):
        self._wait_turn()
        return self._geolocator.geocode(
            query, addressdetails=True, language="en", timeout=10, exactly_one=True
        )


# --------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------


@dataclass
class Prediction:
    """A single successful model response."""

    text: str
    source: str
    tier: int
    confidence: float


class AIEngine:
    def __init__(self) -> None:
        self.geocoder = Geocoder()
        self.redis = self._connect_redis()

    # -- infrastructure ----------------------------------------------------

    @staticmethod
    def _connect_redis():
        try:
            redis_url = os.getenv("REDIS_URL")
            if not redis_url:
                print("[cache] REDIS_URL not set -- running stateless")
                return None
            import redis as redis_lib

            client = redis_lib.from_url(redis_url, decode_responses=True)
            client.ping()
            print("[cache] connected to Redis")
            return client
        except Exception as exc:
            print(f"[cache] offline ({type(exc).__name__}) -- running stateless")
            return None

    @staticmethod
    def _resolve_keys(byok: dict[str, str] | None) -> tuple[dict[str, str], list[str]]:
        """Merge BYOK keys over the server keys.

        Returns ``(effective_keys, errors)``. A malformed key is reported
        rather than silently dropped so the operator learns why their scan
        produced nothing.
        """
        effective: dict[str, str] = {}
        errors: list[str] = []
        byok = byok or {}
        for slug, provider in PROVIDERS.items():
            if provider.env_key is None:
                continue
            supplied = byok.get(slug)
            if supplied:
                try:
                    validated = validate_key(slug, supplied)
                except KeyValidationError as exc:
                    errors.append(f"{provider.label}: {exc.reason}")
                    continue
                if validated:
                    effective[slug] = validated
                    continue
            server_value = os.getenv(provider.env_key) or ""
            if server_value.strip():
                effective[slug] = server_value.strip()
        return effective, errors

    # -- provider calls ----------------------------------------------------

    def _call_gemini(self, provider: Provider, model: str, b64: str, prompt: str, key: str) -> str | None:
        url = provider.endpoint.format(model=model)
        payload = {
            "contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": "image/jpeg", "data": b64}}]}]
        }
        try:
            response = requests.post(
                f"{url}?key={key}", json=payload, timeout=15, headers={"Content-Type": "application/json"}
            )
            if response.status_code != 200:
                print(f"[{provider.slug}/{model}] HTTP {response.status_code}")
                return None
            parts = response.json()["candidates"][0]["content"]["parts"]
            texts = [part.get("text", "") for part in parts if part.get("text")]
            if not texts:
                return None
            # Thinking models emit a reasoning part before the answer. Prefer
            # the last part that actually carries a structured tag, so a
            # thought cannot masquerade as the model's conclusion.
            for text in reversed(texts):
                if re.search(r"\[(NAME|LOC|SEED|VER|DIM|X|Y|Z)\s*:", text, re.IGNORECASE):
                    return text.strip()
            return texts[-1].strip() or None
        except Exception as exc:
            print(f"[{provider.slug}/{model}] {type(exc).__name__}: {exc}")
            return None

    def _call_openai_chat(
        self, provider: Provider, model: str, b64: str, prompt: str, key: str
    ) -> str | None:
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            **{name: value for name, value in provider.extra_headers},
        }
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                }
            ],
            "max_tokens": 256,
        }
        try:
            response = requests.post(provider.endpoint, headers=headers, json=payload, timeout=15)
            if response.status_code != 200:
                print(f"[{provider.slug}/{model}] HTTP {response.status_code}")
                return None
            content = response.json()["choices"][0]["message"]["content"]
            return (content or "").strip() or None
        except Exception as exc:
            print(f"[{provider.slug}/{model}] {type(exc).__name__}: {exc}")
            return None

    def _call_tier(
        self,
        tier: Tier,
        image_bytes: bytes,
        b64: str,
        prompt: str,
        keys: dict[str, str],
    ) -> Prediction | None:
        provider = tier.provider
        if provider.style == LOCAL:
            label, score = call_local_engine(image_bytes)
            if not label:
                return None
            # CLIP's zero-shot softmax is not a probability of *correctness*;
            # it is a relative score across a fixed label set. Cap it well
            # below the cloud tiers so the UI never overstates a guess.
            confidence = max(0.05, min(0.6, round(score, 4)))
            return Prediction(
                text=f"[NAME: {label}]",
                source=f"Local CLIP ({tier.model})",
                tier=tier.index,
                confidence=confidence,
            )

        key = keys.get(provider.slug)
        if not key:
            return None

        if provider.style == GEMINI:
            text = self._call_gemini(provider, tier.model, b64, prompt, key)
        else:
            text = self._call_openai_chat(provider, tier.model, b64, prompt, key)
        if not text:
            return None
        return Prediction(
            text=text,
            source=f"{provider.label}({tier.model})",
            tier=tier.index,
            confidence=0.88,
        )

    def _select_tiers(self, model: str, mode: str) -> tuple[Tier, ...]:
        ladder = GAME_TIERS if mode == "game" else REAL_WORLD_TIERS
        if model == "auto":
            selected = ladder
        else:
            slug = _PROVIDER_FOR_MODE.get(model)
            if slug is None:
                return ()
            selected = tuple(t for t in ladder if t.provider.slug == slug)
        if mode == "game":
            selected = tuple(t for t in selected if t.game_capable)
        return selected

    # -- public API --------------------------------------------------------

    def scan_real_world(
        self,
        image_bytes: bytes,
        model: str = "auto",
        byok: dict[str, str] | None = None,
    ) -> dict:
        keys, key_errors = self._resolve_keys(byok)
        if key_errors:
            return {"error": "Invalid API key: " + "; ".join(key_errors)}

        scope = key_scope(keys)
        img_hash = hashlib.md5(image_bytes).hexdigest()
        img_cache_key = f"pinpoint:img:{img_hash}:{model}:{scope}"

        if self.redis:
            cached = self.redis.get(img_cache_key)
            if cached:
                print(f"[cache] image hit {img_hash[:8]} scope={scope}")
                return json.loads(cached)

        b64 = base64.b64encode(image_bytes).decode("utf-8")
        deadline = time.monotonic() + SCAN_DEADLINE_SECONDS

        prediction: Prediction | None = None
        candidates: list[str] = []
        for tier in self._select_tiers(model, "real-world"):
            if time.monotonic() > deadline:
                print("[scan] deadline reached -- stopping cascade")
                break
            attempt = self._call_tier(tier, image_bytes, b64, REAL_WORLD_PROMPT, keys)
            if not attempt:
                continue
            attempt_candidates = extract_location_candidates(attempt.text)
            if not attempt_candidates:
                # The model answered, but not with a place ("[NAME: Unknown,
                # Unknown]"). A non-answer is a failed rung, so keep
                # descending the ladder rather than pinning a guess.
                print(f"[{tier.provider.label}/{tier.model}] no usable place name -- next rung")
                continue
            prediction, candidates = attempt, attempt_candidates
            break

        if not prediction or not candidates:
            return {"error": self._no_tier_message(model, keys)}

        location, coords, _attempts = self._map_lock(candidates)
        if not coords:
            return {
                "error": f"Map lock failed. AI predicted: '{candidates[0][:120]}'",
                "candidates": candidates,
            }

        result = {
            "location": location,
            "coordinates": {"lat": coords[0], "lng": coords[1]},
            "confidence": self._confidence_for(prediction, location),
            "source": prediction.source,
            "tier": prediction.tier,
            "mode": "real-world",
            "insights": [f"Source: {prediction.source}", f"Tier: {prediction.tier}"],
        }
        self._store_caches(img_cache_key, location, coords, result)
        return result

    def scan_game(
        self,
        image_bytes: bytes,
        game_name: str,
        model: str = "auto",
        byok: dict[str, str] | None = None,
    ) -> dict:
        keys, key_errors = self._resolve_keys(byok)
        if key_errors:
            return {"error": "Invalid API key: " + "; ".join(key_errors)}

        if model == "local-only":
            return {
                "error": (
                    "The local CLIP bunker cannot crack world seeds. "
                    "Choose Automatic, Groq, Gemini or OpenAI for gaming mode."
                )
            }

        scope = key_scope(keys)
        img_hash = hashlib.md5(image_bytes).hexdigest()
        img_cache_key = f"pinpoint:game:{img_hash}:{model}:{scope}"

        if self.redis:
            cached = self.redis.get(img_cache_key)
            if cached:
                print(f"[cache] game hit {img_hash[:8]} scope={scope}")
                return json.loads(cached)

        b64 = base64.b64encode(image_bytes).decode("utf-8")
        prompt = game_prompt(game_name)
        deadline = time.monotonic() + SCAN_DEADLINE_SECONDS

        prediction: Prediction | None = None
        parsed: tuple[str, int, int, int, str, str, str, int] | None = None
        for tier in self._select_tiers(model, "game"):
            if time.monotonic() > deadline:
                print("[scan] deadline reached -- stopping cascade")
                break
            attempt = self._call_tier(tier, image_bytes, b64, prompt, keys)
            if not attempt:
                continue
            attempt_parsed = parse_game_response(attempt.text, game_name)
            if attempt_parsed[7] < 2:
                # Not enough of the structured answer came back to be useful.
                print(f"[{tier.provider.label}/{tier.model}] incomplete game readout -- next rung")
                continue
            prediction, parsed = attempt, attempt_parsed
            break

        if not prediction or parsed is None:
            return {"error": self._no_tier_message(model, keys)}

        loc, x, y, z, ver, dim, seed, complete = parsed
        # Confidence tracks how much of the structured answer actually parsed.
        confidence = round(min(0.95, 0.3 + 0.09 * complete), 2)

        result = {
            "game": game_name,
            "location": loc,
            "coordinates": {"x": x, "y": y, "z": z},
            "seed": seed,
            "version": ver,
            "type": dim,
            "mode": "game",
            "confidence": confidence,
            "source": prediction.source,
            "tier": prediction.tier,
            "insights": [f"Engine: {prediction.source}", f"Tier: {prediction.tier}"],
        }
        if self.redis:
            self.redis.setex(img_cache_key, IMAGE_TTL_SECONDS, json.dumps(result))
        return result

    @staticmethod
    def _confidence_for(prediction: Prediction, resolved_location: str) -> float:
        """Confidence reflects how much we actually know.

        A cloud model that produced a city *and* a country is a much stronger
        claim than one that produced a single token, so the former earns a
        higher score. The local bunker keeps its own (low) score.
        """
        if prediction.source.startswith("Local"):
            return prediction.confidence
        confidence = prediction.confidence
        if "," in resolved_location:
            confidence = min(0.93, confidence + 0.05)
        return round(confidence, 2)

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _no_tier_message(model: str, keys: dict[str, str], game: bool = False) -> str:
        if not keys:
            return (
                "No AI tier is reachable. Supply a Groq, Gemini or OpenAI key "
                "(BYOK in Settings, or server-side environment variables), or install the "
                "local model extras to enable the offline CLIP bunker."
            )
        if model != "auto":
            return f"Requested scanner '{model}' failed to process the image."
        return "Every AI tier failed to process the image. Try again shortly."

    def _map_lock(self, candidates: Sequence[str]) -> tuple[str | None, tuple[float, float] | None, int]:
        """Geocode the ranked candidates, first hit wins.

        The geocode cache is checked before Nominatim is contacted, so a
        location that has been resolved before costs zero upstream requests.
        """
        attempts = 0
        for candidate in candidates:
            for variant in _comma_variants(candidate):
                if attempts >= MAX_GEOCODE_ATTEMPTS:
                    return None, None, attempts
                attempts += 1

                cached = self._read_geo_cache(variant)
                if cached is not None:
                    return variant, cached, attempts

                try:
                    location = self.geocoder.geocode(variant)
                except Exception as exc:
                    print(f"[geocode] {type(exc).__name__}: {exc}")
                    continue
                if location is not None:
                    return variant, (location.latitude, location.longitude), attempts
        return None, None, attempts

    @staticmethod
    def _geo_cache_key(location: str) -> str:
        return "pinpoint:geo:" + re.sub(r"[^a-z0-9]+", "_", location.lower()).strip("_")[:120]

    def _read_geo_cache(self, location: str) -> tuple[float, float] | None:
        if not self.redis:
            return None
        try:
            raw = self.redis.get(self._geo_cache_key(location))
            if not raw:
                return None
            data = json.loads(raw)
            return float(data["lat"]), float(data["lng"])
        except Exception:
            return None

    def _store_caches(
        self,
        img_cache_key: str,
        location: str,
        coords: tuple[float, float],
        result: dict,
    ) -> None:
        if not self.redis:
            return
        try:
            self.redis.setex(
                self._geo_cache_key(location), GEO_TTL_SECONDS, json.dumps({"lat": coords[0], "lng": coords[1]})
            )
            self.redis.setex(img_cache_key, IMAGE_TTL_SECONDS, json.dumps(result))
        except Exception as exc:
            print(f"[cache] write failed: {type(exc).__name__}")


def warm_local_bunker() -> None:
    """Load the CLIP bunker in the background so the first scan is not slow.

    The first load pulls roughly 600 MB of weights; doing it on a background
    thread at startup means the bunker is warm by the time an operator needs
    it instead of stalling their first request for two minutes.
    """
    if not local_model_available():
        print("[local] extras not installed -- the offline bunker stays disabled")
        return

    def _warm() -> None:
        started = time.monotonic()
        model, _ = _init_local_bunker()
        if model is None:
            print("[local] warm-up failed")
            return
        print(f"[local] bunker warm in {time.monotonic() - started:.1f}s")

    threading.Thread(target=_warm, name="pinpoint-local-warmup", daemon=True).start()


_engine: AIEngine | None = None
_engine_lock = threading.Lock()


def get_engine() -> AIEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = AIEngine()
    return _engine
