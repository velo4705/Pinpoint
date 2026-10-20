/** Shared API types for the Pinpoint console. */

export type ScanMode = 'real-world' | 'game';

export type ModelChoice =
  | 'auto'
  | 'gemini-only'
  | 'groq-only'
  | 'openai-only'
  | 'local-only';

/** Providers that take a key. */
export type ProviderSlug = 'gemini' | 'groq' | 'openai';

/** Providers in the catalogue, including the offline one. */
export type CatalogSlug = ProviderSlug | 'local';

export type MapStyle = 'dark' | 'light' | 'satellite';

/**
 * How deep the satellite imagery goes.
 *
 * - `auto` probes the imagery service for the locked coordinate and uses the
 *   sharpest depth that actually has data there.
 * - `balanced` always uses the globally safe depth: never a blank tile, but
 *   softer imagery when zoomed right in.
 * - `sharp` always uses the deepest city-level imagery: crisper, but some
 *   remote regions have no data at that depth.
 */
export type ImageryDetail = 'auto' | 'balanced' | 'sharp';

export type AccentColor = 'red' | 'blue' | 'green' | 'purple' | 'orange';

/** Bring-your-own-key material, per provider. */
export interface ByokKeys {
  groq: string;
  gemini: string;
  openai: string;
}

export const EMPTY_KEYS: ByokKeys = { groq: '', gemini: '', openai: '' };

/** One selectable model, as published by the API's /models endpoint. */
export interface CatalogModel {
  id: string;
  label: string;
  note: string;
  /** Position in the engine's recommended accuracy ladder. */
  tier: number;
  gameCapable: boolean;
}

/** A provider and the models it offers. */
export interface CatalogProvider {
  slug: CatalogSlug;
  label: string;
  hint: string;
  keyEnv: string | null;
  models: CatalogModel[];
}

export interface ModelCatalog {
  providers: CatalogProvider[];
}

/**
 * Which models a scan should consult, per provider.
 *
 * An empty list for a provider means "let the engine decide".
 */
export type ModelSelection = Partial<Record<CatalogSlug, string[]>>;

export const PROVIDER_META: Record<ProviderSlug, { label: string; hint: string }> = {
  groq: { label: 'Groq', hint: 'gsk_... - fastest inference' },
  gemini: { label: 'Gemini', hint: 'AIza... - Google DeepMind' },
  openai: { label: 'OpenAI', hint: 'sk-... - GPT vision' },
};

/** Real-world scan returns lat/lng; a game scan returns x/y/z. */
export interface ScanCoordinates {
  lat?: number;
  lng?: number;
  x?: number;
  y?: number;
  z?: number;
}

/** A completed scan, as rendered by the console. */
export interface ScanResult {
  location: string;
  coordinates: ScanCoordinates;
  confidence: number;
  source?: string;
  tier?: number;
  /** How many models agreed on this answer. */
  support?: number;
  /** Which models were consulted. */
  consulted?: string[];
  mode: ScanMode;
  game?: string;
  seed?: string;
  version?: string;
  type?: string;
  /** Local preview of the uploaded file. Never sent to the server. */
  image?: string;
  insights?: string[];
  error?: string;
}

/** An entry in the Discovery Vault. */
export interface VaultEntry {
  id: number;
  timestamp: string;
  location?: string;
  coordinates?: ScanCoordinates;
  mode?: ScanMode;
  confidence?: number;
  source?: string;
  tier?: number;
  game?: string;
  seed?: string;
}

export interface ProviderStatus {
  provider: ProviderSlug;
  label: string;
  status: 'ok' | 'unset' | 'error';
  detail?: string;
}
