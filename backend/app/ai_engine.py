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
import json
import math
import os
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from typing import Sequence

import requests
from dotenv import load_dotenv
from geopy.geocoders import Nominatim

from app.local_model import LocalModel

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

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
        label="Offline",
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


# --------------------------------------------------------------------------
# Model catalogue
# --------------------------------------------------------------------------
#
# One source of truth for which models exist, what they are called, and where
# they sit in the fallback ladder. The ladder is generated from this, so a
# model can never be offered in the UI without also being reachable, and the
# two can never drift apart.
#
# The tier order is by *measured accuracy*, not by cost. A fast, cheap model
# that answers confidently and wrongly is far more damaging than a slow one
# that is right, so the cheap-and-shaky rungs sit near the bottom.
#
# On an eight-image benchmark of geotagged Commons photos, leading with
# `gemini-2.5-flash` put 7/8 answers inside 25 km of the truth, while the
# old ladder -- which tried `gemini-3.1-flash-lite` and then Groq -- put
# only 3/8 there and sent Porto to Buenos Aires and Marrakesh to Kabul.
#
# Note: the former "GitHub Models" rungs were removed. GitHub retired the
# whole GitHub Models service (playground, catalog, inference API and BYOK)
# on 2026-07-30, so those rungs could never fire again.


@dataclass(frozen=True)
class ModelEntry:
    """One concrete model."""

    id: str
    label: str
    note: str = ""
    tier: int = 99
    game_capable: bool = True


@dataclass(frozen=True)
class ModelFamily:
    """A group of models the operator picks between.

    The picker shows families rather than individual models, because a
    provider's catalogue is mostly noise: Google alone ships half a dozen
    Flash revisions, and only one of them is ever the one you want. A
    family is a promise -- "give me the Flash line" -- and the members are
    tried in the order given, so a family that is temporarily unavailable
    falls through to its next member instead of failing.
    """

    id: str
    label: str
    note: str = ""
    models: tuple[ModelEntry, ...] = ()

    @property
    def best(self) -> ModelEntry | None:
        return self.models[0] if self.models else None


@dataclass(frozen=True)
class ProviderCatalogue:
    """A provider and the model families it offers."""

    slug: str
    label: str
    key_env: str | None
    hint: str
    families: tuple[ModelFamily, ...]
    #: The cheapest, steadiest model to use when probing this provider's key.
    probe_model: str = ""

    @property
    def models(self) -> tuple[ModelEntry, ...]:
        """Every model in every family, best family first."""
        return tuple(model for family in self.families for model in family.models)

    def family(self, family_id: str) -> ModelFamily | None:
        for family in self.families:
            if family.id == family_id:
                return family
        return None


MODEL_CATALOGUE: tuple[ProviderCatalogue, ...] = (
    ProviderCatalogue(
        slug="gemini",
        label="Gemini",
        key_env="GOOGLE_API_KEY",
        hint="Google DeepMind",
        probe_model="gemini-2.5-flash-lite",
        families=(
            ModelFamily(
                id="pro",
                label="Pro",
                note="strongest reasoning; preview build, quota-limited",
                models=(
                    ModelEntry("gemini-3.1-pro-preview", "3.1 Pro", "preview", tier=1),
                ),
            ),
            ModelFamily(
                id="flash",
                label="Flash",
                note="the accuracy workhorse",
                models=(
                    ModelEntry("gemini-2.5-flash", "2.5 Flash", "best measured accuracy", tier=3),
                    ModelEntry("gemini-3.6-flash", "3.6 Flash", "fast", tier=4),
                    ModelEntry("gemini-3.5-flash", "3.5 Flash", "fast", tier=5),
                    ModelEntry("gemini-3.7-flash", "3.7 Flash", "fast", tier=6),
                    ModelEntry("gemini-3.8-flash", "3.8 Flash", "fast", tier=7),
                    ModelEntry("gemini-3-flash-preview", "3 Flash", "preview", tier=8),
                ),
            ),
            ModelFamily(
                id="flash-lite",
                label="Flash-Lite",
                note="cheapest and quickest; less precise",
                models=(
                    ModelEntry("gemini-2.5-flash-lite", "2.5 Flash-Lite", "cheapest workhorse", tier=9),
                    ModelEntry("gemini-3.1-flash-lite-preview", "3.1 Flash-Lite", "preview", tier=10),
                ),
            ),
        ),
    ),
    ProviderCatalogue(
        slug="openai",
        label="OpenAI",
        key_env="OPENAI_API_KEY",
        hint="GPT vision family",
        probe_model="gpt-4o-mini",
        families=(
            ModelFamily(
                id="flagship",
                label="Flagship",
                note="strongest",
                models=(
                    ModelEntry("gpt-6-astra", "GPT-6 Astra", "flagship, strongest", tier=2),
                ),
            ),
            ModelFamily(
                id="balanced",
                label="Balanced",
                note="good accuracy, moderate cost",
                models=(
                    ModelEntry("gpt-6.1-sol", "GPT-6.1 Sol", "balanced", tier=8),
                ),
            ),
            ModelFamily(
                id="cheap",
                label="Cheap",
                note="lowest cost, fastest",
                models=(
                    ModelEntry("gpt-6-luna", "GPT-6 Luna", "cheapest, fastest", tier=14),
                ),
            ),
            ModelFamily(
                id="legacy",
                label="Legacy",
                note="older models; retire 2027-01-14",
                models=(
                    ModelEntry("gpt-4o", "GPT-4o", "legacy", tier=15),
                    ModelEntry("gpt-4o-mini", "GPT-4o mini", "legacy", tier=16),
                ),
            ),
        ),
    ),
    ProviderCatalogue(
        slug="groq",
        label="Groq",
        key_env="GROQ_API_KEY",
        hint="fastest inference",
        probe_model="qwen/qwen3.8-27b",
        families=(
            ModelFamily(
                id="fast",
                label="Fast",
                note="quick, but the least reliable at geolocation",
                models=(
                    ModelEntry("qwen/qwen3.8-27b", "Qwen 3.8 27B", "fast; least reliable at geolocation", tier=13),
                ),
            ),
        ),
    ),
    ProviderCatalogue(
        slug="local",
        label="Offline",
        key_env=None,
        hint="no key, no network, no cost",
        families=(
            ModelFamily(
                id="auto",
                label="Auto",
                note="GeoCLIP if prepared, else CLIP",
                models=(
                    ModelEntry("auto", "Auto", "GeoCLIP if prepared, else CLIP", tier=17, game_capable=False),
                ),
            ),
            ModelFamily(
                id="geoclip",
                label="GeoCLIP",
                note="accurate; returns coordinates",
                models=(
                    ModelEntry("geoclip", "GeoCLIP", "accurate; returns coordinates", tier=17, game_capable=False),
                ),
            ),
            ModelFamily(
                id="clip",
                label="CLIP zero-shot",
                note="lightweight; names only",
                models=(
                    ModelEntry("clip", "CLIP zero-shot", "lightweight; names only", tier=17, game_capable=False),
                ),
            ),
        ),
    ),
)


def _build_ladder() -> tuple[Tier, ...]:
    """Generate the tier ladder from the catalogue."""
    tiers: list[Tier] = []
    for provider in MODEL_CATALOGUE:
        if provider.slug == "local":
            continue
        for entry in provider.models:
            tiers.append(
                Tier(
                    index=entry.tier,
                    provider=PROVIDERS[provider.slug],
                    model=entry.id,
                    game_capable=entry.game_capable,
                )
            )
    tiers.sort(key=lambda tier: (tier.index, tier.provider.slug))
    # Renumber so the ladder reads 1..N whatever the catalogue says.
    return tuple(
        Tier(index=position, provider=tier.provider, model=tier.model, game_capable=tier.game_capable)
        for position, tier in enumerate(tiers, start=1)
    )


#: The canonical ladder for real-world scans.
REAL_WORLD_TIERS: tuple[Tier, ...] = _build_ladder()

#: Game mode drops the local bunker, which cannot crack a seed.
GAME_TIERS: tuple[Tier, ...] = tuple(
    tier for tier in REAL_WORLD_TIERS if tier.game_capable
)

def catalogue_for_api() -> dict:
    """The catalogue, shaped for the frontend.

    ``available`` reflects what this deployment can actually do. The local
    engine needs the optional extras and is absent on hosts that cannot
    spare the memory, such as a serverless function.
    """
    local_status = local_model.status()
    local_available = local_status["installed"]
    return {
        "providers": [
            {
                "slug": provider.slug,
                "label": provider.label,
                "hint": provider.hint,
                "keyEnv": provider.key_env,
                "available": local_available if provider.slug == "local" else True,
                "offlineReady": local_status["prepared"] if provider.slug == "local" else True,
                "note": local_status["detail"] if provider.slug == "local" else "",
                "families": [
                    {
                        "id": family.id,
                        "label": family.label,
                        "note": family.note,
                        "models": [
                            {
                                "id": entry.id,
                                "label": entry.label,
                                "note": entry.note,
                                "tier": entry.tier,
                                "gameCapable": entry.game_capable,
                            }
                            for entry in family.models
                        ],
                    }
                    for family in provider.families
                ],
            }
            for provider in MODEL_CATALOGUE
        ]
    }


def parse_model_selection(raw: str | None) -> list[str]:
    """Parse a ``provider:family,provider:family`` selection.

    Returns the qualified family ids in the order given. Unknown providers or
    families are dropped rather than raising: a stale client should degrade to
    the models that still exist, not fail the scan.

    An exact model id is also accepted, so a client that picked a single
    concrete model keeps working.
    """
    if not raw:
        return []
    known_families = {
        f"{provider.slug}:{family.id}"
        for provider in MODEL_CATALOGUE
        for family in provider.families
    }
    known_models = {
        f"{provider.slug}:{entry.id}"
        for provider in MODEL_CATALOGUE
        for entry in provider.models
    }
    chosen: list[str] = []
    for part in raw.split(","):
        candidate = part.strip()
        if candidate in known_families or candidate in known_models:
            if candidate not in chosen:
                chosen.append(candidate)
    return chosen


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
    "You are an expert geolocation analyst. Work through the photograph systematically "
    "before you commit to an answer.\n"
    "\n"
    "First, state the visual evidence you can actually see, in one or two short "
    "sentences. Be literal and specific:\n"
    "- Transcribe any readable text -- signs, shopfronts, street names, plates, posters "
    "-- character by character, and name the script or language.\n"
    "- Describe the architecture and building materials, the road surface, the markings "
    "and signs, and which side of the road traffic drives on.\n"
    "- Note the terrain, vegetation, climate, light and weather.\n"
    "- Name anything that pins the place down: a distinct tower, a specific mountain "
    "shape, a stadium, a particular bridge, a market stall.\n"
    "\n"
    "Then reason from that evidence to the most specific place you can justify: a "
    "landmark, building, street, park or neighbourhood over a city, and a city over a "
    "country. Do not guess a famous place unless the evidence supports it.\n"
    "\n"
    "Then give up to three ranked candidates, best first, in exactly this format and "
    "nothing else:\n"
    "[NAME: Most specific place name, City, Country] [LAT: decimal degrees] "
    "[LNG: decimal degrees]\n"
    "[NAME: Second choice, City, Country] [LAT: decimal degrees] [LNG: decimal degrees]\n"
    "[NAME: Third choice, City, Country] [LAT: decimal degrees] [LNG: decimal degrees]\n"
    "Give fewer lines only if you have fewer serious candidates. Never invent a place "
    "you have no evidence for: a wrong second candidate is worse than no second "
    "candidate."
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
# Local model (GeoCLIP, or CLIP zero-shot as a fallback)
# --------------------------------------------------------------------------

local_model = LocalModel()


def local_model_available() -> bool:
    """True when an offline geolocator can be used at all."""
    return local_model.available()


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


def _is_latin_token(token: str) -> bool:
    """True when a token contains at least one Latin letter."""
    for character in token:
        if not character.isalpha():
            continue
        try:
            if unicodedata.name(character).startswith("LATIN"):
                return True
        except ValueError:
            continue
    return False


def latin_lead(text: str) -> str:
    """Keep the leading Latin-script part of a place name.

    Nominatim returns the local form when a place has no registered English
    name -- "Marrakech ⵎⵕⵕⴰⴽⵯⵛ مراكش, Maroc ⵍⵎⵖⵔⵉⴱ المغرب" -- which
    reads oddly in an English console. The leading Latin run is the name most
    people recognise, so that is what is kept.
    """
    tokens = text.split()
    kept: list[str] = []
    for token in tokens:
        if _is_latin_token(token):
            kept.append(token)
        else:
            break
    return " ".join(kept) if kept else text


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

    def reverse(self, lat: float, lng: float) -> str | None:
        """Turn a coordinate into a readable place name.

        The local model answers with coordinates and no name, so a reverse
        lookup is what gives the operator something recognisable. geopy's
        ``reverse()`` returns the address as a flat string, so the raw
        Nominatim JSON is used to pick the most useful level.
        """
        self._wait_turn()
        url = (
            "https://nominatim.openstreetmap.org/reverse"
            f"?lat={lat:.6f}&lon={lng:.6f}&format=jsonv2&addressdetails=1&zoom=14&language=en"
        )
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "pinpoint-os/2.0 (+https://github.com/velo4705)"},
                timeout=10,
            )
            if response.status_code != 200:
                return None
            payload = response.json()
        except Exception:
            return None

        address = payload.get("address") or {}
        name = (
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("municipality")
            or address.get("county")
            or address.get("state")
            or payload.get("name")
        )
        country = address.get("country")
        if name and country:
            return f"{latin_lead(str(name))}, {latin_lead(str(country))}"
        if name:
            return latin_lead(str(name))
        display = payload.get("display_name")
        return latin_lead(str(display)) if display else None


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


@dataclass
class Vote:
    """One model's answer, resolved to coordinates."""

    coordinates: tuple[float, float]
    source: str
    tier: int
    #: 'name' (forward-geocoded), 'model' (coordinates the model stated) or
    #: 'both' (the two agreed).
    origin: str
    label: str
    #: How much of this model's belief this candidate carries.
    #:
    #: A model that ranks three candidates splits its single vote across
    #: them rather than casting three: rank 1 keeps the bulk, the runners-up
    #: keep a share. That way a model's total support is one, so a chatty
    #: model cannot outvote a decisive one -- but two models that both name
    #: the same runner-up can still outvote one model's first guess.
    weight: float = 1.0


#: Two answers within this distance of each other are treated as agreeing.
AGREEMENT_KM = 75.0

#: How a model's belief is split across the candidates it ranked. They sum
#: to one, so a model's total support never exceeds a single vote.
CANDIDATE_WEIGHTS = (0.55, 0.30, 0.15)

#: How many models a single scan may consult. Independent agreement is what
#: makes the result trustworthy, so this is deliberately greater than one.
DEFAULT_VERIFY_MODELS = 3

#: Ceiling on an operator-supplied model selection.
MAX_SELECTED_MODELS = 10

#: Per-tier trust, used as the confidence baseline for an unconfirmed answer.
TIER_TRUST = {
    "gemini": 0.78,
    "openai": 0.78,
    "groq": 0.45,
    "local": 0.35,
}


def parse_ranked_candidates(text: str) -> list[tuple[str, tuple[float, float] | None]]:
    """Pull the model's ranked candidates out of a reply.

    Each candidate is a ``[NAME: ...]`` tag paired with the coordinates that
    follow it. A reply that names a place without coordinates still counts;
    the coordinates are simply unknown, and the name is geocoded instead.

    Only the leading candidate's coordinates are read when a reply mixes
    formats, so a stray coordinate elsewhere in the prose cannot be attached
    to the wrong place.
    """
    if not text:
        return []
    results: list[tuple[str, tuple[float, float] | None]] = []
    pattern = re.compile(
        r"\[NAME\s*:\s*([^\]]+)\]"
        r"(?:\s*\[LAT\s*:\s*(-?\d+(?:\.\d+)?)\])?"
        r"(?:\s*\[(?:LNG|LON)\s*:\s*(-?\d+(?:\.\d+)?)\])?",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        name = _clean_place(match.group(1))
        if not name or _is_placeholder(name):
            continue
        coordinates: tuple[float, float] | None = None
        if match.group(2) and match.group(3):
            try:
                lat = float(match.group(2))
                lon = float(match.group(3))
            except ValueError:
                lat = lon = None
            if lat is not None and lon is not None and -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                coordinates = (lat, lon)
        if any(existing[0] == name for existing in results):
            continue
        results.append((name, coordinates))
    return results


def parse_model_coordinates(text: str) -> tuple[float, float] | None:
    """Pull the model's own ``[LAT: ...] [LNG: ...]`` estimate out of a reply.

    This is a second, independent signal from the same model: the place name
    goes through a geocoder, while these numbers do not.
    """
    lat_match = re.search(r"\[LAT\s*:\s*(-?\d+(?:\.\d+)?)\]", text, re.IGNORECASE)
    lng_match = re.search(r"\[(?:LNG|LON)\s*:\s*(-?\d+(?:\.\d+)?)\]", text, re.IGNORECASE)
    if not lat_match or not lng_match:
        return None
    try:
        lat = float(lat_match.group(1))
        lng = float(lng_match.group(1))
    except ValueError:
        return None
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lng <= 180.0):
        return None
    return lat, lng


def haversine_km(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Great-circle distance in kilometres."""
    radius = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return radius * 2 * math.asin(math.sqrt(a))


def group_votes(votes: Sequence[Vote]) -> list[list[Vote]]:
    """Cluster votes that agree on a location."""
    clusters: list[list[Vote]] = []
    for vote in votes:
        for cluster in clusters:
            if any(
                haversine_km(vote.coordinates[0], vote.coordinates[1], member.coordinates[0], member.coordinates[1])
                <= AGREEMENT_KM
                for member in cluster
            ):
                cluster.append(vote)
                break
        else:
            clusters.append([vote])
    return clusters


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

    def _call_gemini(
        self,
        provider: Provider,
        model: str,
        b64: str,
        prompt: str,
        key: str,
        out_of_quota: set[str] | None = None,
    ) -> str | None:
        """Ask Gemini. A 429 means the whole key is out of quota."""
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
                if response.status_code == 429 and out_of_quota is not None:
                    out_of_quota.add(provider.slug)
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
        self,
        provider: Provider,
        model: str,
        b64: str,
        prompt: str,
        key: str,
        out_of_quota: set[str] | None = None,
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
                if response.status_code == 429 and out_of_quota is not None:
                    out_of_quota.add(provider.slug)
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
        out_of_quota: set[str] | None = None,
    ) -> Prediction | None:
        provider = tier.provider
        key = keys.get(provider.slug)
        if not key:
            return None

        if provider.style == GEMINI:
            text = self._call_gemini(provider, tier.model, b64, prompt, key, out_of_quota)
        else:
            text = self._call_openai_chat(provider, tier.model, b64, prompt, key, out_of_quota)
        if not text:
            return None
        return Prediction(
            text=text,
            source=f"{provider.label}({tier.model})",
            tier=tier.index,
            confidence=0.88,
        )

    def _selection_groups(self, selection: Sequence[str]) -> list[list[Tier]]:
        """Expand an operator's selection into groups of fallback models.

        One selection entry is one voice. A family entry expands to its
        members in accuracy order, and the engine tries them in turn until
        one answers -- so "Flash" means "the Flash line, best first", not
        "every Flash revision gets a vote".
        """
        ladder = REAL_WORLD_TIERS
        by_key = {f"{tier.provider.slug}:{tier.model}": tier for tier in ladder}
        groups: list[list[Tier]] = []
        for item in selection:
            provider_slug, _, name = item.partition(":")
            provider = next((p for p in MODEL_CATALOGUE if p.slug == provider_slug), None)
            if provider is None:
                continue
            family = provider.family(name)
            if family is not None:
                members = [
                    by_key[f"{provider.slug}:{entry.id}"]
                    for entry in family.models
                    if f"{provider.slug}:{entry.id}" in by_key
                ]
                if members:
                    groups.append(members)
                continue
            tier = by_key.get(item)
            if tier is not None:
                groups.append([tier])
        return groups

    def _select_tiers(
        self, model: str, mode: str, selection: Sequence[str] | None = None
    ) -> tuple[Tier, ...]:
        """Pick the rungs to consult.

        An explicit ``selection`` of ``provider:model`` ids wins outright:
        the operator chose those models, and only those participate. The
        selection keeps the order it was given, so the first one is the
        model the engine trusts most.
        """
        ladder = GAME_TIERS if mode == "game" else REAL_WORLD_TIERS

        if selection:
            chosen: list[Tier] = []
            by_key = {
                f"{tier.provider.slug}:{tier.model}": tier
                for tier in ladder
            }
            for item in selection:
                provider_slug, _, name = item.partition(":")
                provider = next(
                    (p for p in MODEL_CATALOGUE if p.slug == provider_slug), None
                )
                if provider is None:
                    continue
                family = provider.family(name)
                if family is not None:
                    # A family is a fallback list: its members are tried in
                    # order, so an unavailable model does not fail the scan.
                    for entry in family.models:
                        tier = by_key.get(f"{provider.slug}:{entry.id}")
                        if tier is not None:
                            chosen.append(tier)
                    continue
                tier = by_key.get(item)
                if tier is not None:
                    chosen.append(tier)
            if chosen:
                return tuple(chosen)

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
        selection: Sequence[str] | None = None,
    ) -> dict:
        keys, key_errors = self._resolve_keys(byok)
        if key_errors:
            return {"error": "Invalid API key: " + "; ".join(key_errors)}

        selection = list(selection or [])
        local_pref = "auto"
        for item in selection:
            if item.startswith("local:"):
                local_pref = item.split(":", 1)[1]
        local_model.set_preference(local_pref)

        scope = key_scope(keys)
        img_hash = hashlib.md5(image_bytes).hexdigest()
        # The verify-model count changes the answer, so it belongs in the key.
        budget = int(os.getenv("PINPOINT_VERIFY_MODELS", str(DEFAULT_VERIFY_MODELS)))
        if selection:
            # An explicit selection is the operator saying which models to
            # use; honour it rather than silently consulting fewer of them.
            # One selection entry is one voice, however many models its
            # family holds -- the extra models are fallbacks, not voters.
            budget = min(len(selection), MAX_SELECTED_MODELS)
        selection_tag = "-".join(selection) if selection else "auto"
        img_cache_key = f"pinpoint:img:{img_hash}:{model}:{scope}:v{budget}:{selection_tag}"

        if self.redis:
            cached = self.redis.get(img_cache_key)
            if cached:
                print(f"[cache] image hit {img_hash[:8]} scope={scope}")
                return json.loads(cached)

        b64 = base64.b64encode(image_bytes).decode("utf-8")
        deadline = time.monotonic() + SCAN_DEADLINE_SECONDS

        # Consult several models and let agreement decide. A single confident
        # model is not enough: on the benchmark, one fast model sent Porto to
        # Buenos Aires and Marrakesh to Kabul, while a second opinion caught
        # both.
        votes: list[Vote] = []
        consulted: list[str] = []
        providers_used: set[str] = set()
        # Providers whose key reported a rate limit during this scan. When a
        # provider is out of quota every one of its models is, so the cascade
        # stops trying that provider instead of burning a call per sibling.
        out_of_quota: set[str] = set()

        # 'local-only' means exactly that: consult the offline model and
        # nothing else.
        cloud_only = model != "local-only"

        if cloud_only:
            if selection:
                groups = self._selection_groups(selection)
            else:
                # The auto ladder descends rung by rung, one model per rung.
                groups = [[tier] for tier in self._select_tiers(model, "real-world")]

            for group in groups:
                if len(votes) >= budget:
                    break
                if time.monotonic() > deadline:
                    print("[scan] deadline reached -- stopping cascade")
                    break
                answered = False
                for tier in group:
                    if len(votes) >= budget:
                        break
                    if time.monotonic() > deadline:
                        print("[scan] deadline reached -- stopping cascade")
                        break
                    if tier.provider.slug in out_of_quota:
                        # The key is out of quota, so every sibling model in
                        # this group is too. Trying them all would just burn
                        # time and rate limit further.
                        print(f"[{tier.provider.label}] out of quota -- skipping the rest")
                        break
                    attempt = self._call_tier(
                        tier, image_bytes, b64, REAL_WORLD_PROMPT, keys, out_of_quota
                    )
                    if not attempt:
                        # The model failed -- quota, overload, a dead id.
                        # The next member of the family gets a turn.
                        continue
                    attempt_candidates = extract_location_candidates(attempt.text)
                    if not attempt_candidates:
                        # The model answered, but not with a place ("[NAME:
                        # Unknown, Unknown]"). A non-answer is a failed rung,
                        # so keep descending the ladder rather than pinning a
                        # guess.
                        print(f"[{tier.provider.label}/{tier.model}] no usable place name -- next rung")
                        continue

                    providers_used.add(tier.provider.slug)
                    consulted.append(attempt.source)
                    new_votes = self._votes_for(tier, attempt, attempt_candidates)
                    if not new_votes:
                        print(f"[{tier.provider.label}/{tier.model}] no usable coordinates -- next rung")
                        continue
                    votes.extend(new_votes)
                    answered = True
                    break
                if not answered and group:
                    tier = group[0]
                    print(f"[{tier.provider.label}] no model in this group answered")

        # The local model is free and offline, so it is consulted in every
        # scan as an *independent* cross-check. It is deliberately not a
        # voter: GeoCLIP is right about 20% of the time on its own, so
        # letting it corroborate would dress a wrong answer up as
        # confirmed. When no cloud model can be reached it is the answer.
        local_vote: Vote | None = None
        if local_model_available() and time.monotonic() <= deadline:
            local_vote = self._local_vote(image_bytes)

        if not votes:
            if local_vote is None:
                return {"error": self._no_tier_message(model, keys)}
            votes = [local_vote]
            consulted = [local_vote.source]
        elif local_vote is not None:
            consulted.append(local_vote.source)

        best, support, confidence, dissent = self._consensus(votes)
        location = best.label
        coords = best.coordinates

        insights = [f"Source: {best.source}", f"Tier: {best.tier}"]
        if support > 1:
            insights.append(f"Corroborated by {support} models")
        if dissent:
            insights.append(f"{dissent} model(s) disagreed")
        if local_vote is not None:
            gap = haversine_km(
                local_vote.coordinates[0],
                local_vote.coordinates[1],
                coords[0],
                coords[1],
            )
            if gap <= AGREEMENT_KM:
                insights.append(f"Local {local_vote.source.split(' ')[-1]} agrees")
            else:
                insights.append(f"Local model differs by {gap:,.0f} km")

        result = {
            "location": location,
            "coordinates": {"lat": coords[0], "lng": coords[1]},
            "confidence": confidence,
            "source": best.source,
            "tier": best.tier,
            "support": support,
            "consulted": consulted,
            "mode": "real-world",
            "insights": insights,
        }
        self._store_caches(img_cache_key, location, coords, result)
        return result

    def _votes_for(
        self, tier: Tier, prediction: Prediction, candidates: list[str]
    ) -> list[Vote]:
        """Turn one model's reply into votes.

        A reply carries two readings of the same opinion for its first
        candidate: the place name (which goes through the geocoder) and the
        coordinates the model stated outright. They are *not* independent,
        so they must never be counted as two votes -- otherwise one model
        could outvote another.

        When they agree, the model's own coordinates win, because they are
        the more precise of the two. When they disagree, the geocoded name
        wins, because a name that resolves to a real place is more
        trustworthy than coordinates the model asserted.

        A model that ranked several candidates has its one vote *split*
        across them, most to the first. The runners-up are taken from the
        model's own coordinates -- they are not geocoded, because that would
        mean several lookups against a service that asks for one request a
        second, and the model has already said where they are.
        """
        ranked = parse_ranked_candidates(prediction.text)
        if not ranked:
            # A model that ignored the tag format still gets its chance:
            # fall back to the plain candidate names.
            ranked = [(name, None) for name in candidates[: len(CANDIDATE_WEIGHTS)]]
        if not ranked:
            return []

        votes: list[Vote] = []
        for index, (name, coordinates) in enumerate(ranked[: len(CANDIDATE_WEIGHTS)]):
            weight = CANDIDATE_WEIGHTS[index]
            if index == 0:
                vote = self._first_candidate_vote(tier, prediction, name, coordinates, candidates)
                if vote is None:
                    continue
                votes.append(vote)
                continue
            if coordinates is None:
                continue
            votes.append(
                Vote(
                    coordinates=coordinates,
                    source=prediction.source,
                    tier=tier.index,
                    origin="model",
                    label=name,
                    weight=weight,
                )
            )
        return votes

    def _first_candidate_vote(
        self,
        tier: Tier,
        prediction: Prediction,
        name: str,
        coordinates: tuple[float, float] | None,
        candidates: list[str],
    ) -> Vote | None:
        """Resolve the leading candidate, preferring a corroborated reading."""
        geocoded_name, geocoded_coords, _attempts = self._map_lock(candidates or [name])

        if geocoded_coords:
            if coordinates:
                distance = haversine_km(
                    coordinates[0], coordinates[1], geocoded_coords[0], geocoded_coords[1]
                )
                if distance <= AGREEMENT_KM:
                    return Vote(
                        coordinates=coordinates,
                        source=prediction.source,
                        tier=tier.index,
                        origin="both",
                        label=geocoded_name or name,
                    )
            return Vote(
                coordinates=geocoded_coords,
                source=prediction.source,
                tier=tier.index,
                origin="name",
                label=geocoded_name or name,
            )

        if coordinates:
            return Vote(
                coordinates=coordinates,
                source=prediction.source,
                tier=tier.index,
                origin="model",
                label=name,
            )
        return None

    def _local_vote(self, image_bytes: bytes) -> Vote | None:
        """The offline model's opinion, as a vote.

        GeoCLIP returns coordinates outright, so this vote needs no geocoder.
        The label is reverse-geocoded when possible, because a bare
        coordinate is not something an operator can read.
        """
        label, coordinates, _score, engine = local_model.predict(image_bytes)
        if coordinates is None:
            if not label:
                return None
            geocoded_name, geocoded_coords, _attempts = self._map_lock([label])
            if not geocoded_coords:
                return None
            coordinates = geocoded_coords
            label = geocoded_name or label
        else:
            reverse = self.geocoder.reverse(coordinates[0], coordinates[1])
            if reverse:
                label = reverse
        return Vote(
            coordinates=coordinates,
            source=f"Local {engine}",
            tier=14,
            origin="model",
            label=label,
        )

    @staticmethod
    def _consensus(votes: Sequence[Vote]) -> tuple[Vote, int, float, int]:
        """Pick the best-supported answer and score it honestly.

        Support is counted in *distinct models*, not raw votes: one model's
        name and its own coordinates are two readings of the same opinion, so
        they must not be able to outvote a second model.

        Returns ``(winner, support_models, confidence, dissent_models)``.
        """
        clusters = group_votes(votes)

        def cluster_key(cluster: list[Vote]):
            models = {vote.source for vote in cluster}
            agreeing = any(vote.origin == "both" for vote in cluster)
            best_tier = min(vote.tier for vote in cluster)
            # Most belief first. A model's belief is split across the
            # candidates it ranked, so this compares *support*, not the
            # number of raw votes. Then most independent models, then a
            # model whose own signals agreed, then the strongest tier.
            support = sum(vote.weight for vote in cluster)
            return (-round(support, 6), -len(models), -int(agreeing), best_tier)

        clusters.sort(key=cluster_key)
        winner_cluster = clusters[0]

        # Prefer a vote whose own name and coordinates agreed, then the
        # strongest tier, then the heaviest weight.
        winner = min(
            winner_cluster,
            key=lambda vote: (vote.origin != "both", vote.tier, -vote.weight),
        )

        cluster_models = {vote.source for vote in winner_cluster}
        total_models = {vote.source for vote in votes}
        support = len(cluster_models)
        dissent = len(total_models - cluster_models)

        trust = TIER_TRUST.get(winner.source.split("(")[0].lower(), 0.5)
        if winner.origin == "both":
            trust = min(0.95, trust + 0.08)

        if support > 1:
            confidence = min(0.96, trust + 0.05 * (support - 1))
        elif dissent > 0:
            # It is the only answer, but other models disagreed with it.
            confidence = trust * 0.7
        else:
            confidence = trust

        return winner, support, round(confidence, 3), dissent

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
    """Load the local model in the background so the first scan is not slow.

    The first load pulls roughly 1.7 GB of GeoCLIP weights and encodes a
    100,000-point gallery; doing that on a background thread at startup means
    the model is warm by the time an operator needs it, instead of stalling
    their first request for minutes.
    """
    if not local_model_available():
        print("[local] extras not installed -- the offline bunker stays disabled")
        return

    def _warm() -> None:
        started = time.monotonic()
        engine = local_model.warm()
        if engine == "none":
            print("[local] warm-up failed")
            return
        print(f"[local] {engine} warm in {time.monotonic() - started:.1f}s")

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
