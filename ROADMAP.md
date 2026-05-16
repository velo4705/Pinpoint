# Pinpoint Milestone Roadmap

This roadmap outlines the journey from a prototype to a "perfect" production-ready AI geolocation engine.

## Phase 1: Foundation (Current)
- [x] Initial Project Structure (Frontend/Backend)
- [x] Basic UI with MapLibre integration
- [x] Neural Engine foundation (CLIP Model)
- [x] Core "Scan" API
- [x] Real-world vs. Gaming mode architecture

## Phase 2: Neural Refinement (Short Term)
- [ ] **Advanced Geolocation**: Move beyond landmarks to "GeoGuessr" style environmental detection (flora, weather, soil).
- [ ] **EXIF Data Scrubber**: Automatically strip privacy-invasive metadata before processing.
- [ ] **Local Storage History**: Store scan results in the user's browser for quick recall.
- [ ] **Multi-Model Support**: Allow switching between lightweight (fast) and heavy (accurate) AI models.

## Phase 3: Gaming & Open World (Mid Term)
- [ ] **Vector Database Integration**: Fully implement ChromaDB for game map matching.
- [ ] **Map Tiler**: A tool to convert high-res game map images into interactive map tiles.
- [ ] **Seed Cracker Integration**: API hooks for Minecraft/No Man's Sky seed calculation.
- [ ] **Game Preset Library**: Built-in support for GTA V, RDR2, Genshin Impact, and Elden Ring.

## Phase 4: Intelligence & Community (Long Term)
- [ ] **Crowdsourced Intelligence**: Allow users to contribute "Landmark" data to the open-source database.
- [ ] **Privacy Vault**: Optional end-to-end encryption for history.
- [ ] **Mobile App (PWA)**: Optimized "Scan-on-the-go" interface.
- [ ] **Game API Integrations**: Directly fetch player coordinates (where permitted) for validation.

## Phase 5: The "Perfect Product" (Polishing)
- [ ] **Real-time Scan**: "Live" camera feed geolocation.
- [ ] **Offline Mode**: Downloadable local models for disconnected usage.
- [ ] **Developer API**: Allow other games/apps to use Pinpoint's geolocation engine.
- [ ] **Interactive 3D Views**: 3D building/terrain overlays for identified locations.
