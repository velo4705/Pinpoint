'use client';

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Settings, CheckCircle2, CircleDashed, CircleX, Loader2, KeyRound, Trash2 } from 'lucide-react';
import { verifyKeys } from '@/lib/api';
import { PROVIDER_META } from '@/lib/types';
import type {
  AccentColor,
  ByokKeys,
  CatalogSlug,
  ImageryDetail,
  MapStyle,
  ModelCatalog,
  ModelChoice,
  ModelSelection,
  ProviderSlug,
  ProviderStatus,
} from '@/lib/types';

interface SettingsPanelProps {
  isOpen: boolean;
  onClose: () => void;
  accentColor: AccentColor;
  onAccentChange: (color: AccentColor) => void;
  mapStyle: MapStyle;
  onMapStyleChange: (style: MapStyle) => void;
  imageryDetail: ImageryDetail;
  onImageryDetailChange: (detail: ImageryDetail) => void;
  selectedModel: ModelChoice;
  onModelChange: (model: ModelChoice) => void;
  byok: ByokKeys;
  onByokChange: (slug: ProviderSlug, value: string) => void;
  catalog: ModelCatalog | null;
  modelSelection: ModelSelection;
  onModelSelectionChange: (selection: ModelSelection) => void;
  rememberKeys: boolean;
  onRememberChange: (enabled: boolean) => void;
  onClearKeys: () => void;
}

const ACCENTS: AccentColor[] = ['red', 'blue', 'green', 'purple', 'orange'];
const MAP_STYLES: MapStyle[] = ['dark', 'light', 'satellite'];
const IMAGERY_DETAILS: { value: ImageryDetail; label: string; hint: string }[] = [
  {
    value: 'auto',
    label: 'Auto',
    hint: 'Picks the sharpest imagery that exists at the scanned location',
  },
  {
    value: 'balanced',
    label: 'Balanced',
    hint: 'Never shows a blank tile, but imagery is softer when zoomed in',
  },
  {
    value: 'sharp',
    label: 'Sharp',
    hint: 'Sharpest city imagery, but some remote areas have no data at that depth',
  },
];
const MODELS: { value: ModelChoice; label: string }[] = [
  { value: 'auto', label: 'Automatic' },
  { value: 'gemini-only', label: 'Gemini-Only' },
  { value: 'groq-only', label: 'Groq-Only' },
  { value: 'openai-only', label: 'OpenAI-Only' },
  { value: 'local-only', label: 'Local AI Engine' },
];

const STATUS_ICON = {
  ok: CheckCircle2,
  unset: CircleDashed,
  error: CircleX,
} as const;

const STATUS_COLOR = {
  ok: 'text-emerald-400',
  unset: 'text-[var(--text-muted)]',
  error: 'text-red-400',
} as const;

const SettingsPanel: React.FC<SettingsPanelProps> = ({
  isOpen,
  onClose,
  accentColor,
  onAccentChange,
  mapStyle,
  onMapStyleChange,
  imageryDetail,
  onImageryDetailChange,
  selectedModel,
  onModelChange,
  byok,
  onByokChange,
  catalog,
  modelSelection,
  onModelSelectionChange,
  rememberKeys,
  onRememberChange,
  onClearKeys,
}) => {
  const [statuses, setStatuses] = useState<ProviderStatus[] | null>(null);
  const [testing, setTesting] = useState(false);
  const [testError, setTestError] = useState<string | null>(null);

  const runTest = async () => {
    setTesting(true);
    setTestError(null);
    try {
      setStatuses(await verifyKeys(byok));
    } catch (error) {
      setStatuses(null);
      setTestError(
        error instanceof Error
          ? error.message
          : 'Could not reach the Pinpoint API. Is the backend running?',
      );
    } finally {
      setTesting(false);
    }
  };

  const hasKey = Boolean(byok.groq || byok.gemini || byok.openai);

  // "Auto" means the engine picks its own accuracy-ordered ladder.
  const selectionIsEmpty = Object.values(modelSelection).every(
    (models) => !models || models.length === 0,
  );

  const toggleModel = (slug: CatalogSlug, modelId: string) => {
    const current = modelSelection[slug] ?? [];
    const next = current.includes(modelId)
      ? current.filter((id) => id !== modelId)
      : [...current, modelId];
    onModelSelectionChange({ ...modelSelection, [slug]: next });
  };

  const selectOnly = (slug: CatalogSlug, modelId: string) => {
    onModelSelectionChange({ ...modelSelection, [slug]: [modelId] });
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="absolute inset-0 bg-black/60 z-[80] backdrop-blur-md pointer-events-auto"
          />
          <motion.div
            initial={{ scale: 0.95, opacity: 0, y: 20 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            exit={{ scale: 0.95, opacity: 0, y: 20 }}
            className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-md max-h-[85vh] overflow-y-auto modern-panel p-8 z-[90] pointer-events-auto flex flex-col gap-6"
          >
            <div className="flex items-center justify-between border-b border-[var(--border)] pb-4">
              <div className="flex items-center gap-2 text-[var(--accent)]">
                <Settings className="w-5 h-5" />
                <h2 className="text-xs font-black uppercase tracking-[0.3em]">System Control Panel</h2>
              </div>
              <button onClick={onClose} className="text-[var(--text-muted)] hover:text-red-500">
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Bring your own key */}
            <div className="flex flex-col gap-3">
              <label className="text-[9px] text-[var(--text-muted)] uppercase tracking-widest font-black flex items-center gap-2">
                <KeyRound className="w-3.5 h-3.5" />
                Neural Link Override
              </label>
              <p className="text-[9px] text-[var(--text-muted)] leading-relaxed">
                Use your own API keys instead of the server&apos;s. Keys travel with a single scan
                request and are never written to the Pinpoint server, the cache, or the log.
              </p>

              <div className="flex flex-col gap-2">
                {(Object.keys(PROVIDER_META) as ProviderSlug[]).map((slug) => (
                  <div key={slug} className="flex flex-col gap-1">
                    <span className="text-[8px] text-[var(--text-muted)] uppercase tracking-widest font-black">
                      {PROVIDER_META[slug].label}
                    </span>
                    <input
                      type="password"
                      autoComplete="off"
                      spellCheck={false}
                      value={byok[slug]}
                      onChange={(event) => onByokChange(slug, event.target.value)}
                      placeholder={PROVIDER_META[slug].hint}
                      className="w-full bg-[var(--bg)] border border-[var(--border)] rounded-xl px-4 py-3 text-xs font-mono outline-none focus:border-[var(--accent)]/50 transition-all text-[var(--text)]"
                    />
                  </div>
                ))}
              </div>

              <label className="flex items-start gap-3 cursor-pointer group">
                <input
                  type="checkbox"
                  checked={rememberKeys}
                  onChange={(event) => onRememberChange(event.target.checked)}
                  className="mt-0.5 w-3.5 h-3.5 accent-[var(--accent)] cursor-pointer"
                />
                <span className="text-[9px] text-[var(--text-muted)] leading-relaxed group-hover:text-[var(--text)] transition-colors">
                  Remember keys on this device
                  <span className="block opacity-70">
                    Off by default: keys are kept in memory and cleared when the tab closes. Turning
                    this on stores them in this browser&apos;s local storage.
                  </span>
                </span>
              </label>

              {/* Model selection */}
              <div className="flex flex-col gap-3 pt-1 border-t border-[var(--border)]">
                <div className="flex items-center justify-between">
                  <label className="text-[9px] text-[var(--text-muted)] uppercase tracking-widest font-black flex items-center gap-2">
                    <KeyRound className="w-3.5 h-3.5" />
                    Models
                  </label>
                  {selectionIsEmpty ? (
                    <span className="text-[8px] font-black uppercase tracking-widest text-[var(--accent)]">
                      Auto ladder
                    </span>
                  ) : (
                    <button
                      onClick={() => onModelSelectionChange({})}
                      className="text-[8px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--accent)] transition-colors"
                    >
                      Reset to auto
                    </button>
                  )}
                </div>

                <p className="text-[8px] text-[var(--text-muted)] leading-relaxed">
                  {selectionIsEmpty
                    ? 'The engine consults models in its own accuracy order and goes with the answer they agree on. Pick models below to take control.'
                    : 'Only the models you pick are consulted, in the order shown. The number is the engine’s recommended rank.'}
                </p>

                {!catalog && (
                  <p className="text-[8px] text-[var(--text-muted)] opacity-70">
                    Model catalogue unavailable — the API could not be reached.
                  </p>
                )}

                {catalog?.providers.map((provider) => {
                  const isLocal = provider.slug === 'local';
                  const selected = modelSelection[provider.slug] ?? [];
                  return (
                    <div key={provider.slug} className="flex flex-col gap-2">
                      <div className="flex items-baseline justify-between">
                        <span className="text-[9px] font-black uppercase tracking-widest text-[var(--text)]">
                          {provider.label}
                          {!provider.available && (
                            <span className="ml-2 text-[8px] font-normal normal-case text-red-400">
                              not installed here
                            </span>
                          )}
                        </span>
                        <span className="text-[8px] text-[var(--text-muted)]">{provider.hint}</span>
                      </div>

                      <div
                        className={`flex flex-col gap-1 max-h-40 overflow-y-auto no-scrollbar pr-1 ${
                          provider.available ? '' : 'opacity-40 pointer-events-none'
                        }`}
                      >
                        {provider.models.map((entry) => {
                          const checked = selected.includes(entry.id);
                          return (
                            <label
                              key={entry.id}
                              className="flex items-start gap-2 cursor-pointer group py-0.5"
                            >
                              <input
                                type={isLocal ? 'radio' : 'checkbox'}
                                name={isLocal ? `local-engine` : undefined}
                                checked={checked}
                                onChange={() =>
                                  isLocal ? selectOnly(provider.slug, entry.id) : toggleModel(provider.slug, entry.id)
                                }
                                className="mt-0.5 w-3 h-3 accent-[var(--accent)] cursor-pointer shrink-0"
                              />
                              <span className="flex flex-col min-w-0">
                                <span className="text-[9px] font-black uppercase tracking-wider text-[var(--text)] group-hover:text-[var(--accent)] transition-colors truncate">
                                  {entry.label}
                                  <span className="ml-2 text-[8px] font-mono font-normal text-[var(--text-muted)]">
                                    {entry.id}
                                  </span>
                                </span>
                                {entry.note && (
                                  <span className="text-[8px] text-[var(--text-muted)] opacity-75 leading-tight">
                                    {entry.note}
                                  </span>
                                )}
                              </span>
                            </label>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>

              <div className="flex gap-2">
                <button
                  onClick={runTest}
                  disabled={testing}
                  className="flex-1 py-2.5 rounded-xl border border-[var(--border)] bg-[var(--bg)] text-[9px] font-black uppercase tracking-widest flex items-center justify-center gap-2 transition-all hover:border-[var(--accent)]/50 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {testing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
                  {testing ? 'Testing' : 'Test Links'}
                </button>
                <button
                  onClick={onClearKeys}
                  disabled={!hasKey}
                  className="py-2.5 px-4 rounded-xl border border-[var(--border)] bg-[var(--bg)] text-[9px] font-black uppercase tracking-widest flex items-center gap-2 transition-all hover:border-red-500/50 hover:text-red-400 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  Clear
                </button>
              </div>

              {testError && (
                <p className="text-[9px] text-red-400 leading-relaxed">{testError}</p>
              )}

              {statuses && (
                <div className="bg-[var(--bg)] border border-[var(--border)] rounded-xl p-3 flex flex-col gap-2">
                  {statuses.map((entry) => {
                    const Icon = STATUS_ICON[entry.status];
                    return (
                      <div key={entry.provider} className="flex items-center justify-between gap-2">
                        <span className="text-[9px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                          {entry.label}
                        </span>
                        <span
                          className={`flex items-center gap-1.5 text-[9px] font-black uppercase tracking-widest ${STATUS_COLOR[entry.status]}`}
                        >
                          <Icon className="w-3.5 h-3.5" />
                          {entry.status}
                          {entry.detail ? ` (${entry.detail})` : ''}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Accent colour */}
            <div className="flex flex-col gap-3">
              <label className="text-[9px] text-[var(--text-muted)] uppercase tracking-widest font-black">
                Interface Accent Spectrum
              </label>
              <div className="flex gap-3">
                {ACCENTS.map((color) => {
                  const bgColors = {
                    red: 'bg-red-500',
                    blue: 'bg-blue-500',
                    green: 'bg-emerald-500',
                    purple: 'bg-violet-500',
                    orange: 'bg-orange-500',
                  }[color];
                  return (
                    <button
                      key={color}
                      onClick={() => onAccentChange(color)}
                      aria-label={`${color} accent`}
                      className={`w-8 h-8 rounded-full ${bgColors} transition-all flex items-center justify-center border-2 ${
                        accentColor === color
                          ? 'border-white scale-110 shadow-lg shadow-black/20'
                          : 'border-transparent opacity-60 hover:opacity-100 hover:scale-105'
                      }`}
                    />
                  );
                })}
              </div>
            </div>

            {/* Map style */}
            <div className="flex flex-col gap-3">
              <label className="text-[9px] text-[var(--text-muted)] uppercase tracking-widest font-black">
                Map Vision Mode
              </label>
              <div className="grid grid-cols-3 gap-2 bg-[var(--bg)] p-1 rounded-xl border border-[var(--border)]">
                {MAP_STYLES.map((style) => (
                  <button
                    key={style}
                    onClick={() => onMapStyleChange(style)}
                    className={`py-2 text-[8px] font-black uppercase tracking-widest rounded-lg transition-all ${
                      mapStyle === style
                        ? 'bg-[var(--accent)] text-white shadow-sm'
                        : 'text-[var(--text-muted)] hover:text-[var(--text)]'
                    }`}
                  >
                    {style}
                  </button>
                ))}
              </div>
            </div>

            {/* Imagery detail */}
            <div className="flex flex-col gap-3">
              <label className="text-[9px] text-[var(--text-muted)] uppercase tracking-widest font-black">
                Imagery Detail
              </label>
              <div className="grid grid-cols-3 gap-2 bg-[var(--bg)] p-1 rounded-xl border border-[var(--border)]">
                {IMAGERY_DETAILS.map((option) => (
                  <button
                    key={option.value}
                    onClick={() => onImageryDetailChange(option.value)}
                    className={`py-2 text-[8px] font-black uppercase tracking-widest rounded-lg transition-all ${
                      imageryDetail === option.value
                        ? 'bg-[var(--accent)] text-white shadow-sm'
                        : 'text-[var(--text-muted)] hover:text-[var(--text)]'
                    }`}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              <p className="text-[8px] text-[var(--text-muted)] leading-relaxed">
                {IMAGERY_DETAILS.find((option) => option.value === imageryDetail)?.hint}
              </p>
            </div>

            {/* Model selection */}
            <div className="flex flex-col gap-3">
              <label className="text-[9px] text-[var(--text-muted)] uppercase tracking-widest font-black">
                Targeting AI Engine
              </label>
              <select
                value={selectedModel}
                onChange={(event) => onModelChange(event.target.value as ModelChoice)}
                className="w-full bg-[var(--bg)] border border-[var(--border)] rounded-xl p-4 text-xs font-black outline-none focus:border-[var(--accent)]/50 transition-all cursor-pointer shadow-sm text-[var(--text)]"
              >
                {MODELS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <p className="text-[8px] text-[var(--text-muted)] leading-relaxed">
                The local engine runs entirely on this machine and needs no key, but it cannot crack
                world seeds and its accuracy is far below the cloud tiers.
              </p>
            </div>

            <div className="text-[8px] text-[var(--text-muted)] font-mono uppercase text-center mt-2 tracking-widest">
              Pinpoint OS // Core System Panel Active
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
};

export default SettingsPanel;
