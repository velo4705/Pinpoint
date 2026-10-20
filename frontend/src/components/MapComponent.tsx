'use client';

import React, { useEffect, useRef } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

interface MapProps {
  center?: [number, number];
  zoom?: number;
  marker?: { lat: number; lng: number };
  mode?: 'real-world' | 'game';
  game?: string;
  gameCoords?: { x: number; y: number; z: number };
  seed?: string;
  mapStyle?: 'dark' | 'light' | 'satellite';
}

/** Side of the schematic window, in Minecraft blocks. */
const VIEW_BLOCKS = 512;
/** Resolution of the schematic canvas, in pixels. */
const CANVAS_SIZE = 512;

const getStyleSource = (style: 'dark' | 'light' | 'satellite') => {
  if (style === 'satellite') {
    return {
      version: 8 as const,
      sources: {
        satellite: {
          type: 'raster' as const,
          tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
          tileSize: 256,
          attribution: 'Tiles &copy; Esri',
        },
      },
      layers: [
        {
          id: 'satellite',
          type: 'raster' as const,
          source: 'satellite',
        },
      ],
    };
  }
  return {
    light: 'https://tiles.basemaps.cartocdn.com/gl/positron-gl-style/style.json',
    dark: 'https://tiles.basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
  }[style];
};

const MapComponent: React.FC<MapProps> = ({
  center = [0, 20],
  zoom = 2,
  marker,
  mode = 'real-world',
  game,
  gameCoords,
  seed,
  mapStyle = 'dark',
}) => {
  const mapContainer = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const markerRef = useRef<maplibregl.Marker | null>(null);

  // The map is created once; later view changes are applied through
  // flyTo and setStyle rather than by recreating it.
  const initialView = useRef({ center, zoom, style: mapStyle });
  const appliedStyle = useRef<string | null>(null);

  const isMinecraft = mode === 'game' && game === 'Minecraft';
  const originX = gameCoords?.x;
  const originZ = gameCoords?.z;

  /* ---------------------------------------------------------------- */
  /* Schematic Minecraft view                                          */
  /* ---------------------------------------------------------------- */

  useEffect(() => {
    if (!isMinecraft || !seed || !canvasRef.current || originX === undefined || originZ === undefined) {
      return;
    }

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    canvas.width = CANVAS_SIZE;
    canvas.height = CANVAS_SIZE;

    const seedNum = Number.parseInt(seed, 10) || 0;
    // The window is centred on the player, and the noise is sampled at
    // *absolute* world coordinates, so the same seed renders the same
    // terrain in the same place.
    const half = VIEW_BLOCKS / 2;

    const hash = (wx: number, wz: number, salt: number) => {
      const value = Math.sin(wx * 12.9898 + wz * 78.233 + salt) * 43758.5453;
      return value - Math.floor(value);
    };

    const imageData = ctx.createImageData(CANVAS_SIZE, CANVAS_SIZE);
    for (let px = 0; px < CANVAS_SIZE; px += 1) {
      for (let py = 0; py < CANVAS_SIZE; py += 1) {
        const index = (px + py * CANVAS_SIZE) * 4;
        const wx = originX - half + px;
        const wz = originZ - half + py;

        // Two octaves: a broad continental shape plus a finer detail pass.
        const broad = hash(Math.floor(wx / 16), Math.floor(wz / 16), seedNum * 0.0001);
        const detail = hash(wx, wz, seedNum * 0.0007);
        const value = broad * 0.65 + detail * 0.35;

        let r: number;
        let g: number;
        let b: number;
        if (value < 0.42) {
          r = 30;
          g = 60;
          b = 180;
        } else if (value < 0.55) {
          r = 140;
          g = 180;
          b = 80;
        } else if (value < 0.78) {
          r = 40;
          g = 120;
          b = 30;
        } else {
          r = 100;
          g = 100;
          b = 100;
        }

        imageData.data[index] = r;
        imageData.data[index + 1] = g;
        imageData.data[index + 2] = b;
        imageData.data[index + 3] = 255;
      }
    }
    ctx.putImageData(imageData, 0, 0);
  }, [seed, isMinecraft, originX, originZ]);

  /* ---------------------------------------------------------------- */
  /* Map lifecycle                                                     */
  /* ---------------------------------------------------------------- */

  useEffect(() => {
    if (map.current || !mapContainer.current) return;

    map.current = new maplibregl.Map({
      container: mapContainer.current,
      style: getStyleSource(initialView.current.style),
      center: initialView.current.center,
      zoom: initialView.current.zoom,
    });
    appliedStyle.current = initialView.current.style;

    return () => {
      markerRef.current = null;
      map.current?.remove();
      map.current = null;
    };
  }, []);

  // Apply style changes. The first render already set the style during
  // construction, so guard against fetching it twice.
  useEffect(() => {
    if (!map.current) return;
    if (appliedStyle.current === mapStyle) return;
    appliedStyle.current = mapStyle;
    map.current.setStyle(getStyleSource(mapStyle));
  }, [mapStyle]);

  // Move the real-world marker to the locked coordinates.
  useEffect(() => {
    if (!map.current) return;

    if (!marker || isMinecraft) {
      markerRef.current?.remove();
      markerRef.current = null;
      return;
    }

    map.current.flyTo({
      center: [marker.lng, marker.lat],
      zoom: 14,
      essential: true,
    });

    if (markerRef.current) {
      markerRef.current.setLngLat([marker.lng, marker.lat]);
    } else {
      markerRef.current = new maplibregl.Marker({ color: '#ef4444' })
        .setLngLat([marker.lng, marker.lat])
        .addTo(map.current);
    }
  }, [marker, isMinecraft]);

  return (
    <div className="relative w-full h-full">
      {/* Schematic Minecraft view, centred on the player */}
      {isMinecraft && (
        <div className="absolute inset-0 z-10 bg-[#1a1a1a] flex items-center justify-center overflow-hidden">
          <canvas
            ref={canvasRef}
            className="w-full h-full object-cover opacity-80"
            style={{ imageRendering: 'pixelated' }}
          />

          {gameCoords && (
            <div
              className="absolute w-4 h-4 bg-red-500 border-2 border-white rounded-full shadow-[0_0_20px_rgba(239,68,68,0.8)] z-20 animate-pulse"
              style={{ left: '50%', top: '50%', transform: 'translate(-50%, -50%)' }}
              title={`X ${gameCoords.x} / Z ${gameCoords.z}`}
            />
          )}

          <div className="absolute top-4 left-4 z-30 px-3 py-1 bg-black/50 border border-white/10 rounded-md text-[10px] font-mono uppercase tracking-widest text-red-400">
            Seed {seed}
            {gameCoords ? ` · X ${gameCoords.x} Z ${gameCoords.z}` : ''}
          </div>
          <div className="absolute bottom-4 left-4 z-30 px-3 py-1 bg-black/50 border border-white/10 rounded-md text-[9px] font-mono uppercase tracking-widest text-white/50">
            Schematic preview · {VIEW_BLOCKS}x{VIEW_BLOCKS} block window
          </div>
        </div>
      )}

      {/* Real-world map */}
      <div
        ref={mapContainer}
        className={`w-full h-full ${isMinecraft ? 'opacity-0 pointer-events-none' : 'opacity-100'}`}
      />
    </div>
  );
};

export default MapComponent;
