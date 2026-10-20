'use client';

import { useCallback, useSyncExternalStore } from 'react';
import { EMPTY_KEYS } from './types';
import type { ByokKeys, ProviderSlug } from './types';

const STORAGE_KEY = 'pinpoint:byok-keys';
const REMEMBER_KEY = 'pinpoint:byok-remember';

interface ByokStore {
  keys: ByokKeys;
  remember: boolean;
}

const SERVER_SNAPSHOT: ByokStore = { keys: EMPTY_KEYS, remember: false };

/**
 * `localStorage` is an external store: it can be read before React mounts and
 * it survives reloads. `useSyncExternalStore` is the primitive that models
 * that correctly -- it gives the server a stable snapshot for hydration and
 * then picks up the stored value on the client, without a setState inside
 * an effect body.
 */
let current: ByokStore = SERVER_SNAPSHOT;
let loaded = false;
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
    const remember = window.localStorage.getItem(REMEMBER_KEY) === '1';
    if (!remember) return { keys: { ...EMPTY_KEYS }, remember: false };
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { keys: { ...EMPTY_KEYS }, remember: true };
    const parsed = JSON.parse(raw) as Partial<ByokKeys>;
    return {
      remember: true,
      keys: {
        groq: parsed.groq ?? '',
        gemini: parsed.gemini ?? '',
        openai: parsed.openai ?? '',
      },
    };
  } catch {
    // Storage can be unavailable (private mode, blocked cookies). Staying
    // in session-only mode is the correct fallback.
    return { keys: { ...EMPTY_KEYS }, remember: false };
  }
}

function getSnapshot(): ByokStore {
  if (!loaded) {
    loaded = true;
    current = readFromStorage();
  }
  return current;
}

function persist(store: ByokStore) {
  try {
    if (store.remember) {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(store.keys));
      window.localStorage.setItem(REMEMBER_KEY, '1');
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
      window.localStorage.removeItem(REMEMBER_KEY);
    }
  } catch {
    // The keys still work for this session even when storage is blocked.
  }
}

function commit(store: ByokStore) {
  current = store;
  persist(store);
  emit();
}

/**
 * Bring-your-own-key state.
 *
 * Keys live in memory by default, so they are discarded when the tab
 * closes. The operator can opt into remembering them on the device, which
 * writes them to `localStorage` -- convenient, but readable by any script
 * that runs on this origin, so it is opt-in and clearly labelled.
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

  const clear = useCallback(() => {
    commit({ keys: { ...EMPTY_KEYS }, remember: false });
  }, []);

  const active = Boolean(store.keys.groq || store.keys.gemini || store.keys.openai);

  return {
    keys: store.keys,
    setKey,
    remember: store.remember,
    setRemember,
    clear,
    active,
  };
}
