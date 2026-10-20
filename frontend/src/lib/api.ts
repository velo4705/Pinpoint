import axios from 'axios';
import type {
  ByokKeys,
  CatalogSlug,
  ModelCatalog,
  ModelChoice,
  ModelSelection,
  ProviderStatus,
  ScanMode,
  ScanResult,
  VaultEntry,
} from './types';

export const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface ScanOptions {
  mode: ScanMode;
  game?: string;
  model: ModelChoice;
  byok: ByokKeys;
  /** Which models to consult, as `provider:model` ids. */
  models?: string[];
}

/** Flatten a per-provider selection into the `provider:model` list the API wants. */
export function selectionToIds(selection: ModelSelection): string[] {
  return (Object.keys(selection) as CatalogSlug[]).flatMap((slug) =>
    (selection[slug] ?? []).map((model) => `${slug}:${model}`),
  );
}

/** Run a scan. BYOK keys ride along with the request and are never stored. */
export async function scanImage(file: File, options: ScanOptions): Promise<ScanResult> {
  const form = new FormData();
  form.append('file', file);
  form.append('mode', options.mode);
  form.append('model', options.model);
  if (options.mode === 'game') form.append('game', options.game ?? 'Generic');
  if (options.byok.groq) form.append('groq_key', options.byok.groq);
  if (options.byok.gemini) form.append('gemini_key', options.byok.gemini);
  if (options.byok.openai) form.append('openai_key', options.byok.openai);
  const models = options.models ?? [];
  if (models.length) form.append('models', models.join(','));

  const response = await axios.post<ScanResult>(`${API_URL}/scan`, form, { timeout: 180_000 });
  return response.data;
}

/** The models this build can use, grouped by provider. */
export async function fetchModelCatalog(): Promise<ModelCatalog> {
  const response = await axios.get<ModelCatalog>(`${API_URL}/models`, { timeout: 15_000 });
  return response.data;
}

/** Probe each provider with the effective keys (BYOK wins over server keys). */
export async function verifyKeys(byok: ByokKeys): Promise<ProviderStatus[]> {
  const form = new FormData();
  if (byok.groq) form.append('groq_key', byok.groq);
  if (byok.gemini) form.append('gemini_key', byok.gemini);
  if (byok.openai) form.append('openai_key', byok.openai);

  const response = await axios.post<{ providers: ProviderStatus[] }>(
    `${API_URL}/keys/verify`,
    form,
    { timeout: 60_000 },
  );
  return response.data.providers;
}

/** Read the operator's recent discoveries. */
export async function fetchHistory(): Promise<VaultEntry[]> {
  const response = await axios.get<VaultEntry[]>(`${API_URL}/history`, { timeout: 15_000 });
  return Array.isArray(response.data) ? response.data : [];
}
