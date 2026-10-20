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

/** Longest edge, in pixels, of the image we actually send. */
const MAX_UPLOAD_EDGE = 1600;

/** JPEG quality used for the downscale. */
const UPLOAD_QUALITY = 0.9;

/** Below this, a file is already cheap enough to send untouched. */
const UPLOAD_SIZE_FLOOR = 1_000_000;

/**
 * Downscale the image before it is uploaded.
 *
 * Two reasons. Vercel Functions reject request bodies over 4.5 MB, and the
 * vision models resize to 224x224 internally regardless -- so a twelve
 * megapixel phone photo is pure waste on the wire. Signage is the one thing
 * that needs resolution, so the long edge is kept generous.
 */
async function prepareUpload(file: File): Promise<File> {
  if (!file.type.startsWith('image/')) return file;
  try {
    const bitmap = await createImageBitmap(file);
    const longestEdge = Math.max(bitmap.width, bitmap.height);
    const scale = Math.min(1, MAX_UPLOAD_EDGE / longestEdge);
    if (scale === 1 && file.size < UPLOAD_SIZE_FLOOR) {
      bitmap.close();
      return file;
    }
    const width = Math.round(bitmap.width * scale);
    const height = Math.round(bitmap.height * scale);
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext('2d');
    if (!context) {
      bitmap.close();
      return file;
    }
    context.drawImage(bitmap, 0, 0, width, height);
    bitmap.close();
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, 'image/jpeg', UPLOAD_QUALITY),
    );
    if (!blob) return file;
    return new File([blob], `${file.name.replace(/\.[^.]+$/, '')}.jpg`, { type: 'image/jpeg' });
  } catch {
    // Some formats (HEIC, for one) cannot be decoded in the browser.
    return file;
  }
}

/** Run a scan. BYOK keys ride along with the request and are never stored. */
export async function scanImage(file: File, options: ScanOptions): Promise<ScanResult> {
  const form = new FormData();
  form.append('file', await prepareUpload(file));
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
