'use client';

import { useCallback, useSyncExternalStore } from 'react';
import type {
  AccentColor,
  ImageryDetail,
  MapStyle,
  ModelChoice,
  ModelSelection,
} from './types';

const STORAGE_KEY = 'pinpoint:settings';

/**
 * The preferences that are worth keeping between visits.
 *
 * None of these are secrets, so they are written to `localStorage` without
 * ceremony -- but only when the operator asks for it, and never as a side
 * effect of the API calls that use them.
 */
export interface Settings {
  theme: 'dark' | 'light';
  accentColor: AccentColor;
  mapStyle: MapStyle;
  imageryDetail: ImageryDetail;
  selectedModel: ModelChoice;
  modelSelection: ModelSelection;
}

export const DEFAULT_SETTINGS: Settings = {
  theme: 'dark',
  accentColor: 'red',
  mapStyle: 'dark',
  imageryDetail: 'auto',
  selectedModel: 'auto',
  modelSelection: {},
};

interface Persisted {
  values: Settings;
  savedAt: number;
}

interface Store {
  values: Settings;
  /** True when the live values differ from what is on disk. */
  dirty: boolean;
  /** When the values were last written to disk, or null if never. */
  savedAt: number | null;
  /** True when something has been written to disk before. */
  stored: boolean;
}

function sameSelection(a: ModelSelection, b: ModelSelection): boolean {
  const slugs = new Set<string>([...Object.keys(a), ...Object.keys(b)]);
  for (const slug of slugs) {
    const left = (a as Record<string, string | undefined>)[slug];
    const right = (b as Record<string, string | undefined>)[slug];
    if ((left ?? '') !== (right ?? '')) return false;
  }
  return true;
}

function sameSettings(a: Settings, b: Settings): boolean {
  return (
    a.theme === b.theme &&
    a.accentColor === b.accentColor &&
    a.mapStyle === b.mapStyle &&
    a.imageryDetail === b.imageryDetail &&
    a.selectedModel === b.selectedModel &&
    sameSelection(a.modelSelection, b.modelSelection)
  );
}

/**
 * `localStorage` is an external store: it can be read before React mounts and
 * it survives reloads. `useSyncExternalStore` is the primitive that models
 * that correctly -- it gives the server a stable snapshot for hydration and
 * then picks up the stored value on the client, without a setState inside an
 * effect body.
 *
 * Two layers are kept: `saved` is what is on disk, `current` is what the
 * interface is showing. They differ while there are unsaved changes, which
 * is what the Save button acts on.
 */
let saved: Settings = DEFAULT_SETTINGS;
let snapshot: Store = {
  values: DEFAULT_SETTINGS,
  dirty: false,
  savedAt: null,
  stored: false,
};
let hydrated = false;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function hydrate() {
  if (hydrated) return;
  hydrated = true;
  if (typeof window === 'undefined') return;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw) as Partial<Persisted>;
    const values: Settings = { ...DEFAULT_SETTINGS, ...(parsed.values ?? {}) };
    saved = values;
    snapshot = {
      values,
      dirty: false,
      savedAt: typeof parsed.savedAt === 'number' ? parsed.savedAt : null,
      stored: true,
    };
  } catch {
    // Storage blocked or the blob is corrupt: fall back to the defaults
    // rather than leaving the panel in a half-applied state.
  }
}

function getSnapshot(): Store {
  hydrate();
  return snapshot;
}

function set(patch: Partial<Settings>) {
  const values: Settings = { ...snapshot.values, ...patch };
  snapshot = {
    ...snapshot,
    values,
    dirty: !sameSettings(values, saved),
  };
  emit();
}

/**
 * Write the current values to disk.
 *
 * Returns false when the browser refused to write -- private browsing and
 * blocked storage are the usual reasons -- so the interface can say so
 * instead of pretending the save worked.
 */
function save(): boolean {
  if (typeof window === 'undefined') return false;
  const values = snapshot.values;
  const savedAt = Date.now();
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ values, savedAt }));
  } catch {
    return false;
  }
  saved = values;
  snapshot = { values, dirty: false, savedAt, stored: true };
  emit();
  return true;
}

/** Throw the live values away and go back to what is on disk. */
function discard() {
  snapshot = { ...snapshot, values: saved, dirty: false };
  emit();
}

/** Forget everything, on disk and in the interface. */
function reset() {
  saved = DEFAULT_SETTINGS;
  snapshot = { values: DEFAULT_SETTINGS, dirty: false, savedAt: null, stored: false };
  if (typeof window !== 'undefined') {
    try {
      window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      // Nothing to do: the values are already gone from the interface.
    }
  }
  emit();
}

export function useSettings() {
  const store = useSyncExternalStore(subscribe, getSnapshot, () => snapshot);

  const update = useCallback((patch: Partial<Settings>) => set(patch), []);

  return {
    values: store.values,
    dirty: store.dirty,
    savedAt: store.savedAt,
    stored: store.stored,
    set: update,
    save,
    discard,
    reset,
  };
}
