'use client';

import { useCallback, useSyncExternalStore } from 'react';
import { EMPTY_KEYS } from './types';
import type { ByokKeys, ProviderSlug } from './types';

const STORAGE_KEY = 'pinpoint:byok';

interface ByokStore {
  keys: ByokKeys;
  /** Whether the operator wants the keys kept on this device. */
  remember: boolean;
  /** True when the live values differ from what is on disk. */
  dirty: boolean;
  /** True when keys have been written to disk before. */
  stored: boolean;
}

const SERVER_SNAPSHOT: ByokStore = {
  keys: EMPTY_KEYS,
  remember: false,
  dirty: false,
  stored: false,
};

/**
 * `localStorage` is an external store: it can be read before React mounts and
 * it survives reloads. `useSyncExternalStore` is the primitive that models
 * that correctly -- it gives the server a stable snapshot for hydration and
 * then picks up the stored value on the client, without a setState inside an
 * effect body.
 *
 * Two layers are kept: `saved` is what is on disk, `current` is what the
 * operator has typed. Nothing reaches the disk until Save is pressed, so a
 * key that is merely typed is never persisted by accident.
 */
let current: ByokStore = SERVER_SNAPSHOT;
let saved: ByokStore = SERVER_SNAPSHOT;
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

function readFromStorage(): ByokStore {
  if (typeof window === 'undefined') return SERVER_SNAPSHOT;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...SERVER_SNAPSHOT, keys: { ...EMPTY_KEYS } };
    const parsed = JSON.parse(raw) as { remember?: boolean; keys?: Partial<ByokKeys> };
    return {
      remember: parsed.remember === true,
      keys: {
        groq: parsed.keys?.groq ?? '',
        gemini: parsed.keys?.gemini ?? '',
        openai: parsed.keys?.openai ?? '',
      },
      dirty: false,
      stored: true,
    };
  } catch {
    // Storage can be unavailable (private mode, blocked cookies). Staying
    // in session-only mode is the correct fallback.
    return { ...SERVER_SNAPSHOT, keys: { ...EMPTY_KEYS } };
  }
}

function getSnapshot(): ByokStore {
  if (!hydrated) {
    hydrated = true;
    current = readFromStorage();
    saved = { ...current, keys: { ...current.keys } };
  }
  return current;
}

function isDirty(next: ByokStore): boolean {
  return (
    next.remember !== saved.remember ||
    next.keys.groq !== saved.keys.groq ||
    next.keys.gemini !== saved.keys.gemini ||
    next.keys.openai !== saved.keys.openai
  );
}

function commit(next: ByokStore) {
  current = { ...next, dirty: isDirty(next) };
  emit();
}

/**
 * Bring-your-own-key state.
 *
 * Keys live in memory by default, so they are discarded when the tab closes.
 * The operator can ask for them to be kept on the device, which writes them
 * to `localStorage` -- convenient, but readable by any script that runs on
 * this origin, so it is opt-in and clearly labelled.
 *
 * The keys are sent to the Pinpoint API with a single scan request. The
 * server never persists them.
 */
export function useByok() {
  const store = useSyncExternalStore(subscribe, getSnapshot, () => SERVER_SNAPSHOT);

  const setKey = useCallback((slug: ProviderSlug, value: string) => {
    commit({ ...current, keys: { ...current.keys, [slug]: value } });
  }, []);

  const setRemember = useCallback((enabled: boolean) => {
    commit({ ...current, remember: enabled });
  }, []);

  /**
   * Write the keys to disk -- but only if the operator asked for it.
   *
   * Returns false when the browser refused to write, so the interface can
   * report the failure rather than implying the keys are safe on disk.
   */
  const save = useCallback((): boolean => {
    if (typeof window === 'undefined') return false;
    try {
      if (current.remember) {
        window.localStorage.setItem(
          STORAGE_KEY,
          JSON.stringify({ remember: true, keys: current.keys }),
        );
        saved = { ...current, keys: { ...current.keys } };
        current = { ...current, dirty: false, stored: true };
      } else {
        // The operator does not want them kept: take them off the disk.
        window.localStorage.removeItem(STORAGE_KEY);
        saved = { ...current, keys: { ...current.keys } };
        current = { ...current, dirty: false, stored: false };
      }
    } catch {
      return false;
    }
    emit();
    return true;
  }, []);

  /** Throw the typed keys away and go back to what is on disk. */
  const discard = useCallback(() => {
    current = { ...saved, keys: { ...saved.keys }, dirty: false };
    emit();
  }, []);

  /** Wipe the keys from memory *and* from the disk, right now. */
  const clear = useCallback(() => {
    if (typeof window !== 'undefined') {
      try {
        window.localStorage.removeItem(STORAGE_KEY);
      } catch {
        // Nothing to do: the keys are already gone from the interface.
      }
    }
    saved = { ...SERVER_SNAPSHOT, keys: { ...EMPTY_KEYS } };
    current = { ...SERVER_SNAPSHOT, keys: { ...EMPTY_KEYS } };
    emit();
  }, []);

  const active = Boolean(store.keys.groq || store.keys.gemini || store.keys.openai);

  return {
    keys: store.keys,
    setKey,
    remember: store.remember,
    setRemember,
    dirty: store.dirty,
    stored: store.stored,
    save,
    discard,
    clear,
    active,
  };
}
