# Project Context: Pinpoint OS

## Purpose
Pinpoint is a privacy-first, zero-budget, open-source tool for image geolocation. It bridges the gap between real-world investigative tools and gaming community tools (like "Seed Crackers").

## Technical Architecture
- **Frontend**: Next.js (App Router), TypeScript, Tailwind CSS, MapLibre GL JS.
- **Backend**: FastAPI (Python), Uvicorn.
- **AI Core**: Hugging Face Transformers (CLIP model).
- **Data Store**: 
  - Real-world: Pre-defined landmark coordinate mapping + AI Inference.
  - Gaming: Vector Embeddings (ChromaDB) for visual similarity matching.

## Key Constraints & Rationale
1. **Zero Budget**: We avoid paid APIs (Google Maps, OpenAI API). We use open-source equivalents (MapLibre, Hugging Face models).
2. **Privacy**: User images should not be stored permanently. Scanning should happen as close to the user as possible (Local Inference goal).
3. **Gaming Focus**: The "Game Mode" is a unique differentiator. It requires a library of game map screenshots converted into vector embeddings.

## Development Status
- **Current**: MVP with real-world landmark identification and a mock gaming mode.
- **Immediate Goal**: Full integration of ChromaDB for at least one game (e.g., GTA V).

## File Structure
- `/frontend`: Next.js web application.
- `/backend`: FastAPI neural engine.
- `/backend/vector_db`: Storage for game map embeddings.
- `/backend/models`: Local AI model cache.
