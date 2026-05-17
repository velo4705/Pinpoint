# Project Context: Pinpoint OS

## Purpose
Pinpoint is a privacy-first, zero-budget, open-source tool for image geolocation. It bridges the gap between real-world investigative OSINT tools and gaming community tools (like Minecraft world "Seed Crackers").

## Technical Architecture
- **Frontend**: Next.js (App Router), TypeScript, Tailwind CSS, MapLibre GL JS, Framer Motion.
- **Backend**: FastAPI (Python), Uvicorn.
- **AI Core**: 14-Tier Federated Model Alliance (Automatic cascading, Gemini 1.5 Flash-Lite, Groq Llama, GitHub Models, and local Hugging Face CLIP fallback).
- **Data Store & Caching**:
  - Real-world: Nominatim Reverse-Geocoding + pre-defined landmarks coordinate mapping + AI Inference.
  - Gaming: Vector Embeddings (ChromaDB) for visual similarity matching + procedural Minecraft Seed-DNA Triangulation.
  - State Caching: Upstash Serverless Redis.

## Key Constraints & Rationale
1. **Zero Budget**: We avoid paid APIs (Google Maps, paid OpenAI keys). We use open-source equivalents (MapLibre, open AI APIs, and Hugging Face models).
2. **Privacy-Focused**: User images are parsed in-memory and are never stored permanently. Local storage is strictly client-side for scan history recall.
3. **Gaming & OSINT Focus**: The dual-mode architecture (Real World vs. Gaming Mode) serves both geopolitical analysts and gamers. 

## Development Status
- **Current**: **v1.0.0 Release**. Fully active, high-fidelity command console with left-sidebar menus, glowing neon progress indicators, operator history recall, visual output thumbnails, and Minecraft seed-triangulation.
- **Immediate Goal (v2.0)**: Complete integration of ChromaDB vector databases for open-world games (starting with GTA V / Red Dead Redemption 2 presets) and an automated EXIF metadata scrubber.

## File Structure
- `/frontend`: Next.js web application.
- `/backend`: FastAPI neural engine.
- `/backend/vector_db`: Storage for game map embeddings.
- `/backend/models`: Local AI model cache.
- `ROADMAP.md`: Dynamic release milestone tracking.
- `CONTEXT.md`: High-level system architecture context.
