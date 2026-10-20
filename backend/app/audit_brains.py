"""
Live tier audit
===============

Probes every rung of the fallback ladder against its provider and reports
which rungs are reachable. Run it after changing the tier plan, after
rotating a key, or before a release.

    python -m app.audit_brains                 # uses .env keys
    python -m app.audit_brains --image x.jpg   # use a specific image
    python -m app.audit_brains --key groq=gsk_...  # override one key
"""

from __future__ import annotations

import argparse
import base64
import io
import os
import sys
import time
from typing import Sequence

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
if SCRIPT_DIR not in sys.path:
    sys.path.append(SCRIPT_DIR)

from PIL import Image  # noqa: E402

from ai_engine import (  # noqa: E402
    GAME_TIERS,
    LOCAL_LABELS,
    REAL_WORLD_TIERS,
    AIEngine,
    call_local_engine,
    extract_location_candidates,
    local_model_available,
)


def _synthetic_image() -> bytes:
    """A small, valid JPEG so the audit does not need a photo on disk."""
    image = Image.new("RGB", (224, 224), (96, 132, 186))
    for x in range(224):
        for y in range(0, 224, 4):
            image.putpixel((x, y), (40, 90, 150))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=85)
    return buffer.getvalue()


def _parse_overrides(pairs: Sequence[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"bad --key value {pair!r}, expected provider=KEY")
        slug, value = pair.split("=", 1)
        overrides[slug.strip()] = value.strip()
    return overrides


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit the Pinpoint tier ladder.")
    parser.add_argument("--image", help="path to an image; a synthetic one is used when omitted")
    parser.add_argument("--key", action="append", default=[], help="provider=KEY override")
    parser.add_argument("--mode", choices=("real-world", "game"), default="real-world")
    args = parser.parse_args()

    if args.image:
        with open(args.image, "rb") as handle:
            image_bytes = handle.read()
    else:
        image_bytes = _synthetic_image()

    overrides = _parse_overrides(args.key)
    engine = AIEngine()
    keys, errors = AIEngine._resolve_keys(overrides)
    if errors:
        print("KEY ERRORS:")
        for error in errors:
            print(f"  ! {error}")

    print()
    print("PINPOINT TIER AUDIT")
    print("=" * 78)
    print(f"mode={args.mode}  keys={', '.join(sorted(keys)) or 'none'}  local_extras={local_model_available()}")
    print("-" * 78)

    b64 = base64.b64encode(image_bytes).decode("utf-8")
    prompt = (
        "Identify the location in this image. You MUST respond with ONLY the location "
        "name in this exact format: [NAME: City, Country]."
    )
    ladder = GAME_TIERS if args.mode == "game" else REAL_WORLD_TIERS

    reachable = 0
    for tier in ladder:
        started = time.monotonic()
        label = f"T{tier.index:02d} {tier.provider.label}/{tier.model}"
        if tier.provider.env_key is None:
            prediction = call_local_engine(image_bytes)
            if prediction and prediction[0]:
                reachable += 1
                print(f"  [ OK ] {label:<48} {time.monotonic() - started:5.1f}s  {prediction[0]}")
            else:
                print(f"  [FAIL] {label:<48} {time.monotonic() - started:5.1f}s  bunker unavailable")
            continue

        key = keys.get(tier.provider.slug)
        if not key:
            print(f"  [SKIP] {label:<48}        no key")
            continue

        if tier.provider.style == "gemini":
            text = engine._call_gemini(tier.provider, tier.model, b64, prompt, key)
        else:
            text = engine._call_openai_chat(tier.provider, tier.model, b64, prompt, key)
        elapsed = time.monotonic() - started
        if text:
            reachable += 1
            candidates = extract_location_candidates(text)
            print(f"  [ OK ] {label:<48} {elapsed:5.1f}s  {candidates[:1] or text[:40]!r}")
        else:
            print(f"  [FAIL] {label:<48} {elapsed:5.1f}s  no response")

    print("-" * 78)
    print(f"reachable rungs: {reachable}/{len(ladder)}")
    print(f"local label pool: {len(LOCAL_LABELS)} places")
    return 0 if reachable else 1


if __name__ == "__main__":
    raise SystemExit(main())
