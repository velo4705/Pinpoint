# 📍 Pinpoint OS

**Pinpoint OS** is an open-source, AI-powered reverse image search and geolocation engine. Designed for investigators, gamers, and explorers, it identifies locations from photos using state-of-the-art neural networks.

![Pinpoint UI Placeholder](https://via.placeholder.com/800x450/0a0a0c/3b82f6?text=PINPOINT+OS+INTERFACE)

## 🌟 Key Features

- **🌍 Real-World Geolocation**: Identify cities, landmarks, and landscapes using AI (CLIP-based vision models).
- **🎮 Gaming Universe Integration**: Specialized mode to find coordinates in open-world games like GTA V, Elden Ring, and Genshin Impact.
- **🗺️ Interactive Map**: Built on MapLibre GL JS with OpenStreetMap for a completely free, privacy-focused experience.
- **🛡️ Privacy First**: Local-first processing architecture. No data collection, no tracking.
- **✨ Premium UI**: Modern "Neural OS" interface with glassmorphism and real-time scanning animations.

## 🚀 Getting Started

### Prerequisites
- Python 3.9+
- Node.js 18+

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/your-username/pinpoint.git
   cd pinpoint
   ```

2. **Setup Backend**
   ```bash
   cd backend
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   python main.py
   ```

3. **Setup Frontend**
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

## 🧠 How it Works

Pinpoint uses a dual-brain architecture:
1. **The Vision Brain**: Powered by OpenAI's CLIP, it understands the "visual context" of an image (e.g., "The architecture looks Parisian").
2. **The Vector Brain**: For games, Pinpoint uses vector similarity search to compare your screenshot against a database of map tiles, finding the exact pixel-perfect match.

## 🤝 Contributing

We welcome contributions! Whether it's adding new game map databases or improving the AI models, please feel free to open a Pull Request.

## 📜 License

Distributed under the MIT License. See `LICENSE` for more information.

## 🗺️ Roadmap

Check out our [ROADMAP.md](ROADMAP.md) for future plans and milestones.

---
*Built with ❤️ for the open-source community.*
