import React, { useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

interface MapProps {
  center?: [number, number];
  zoom?: number;
  marker?: { lat: number; lng: number };
  mode?: 'real-world' | 'game';
  game?: string;
  gameCoords?: { x: number; z: number };
  seed?: string; // The Minecraft seed to generate the map from
  mapStyle?: 'dark' | 'light' | 'satellite';
}

const MapComponent: React.FC<MapProps> = ({ center = [0, 20], zoom = 2, marker, mode = 'real-world', game, gameCoords, seed, mapStyle = 'dark' }) => {
  const mapContainer = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  
  const isMinecraft = mode === 'game' && game === 'Minecraft';

  // Get Style Object/URL for MapLibre
  const getStyleSource = (style: 'dark' | 'light' | 'satellite') => {
    if (style === 'satellite') {
      return {
        version: 8 as const,
        sources: {
          'satellite': {
            type: 'raster' as const,
            tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
            tileSize: 256,
            attribution: 'Tiles &copy; Esri'
          }
        },
        layers: [{
          id: 'satellite',
          type: 'raster' as const,
          source: 'satellite'
        }]
      };
    }
    return {
      light: 'https://tiles.basemaps.cartocdn.com/gl/positron-gl-style/style.json',
      dark: 'https://tiles.basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
    }[style];
  };

  // --- SEEDED NOISE GENERATOR (For Minecraft Procedural Map) ---
  // ... (Procedural generation) ...
  useEffect(() => {
    if (!isMinecraft || !seed || !canvasRef.current) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const width = 1000;
    const height = 1000;
    canvas.width = width;
    canvas.height = height;

    // Simple seeded random for biome noise
    const seedNum = parseInt(seed) || 0;
    const random = (s: number) => {
        const x = Math.sin(s) * 10000;
        return x - Math.floor(x);
    };

    const imageData = ctx.createImageData(width, height);
    for (let x = 0; x < width; x++) {
      for (let y = 0; y < height; y++) {
        const i = (x + y * width) * 4;
        
        // Generate procedural noise based on seed
        const val = (
            random(seedNum + x * 0.01) + 
            random(seedNum + y * 0.01) + 
            random(seedNum + (x + y) * 0.005)
        ) / 3;

        let r, g, b;
        if (val < 0.45) { // Water/Oceans
            r = 30; g = 60; b = 180;
        } else if (val < 0.55) { // Plains/Beach
            r = 140; g = 180; b = 80;
        } else if (val < 0.75) { // Forest/Lush
            r = 40; g = 120; b = 30;
        } else { // Mountains/Stone
            r = 100; g = 100; b = 100;
        }

        imageData.data[i] = r;
        imageData.data[i + 1] = g;
        imageData.data[i + 2] = b;
        imageData.data[i + 3] = 255;
      }
    }
    ctx.putImageData(imageData, 0, 0);
  }, [seed, isMinecraft]);

  const markerRef = useRef<maplibregl.Marker | null>(null);

  // Initialize Map
  useEffect(() => {
    if (map.current) return;
    map.current = new maplibregl.Map({
      container: mapContainer.current!,
      style: getStyleSource(mapStyle),
      center: center,
      zoom: zoom,
    });
  }, []);

  // Handle Dynamic Map Style Switching
  useEffect(() => {
    if (!map.current) return;
    map.current.setStyle(getStyleSource(mapStyle));
  }, [mapStyle]);

  // Update real-world map when marker changes
  useEffect(() => {
    if (!map.current || !marker || isMinecraft) return;

    // Smoothly fly to the new coordinates
    map.current.flyTo({ 
      center: [marker.lng, marker.lat], 
      zoom: 14,
      essential: true 
    });

    // Create or update the map marker
    if (markerRef.current) {
      markerRef.current.setLngLat([marker.lng, marker.lat]);
    } else {
      markerRef.current = new maplibregl.Marker({ color: '#ef4444' })
        .setLngLat([marker.lng, marker.lat])
        .addTo(map.current);
    }
  }, [marker, isMinecraft]);

  // Update Game Marker (X, Z)
  return (
    <div className="relative w-full h-full">
      {/* Procedural Minecraft Layer */}
      {isMinecraft && (
        <div className="absolute inset-0 z-10 bg-[#1a1a1a] flex items-center justify-center overflow-hidden">
          <canvas 
            ref={canvasRef} 
            className="w-full h-full object-cover opacity-80"
            style={{ imageRendering: 'pixelated' }}
          />
          {/* Procedural Marker */}
          {gameCoords && (
            <div 
              className="absolute w-4 h-4 bg-red-500 border-2 border-white rounded-full shadow-[0_0_20px_rgba(239,68,68,0.8)] z-20 animate-pulse"
              style={{
                left: `${50 + (gameCoords.x / 20)}%`,
                top: `${50 + (gameCoords.z / 20)}%`
              }}
            />
          )}
          <div className="absolute top-4 left-4 z-30 px-3 py-1 bg-black/50 border border-white/10 rounded-md text-[10px] font-mono uppercase tracking-widest text-red-400">
            Procedural Seed Engine: {seed}
          </div>
        </div>
      )}

      {/* Real-World Map Layer */}
      <div ref={mapContainer} className={`w-full h-full ${isMinecraft ? 'opacity-0 pointer-events-none' : 'opacity-100'}`} />
    </div>
  );
};

export default MapComponent;
