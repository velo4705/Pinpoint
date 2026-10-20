/**
 * Esri World Imagery depth probing.
 *
 * The imagery service is a mosaic with a resolution gradient: cities carry
 * real imagery down to z19, deserts and open ocean stop at z17, and some
 * regions (Greenland) have none at all. Past the local limit the service
 * serves a 2,521-byte grey tile with "Map data not available" printed on it.
 *
 * Real imagery is always 4 KB or larger, so anything under
 * `PLACEHOLDER_THRESHOLD` is that placeholder. Probing one tile tells us
 * which depth is worth using for a location, which lets the map pick sharp
 * imagery where it exists and fall back gracefully where it does not.
 */

/** Anything smaller than this is Esri's "no data" placeholder, not imagery. */
const PLACEHOLDER_THRESHOLD = 3500;

/** The deepest zoom at which Esri carries imagery for most populated places. */
export const IMAGERY_MAX_ZOOM_CITY = 19;

/** The deepest zoom with coverage over essentially all land. */
export const IMAGERY_MAX_ZOOM_GLOBAL = 17;

const ESRI_TILE =
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';

/** The standard XYZ tile that contains a coordinate at a given zoom. */
export function tileUrl(lat: number, lng: number, zoom: number): string {
  const scale = 2 ** zoom;
  const x = Math.floor(((lng + 180) / 360) * scale);
  const latRadians = (lat * Math.PI) / 180;
  const y = Math.floor(((1 - Math.asinh(Math.tan(latRadians)) / Math.PI) / 2) * scale);
  return ESRI_TILE.replace('{z}', String(zoom)).replace('{y}', String(y)).replace('{x}', String(x));
}

/** True when Esri has real imagery for this coordinate at this zoom. */
export async function hasImageryAt(lat: number, lng: number, zoom: number): Promise<boolean> {
  try {
    const response = await fetch(tileUrl(lat, lng, zoom), { method: 'GET' });
    if (!response.ok) return false;

    // `content-length` is a CORS-safelisted header, so it is readable
    // cross-origin without exposing the full response.
    const declared = Number(response.headers.get('content-length') ?? '0');
    if (declared > 0) return declared > PLACEHOLDER_THRESHOLD;

    const buffer = await response.arrayBuffer();
    return buffer.byteLength > PLACEHOLDER_THRESHOLD;
  } catch {
    // No network, blocked, or the service refused: assume no imagery.
    return false;
  }
}

/**
 * The deepest imagery zoom with real coverage at this coordinate.
 *
 * Returns 19 where the service carries city-level imagery, otherwise the
 * globally safe 17.
 */
export async function probeImageryDepth(lat: number, lng: number): Promise<number> {
  if (await hasImageryAt(lat, lng, IMAGERY_MAX_ZOOM_CITY)) return IMAGERY_MAX_ZOOM_CITY;
  return IMAGERY_MAX_ZOOM_GLOBAL;
}
