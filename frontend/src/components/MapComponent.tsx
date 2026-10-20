'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { IMAGERY_MAX_ZOOM_CITY, IMAGERY_MAX_ZOOM_GLOBAL, probeImageryDepth } from '@/lib/imagery';

interface MapProps {
  center?: [number, number];
  zoom?: number;
  marker?: { lat: number; lng: number };
  mode?: 'real-world' | 'game';
  game?: string;
  gameCoords?: { x: number; y: number; z: number };
  seed?: string;
  mapStyle?: 'dark' | 'light' | 'satellite';
  /** 'auto' picks the imagery depth that actually exists at `focus`. */
  imageryDetail?: 'auto' | 'balanced' | 'sharp';
  /** The coordinate the view is locked to, used to probe imagery depth. */
  focus?: { lat: number; lng: number };
}

/** Side of the schematic window, in Minecraft blocks. */
const VIEW_BLOCKS = 512;
/** Resolution of the schematic canvas, in pixels. */
const CANVAS_SIZE = 512;

/**
 * Vector basemap styles.
 *
 * Both basemap TileJSONs declare `maxzoom: 14`. MapLibre reads that and
 * *overzooms* the z14 tiles rather than requesting z15+, which is what we
 * want: the z15+ tiles do not exist on these CDNs (Carto 404s, OpenFreeMap
 * returns empty bodies), so asking for them would blank the map.
 */
const VECTOR_STYLES = {
  light: 'https://tiles.basemaps.cartocdn.com/gl/positron-gl-style/style.json',
  dark: 'https://tiles.basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
} as const;

/**
 * Esri World Imagery.
 *
 * The service stops serving real imagery at a zoom that depends on where you
 * are: z19 in most cities, z17 in deserts and open ocean, and nowhere at all
 * in places like Greenland. Past its limit it returns a 2.5 KB grey tile with
 * "Map data not available" printed on it.
 *
 * Declaring `maxzoom` makes MapLibre overzoom the deepest tile that really
 * exists instead of fetching that placeholder -- so zooming in gives blurry
 * imagery rather than a grey error. The value is chosen per location by
 * `probeImageryDepth`; see `IMAGERY_MAX_ZOOM_GLOBAL` and
 * `IMAGERY_MAX_ZOOM_CITY` in `@/lib/imagery`.
 */
const IMAGERY_SOURCE = {
  type: 'raster' as const,
  tiles: [
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
  ],
  tileSize: 256,
  attribution: 'Tiles &copy; Esri',
};

/** Hard ceiling on the map zoom, so the view can never become a void. */
const MAX_MAP_ZOOM = 20;

const MapComponent: React.FC<MapProps> = ({
  center = [0, 20],
  zoom = 2,
  marker,
  mode = 'real-world',
  game,
  gameCoords,
  seed,
  mapStyle = 'dark',
  imageryDetail = 'auto',
  focus,
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
  /* Imagery depth                                                     */
  /* ---------------------------------------------------------------- */

  // The depth the imagery source will overzoom from. 'auto' uses whatever
  // the probe found; an explicit choice overrides it.
  const [probedMaxZoom, setProbedMaxZoom] = useState(IMAGERY_MAX_ZOOM_GLOBAL);

  const imageryMaxZoom =
    imageryDetail === 'sharp'
      ? IMAGERY_MAX_ZOOM_CITY
      : imageryDetail === 'balanced'
        ? IMAGERY_MAX_ZOOM_GLOBAL
        : probedMaxZoom;

  const focusLat = focus?.lat;
  const focusLng = focus?.lng;

  // In 'auto' mode, ask Esri whether the locked coordinate actually has
  // imagery at city depth. One small probe per scan.
  useEffect(() => {
    if (imageryDetail !== 'auto' || focusLat === undefined || focusLng === undefined) return;
    let cancelled = false;
    void probeImageryDepth(focusLat, focusLng).then((depth) => {
      if (!cancelled) setProbedMaxZoom(depth);
    });
    return () => {
      cancelled = true;
    };
  }, [imageryDetail, focusLat, focusLng]);

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

  /**
   * Build the satellite style.
   *
   * Satellite is a hybrid: Esri imagery on the bottom, the vector basemap's
   * place labels on top. The vector basemap's own opaque base layers are
   * dropped so the imagery shows through, but its labels survive -- which
   * means the map still tells you where you are even where the imagery
   * stops.
   *
   * The style is assembled as an *object* rather than by swapping to the
   * basemap URL and then adding a layer: MapLibre skips reloading a style
   * whose URL is unchanged, so `style.load` would never fire and the
   * imagery layer would silently never be added.
   */
  const buildSatelliteStyle = useCallback(async (maxzoom: number) => {
    const base = await fetch(VECTOR_STYLES.dark).then((response) => response.json());
    const labelLayers = (base.layers ?? []).filter((layer: { type?: string }) => layer.type === 'symbol');

    return {
      version: 8 as const,
      glyphs: base.glyphs,
      sprite: base.sprite,
      sources: {
        ...base.sources,
        'esri-imagery': { ...IMAGERY_SOURCE, maxzoom },
      },
      layers: [
        {
          id: 'satellite-background',
          type: 'background' as const,
          paint: { 'background-color': '#0b0b0c' },
        },
        {
          id: 'esri-imagery',
          type: 'raster' as const,
          source: 'esri-imagery',
          paint: { 'raster-opacity': 1 },
        },
        ...labelLayers,
      ],
    };
  }, []);

  const applyStyle = useCallback(
    (target: maplibregl.Map, style: 'dark' | 'light' | 'satellite', maxzoom: number) => {
      if (style === 'satellite') {
        void buildSatelliteStyle(maxzoom).then((styleSpec) => {
          target.setStyle(styleSpec);
        });
        return;
      }
      target.setStyle(VECTOR_STYLES[style]);
    },
    [buildSatelliteStyle],
  );

  useEffect(() => {
    if (map.current || !mapContainer.current) return;

    map.current = new maplibregl.Map({
      container: mapContainer.current,
      style: VECTOR_STYLES.dark,
      center: initialView.current.center,
      zoom: initialView.current.zoom,
      minZoom: 1,
      maxZoom: MAX_MAP_ZOOM,
    });
    appliedStyle.current = initialView.current.style;

    return () => {
      markerRef.current = null;
      map.current?.remove();
      map.current = null;
    };
  }, []);

  // The satellite style depends on the imagery depth, so it is rebuilt
  // whenever that changes.
  const styleSignature = mapStyle === 'satellite' ? `satellite:${imageryMaxZoom}` : mapStyle;

  useEffect(() => {
    if (!map.current) return;
    if (appliedStyle.current === styleSignature) return;
    appliedStyle.current = styleSignature;
    applyStyle(map.current, mapStyle, imageryMaxZoom);
  }, [styleSignature, mapStyle, imageryMaxZoom, applyStyle]);

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
