/** Shared API types for the Pinpoint console. */

export type ScanMode = 'real-world' | 'game';

export type ModelChoice =
  | 'auto'
  | 'gemini-only'
  | 'groq-only'
  | 'openai-only'
  | 'local-only';

export type ProviderSlug = 'gemini' | 'groq' | 'openai';

export type MapStyle = 'dark' | 'light' | 'satellite';

export type AccentColor = 'red' | 'blue' | 'green' | 'purple' | 'orange';

/** Bring-your-own-key material, per provider. */
export interface ByokKeys {
  groq: string;
  gemini: string;
  openai: string;
}

export const EMPTY_KEYS: ByokKeys = { groq: '', gemini: '', openai: '' };

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
