# Project Context: Pinpoint OS

## Purpose
Pinpoint is a privacy-first, zero-budget, open-source tool for image geolocation. It bridges the gap between real-world investigative OSINT tools and gaming community tools (like Minecraft world "Seed Crackers").

## Technical Architecture
- **Frontend**: Next.js 16 (App Router), TypeScript, Tailwind CSS 4, MapLibre GL JS, Framer Motion.
- **Backend**: FastAPI (Python), Uvicorn.
- **AI Core**: 14-Tier Federated Model Alliance (Automatic cascading across Gemini, Groq, OpenAI, and a local Hugging Face CLIP fallback).
- **Data Store & Caching**:
  - Real-world: Nominatim Reverse-Geocoding + pre-defined landmarks coordinate mapping + AI Inference.
  - Gaming: procedural Minecraft Seed-DNA triangulation. (ChromaDB vector matching is still an open roadmap item — see `ROADMAP.md`.)
  - State Caching: Upstash Serverless Redis (two layers: image-hash and geocode).

## Key Constraints & Rationale
1. **Zero Budget**: We avoid paid APIs (Google Maps, paid OpenAI keys). We use open-source equivalents (MapLibre, open AI APIs, and Hugging Face models).
2. **Privacy-Focused**: User images are parsed in-memory and are never stored permanently.
3. **BYOK Is First-Class**: Operators may supply their own Groq / Gemini / OpenAI key per request. Those keys are never persisted by the server, and results produced with them are cached in a separate namespace.
4. **No Service Lock-In**: The former GitHub Models tier was removed after GitHub retired the whole service on 2026-07-30. Every provider is swappable.
5. **Honest Confidence**: The reported confidence reflects how specific the answer actually was, not a flat constant. The local CLIP bunker reports its own (typically low) score.

## Development Status
- **Current**: **v2.0**. 14-tier federated AI engine with BYOK, Redis dual-layer caching, an offline CLIP bunker, a ranked-candidate geolocation parser, and a refreshed UI.
- **Immediate Goal (v2.x)**: ChromaDB vector matching for open-world game maps, and an automated EXIF metadata scrubber.

## File Structure
- `/frontend`: Next.js web application.
  - `/frontend/src/lib`: typed API client, BYOK store, imagery-depth probe, shared types.
- `/backend`: FastAPI neural engine.
  - `/backend/app/ai_engine.py`: provider registry, tier ladder, consensus voting, parsers.
  - `/backend/app/local_model.py`: the offline geolocator (GeoCLIP, with a CLIP zero-shot fallback).
  - `/backend/app/audit_brains.py`: live tier-ladder audit tool.
  - `/backend/vector_db`: Storage for game map embeddings (not yet wired up).
  - `/backend/models`: Local AI model cache (CLIP weights, GeoCLIP gallery embeddings).
- `ROADMAP.md`: Dynamic release milestone tracking.
- `CONTEXT.md`: High-level system architecture context.
