'use client';

import React, { useState, useEffect } from 'react';
import Image from 'next/image';
import MapComponent from '@/components/MapComponent';
import Scanner from '@/components/Scanner';
import SettingsPanel from '@/components/SettingsPanel';
import { motion, AnimatePresence } from 'framer-motion';
import { Sun, Moon, Settings, Info, History, Map as MapIcon, Crosshair, X } from 'lucide-react';
import { fetchHistory } from '@/lib/api';
import { useByok } from '@/lib/useByok';
import type {
  AccentColor,
  MapStyle,
  ModelChoice,
  ProviderSlug,
  ScanMode,
  ScanResult,
  VaultEntry,
} from '@/lib/types';

const ACCENT_VALUES: Record<AccentColor, { accent: string; hover: string }> = {
  red: { accent: '#ef4444', hover: '#dc2626' },
  blue: { accent: '#3b82f6', hover: '#2563eb' },
  green: { accent: '#10b981', hover: '#059669' },
  purple: { accent: '#8b5cf6', hover: '#7c3aed' },
  orange: { accent: '#f97316', hover: '#ea580c' },
};

export default function Home() {
  const [scanResult, setScanResult] = useState<ScanResult | null>(null);
  const [isScanning, setIsScanning] = useState(false);
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const [history, setHistory] = useState<VaultEntry[]>([]);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [currentMode, setCurrentMode] = useState<ScanMode>('real-world');
  const [currentGame, setCurrentGame] = useState('Minecraft');

  const [accentColor, setAccentColor] = useState<AccentColor>('red');
  const [mapStyle, setMapStyle] = useState<MapStyle>('dark');
  const [selectedModel, setSelectedModel] = useState<ModelChoice>('auto');
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isInfoOpen, setIsInfoOpen] = useState(false);

  const [view, setView] = useState<'map' | 'scanner'>('scanner');

  const byok = useByok();

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  useEffect(() => {
    const root = document.documentElement;
    const colors = ACCENT_VALUES[accentColor];
    root.style.setProperty('--accent', colors.accent);
    root.style.setProperty('--accent-hover', colors.hover);
  }, [accentColor]);

  const loadHistory = async () => {
    try {
      setHistory(await fetchHistory());
    } catch (error) {
      console.error('History fetch error', error);
    }
  };

  const toggleTheme = () => setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'));

  const handleScanResult = (result: ScanResult | null) => {
    setScanResult(result);
    setIsScanning(false);
    if (result) void loadHistory();
  };

  const copyToClipboard = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setScanResult((previous) =>
        previous ? { ...previous, insights: [...(previous.insights ?? []), 'Copied to clipboard'] } : previous,
      );
    } catch {
      console.error('Clipboard write failed');
    }
  };

  const mapCenter: [number, number] =
    scanResult?.mode === 'real-world' &&
    scanResult.coordinates.lat !== undefined &&
    scanResult.coordinates.lng !== undefined
      ? [scanResult.coordinates.lng, scanResult.coordinates.lat]
      : [0, 20];

  const confidence = Math.round((scanResult?.confidence ?? 0) * 100);

  const copyTarget = scanResult
    ? scanResult.seed ||
      (scanResult.coordinates.lat !== undefined && scanResult.coordinates.lng !== undefined
        ? `${scanResult.coordinates.lat}, ${scanResult.coordinates.lng}`
        : scanResult.location)
    : '';

  return (
    <main className="relative h-screen w-screen overflow-hidden text-[var(--text)] font-sans">
      {/* Background map */}
      <div className="absolute inset-0 z-0 bg-[#0a0a0b]">
        <MapComponent
          marker={
            scanResult?.mode === 'real-world' &&
            scanResult.coordinates.lat !== undefined &&
            scanResult.coordinates.lng !== undefined
              ? { lat: scanResult.coordinates.lat, lng: scanResult.coordinates.lng }
              : undefined
          }
          gameCoords={
            scanResult?.mode === 'game' && scanResult.coordinates.x !== undefined
              ? {
                  x: scanResult.coordinates.x,
                  y: scanResult.coordinates.y ?? 0,
                  z: scanResult.coordinates.z ?? 0,
                }
              : undefined
          }
          seed={scanResult?.seed}
          center={mapCenter}
          zoom={scanResult ? 14 : 2}
          mode={scanResult?.mode ?? currentMode}
          game={scanResult?.game ?? currentGame}
          mapStyle={mapStyle}
        />
      </div>

      {/* Header */}
      <nav className="absolute top-0 left-0 w-full z-50 p-4 md:p-6 flex justify-center pointer-events-none">
        <motion.div
          initial={{ y: -50, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          className="pointer-events-auto flex items-center gap-1 p-1.5 bg-black/40 backdrop-blur-xl border border-white/10 rounded-2xl shadow-2xl"
        >
          <button
            onClick={() => setView('map')}
            className={`flex items-center gap-3 px-6 py-2.5 rounded-xl text-[10px] font-black uppercase tracking-[0.2em] transition-all ${
              view === 'map'
                ? 'bg-[var(--accent)] text-white'
                : 'text-white/60 hover:text-white'
            }`}
          >
            <MapIcon className="w-4 h-4" />
            World Discovery
          </button>
          <button
            onClick={() => setView('scanner')}
            className={`flex items-center gap-3 px-6 py-2.5 rounded-xl text-[10px] font-black uppercase tracking-[0.2em] transition-all ${
              view === 'scanner'
                ? 'bg-[var(--accent)] text-white'
                : 'text-white/60 hover:text-white'
            }`}
          >
            <Crosshair className="w-4 h-4" />
            Neural Scanner
          </button>
        </motion.div>
      </nav>

      {/* Scanner */}
      <AnimatePresence>
        {view === 'scanner' && !scanResult && (
          <motion.div
            initial={{ opacity: 0, x: -50 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -50 }}
            className={`absolute z-30 pointer-events-none transition-all duration-700 ease-in-out ${
              isScanning
                ? 'inset-0 flex items-center justify-center p-4'
                : 'top-8 md:top-12 left-4 md:left-12 bottom-8 max-h-[90vh] overflow-y-auto flex flex-col justify-start'
            }`}
          >
            <div
              className={`pointer-events-auto w-full transition-all duration-700 ease-in-out ${
                isScanning ? 'max-w-md shadow-2xl rounded-2xl overflow-hidden' : 'max-w-md'
              }`}
            >
              <Scanner
                onScanResult={handleScanResult}
                onScanStart={() => setIsScanning(true)}
                onModeChange={setCurrentMode}
                onGameChange={setCurrentGame}
                isCollapsed={isScanning}
                selectedModel={selectedModel}
                currentMode={currentMode}
                currentGame={currentGame}
                byok={byok.keys}
              />
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Result card */}
      <AnimatePresence>
        {scanResult && !isScanning && (
          <motion.div
            initial={{ opacity: 0, x: 50 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 50 }}
            className="absolute top-1/2 right-4 md:right-12 -translate-y-1/2 w-72 md:w-80 max-h-[80vh] overflow-y-auto modern-panel p-6 md:p-8 border-r-4 border-r-[var(--accent)] z-40 shadow-2xl"
          >
            <div className="flex items-center justify-between mb-6">
              <div className="flex flex-col">
                <h3 className="text-[10px] font-black text-[var(--accent)] uppercase tracking-[0.3em]">
                  Discovery Confirmed
                </h3>
                <p className="text-[8px] text-[var(--text-muted)] font-bold uppercase mt-1">
                  Neural Vector Logged
                </p>
              </div>
              <button
                onClick={() => setScanResult(null)}
                aria-label="Dismiss result"
                className="text-[var(--text-muted)] hover:text-red-500 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {scanResult.image && (
              <div className="w-full aspect-[16/10] rounded-xl overflow-hidden border border-[var(--border)] mb-6 shadow-inner flex-shrink-0 relative">
                <Image
                  src={scanResult.image}
                  alt="Scanned imagery"
                  fill
                  unoptimized
                  sizes="(max-width: 768px) 288px, 320px"
                  className="object-cover"
                />
              </div>
            )}

            <div className="flex flex-col gap-6">
              <div>
                <p className="text-[9px] text-[var(--text-muted)] uppercase tracking-widest font-black mb-1">
                  Target Identity
                </p>
                <p className="text-xl font-black tracking-tighter italic">{scanResult.location}</p>
              </div>

              <div className="flex flex-col gap-2">
                <div className="flex justify-between items-center text-[9px] text-[var(--text-muted)] uppercase tracking-widest font-black">
                  <span>Neural Confidence</span>
                  <span className="font-mono text-[var(--accent)] font-bold">{confidence}%</span>
                </div>
                <div className="w-full h-1.5 bg-[var(--border)] rounded-full overflow-hidden">
                  <div
                    className="h-full bg-[var(--accent)] rounded-full transition-all duration-1000"
                    style={{
                      width: `${confidence}%`,
                      boxShadow: '0 0 10px var(--accent)',
                    }}
                  />
                </div>
              </div>

              {scanResult.insights && scanResult.insights.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {scanResult.insights.map((insight: string, index: number) => (
                    <span
                      key={`${insight}-${index}`}
                      className="px-3 py-1 bg-[var(--accent)]/10 border border-[var(--accent)]/20 rounded-lg text-[8px] font-black uppercase text-[var(--accent)] tracking-widest"
                    >
                      {insight}
                    </span>
                  ))}
                </div>
              )}

              <div className="p-4 bg-[var(--bg)] rounded-xl border border-[var(--border)] shadow-inner">
                <p className="text-[8px] text-[var(--accent)] uppercase font-black mb-3 tracking-widest">
                  Neural Vectors
                </p>
                {scanResult.mode === 'real-world' ? (
                  <div className="flex flex-col gap-1 text-[10px] font-mono">
                    <p>
                      <span className="text-[var(--text-muted)]">LAT:</span>{' '}
                      {scanResult.coordinates.lat?.toFixed(6)}
                    </p>
                    <p>
                      <span className="text-[var(--text-muted)]">LNG:</span>{' '}
                      {scanResult.coordinates.lng?.toFixed(6)}
                    </p>
                  </div>
                ) : (
                  <div className="flex flex-col gap-1 text-[10px] font-mono">
                    <p>
                      <span className="text-[var(--text-muted)]">X:</span> {scanResult.coordinates.x}
                    </p>
                    <p>
                      <span className="text-[var(--text-muted)]">Y:</span> {scanResult.coordinates.y}
                    </p>
                    <p>
                      <span className="text-[var(--text-muted)]">Z:</span> {scanResult.coordinates.z}
                    </p>
                  </div>
                )}
              </div>

              {scanResult.seed && (
                <div className="p-4 bg-[var(--accent)]/5 rounded-xl border border-[var(--accent)]/20">
                  <p className="text-[8px] text-[var(--accent)] uppercase font-black mb-1">World Seed</p>
                  <p className="text-[10px] font-mono truncate">{scanResult.seed}</p>
                </div>
              )}

              <button
                onClick={() => void copyToClipboard(copyTarget)}
                className="w-full py-4 bg-[var(--accent)] text-white rounded-xl text-[9px] font-black uppercase tracking-[0.2em] shadow-lg shadow-[var(--accent)]/20"
              >
                Copy Intelligence
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Discovery vault */}
      <AnimatePresence>
        {isHistoryOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setIsHistoryOpen(false)}
              className="absolute inset-0 bg-black/40 z-[60] backdrop-blur-sm pointer-events-auto"
            />
            <motion.div
              initial={{ x: -400 }}
              animate={{ x: 0 }}
              exit={{ x: -400 }}
              className="absolute top-0 left-0 h-full w-80 bg-[var(--bg)] border-r border-[var(--border)] z-[70] p-8 flex flex-col gap-8 shadow-2xl pointer-events-auto"
            >
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-black tracking-[0.3em] uppercase">Discovery Vault</h2>
                <button
                  onClick={() => setIsHistoryOpen(false)}
                  className="text-[var(--text-muted)] hover:text-red-500 transition-colors uppercase text-[10px] font-bold"
                >
                  Close
                </button>
              </div>
              <div className="flex-1 overflow-y-auto no-scrollbar flex flex-col gap-4">
                {history.length === 0 && (
                  <p className="text-[10px] text-[var(--text-muted)] leading-relaxed">
                    No discoveries yet. The vault lives in the API process and is cleared when it
                    restarts.
                  </p>
                )}
                {history.map((item) => (
                  <div
                    key={item.id}
                    onClick={() => {
                      setScanResult({
                        location: item.location ?? 'Unknown',
                        coordinates: item.coordinates ?? {},
                        confidence: item.confidence ?? 0,
                        source: item.source,
                        tier: item.tier,
                        mode: item.mode ?? 'real-world',
                        game: item.game,
                        seed: item.seed,
                      });
                      setIsHistoryOpen(false);
                    }}
                    className="modern-panel p-4 hover:border-[var(--accent)]/50 cursor-pointer transition-all group"
                  >
                    <p className="text-[11px] font-black truncate">{item.location}</p>
                    <p className="text-[9px] text-[var(--text-muted)] mt-1 font-mono uppercase tracking-tighter">
                      Verified Entry #{item.id}
                    </p>
                  </div>
                ))}
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>

      {/* Utility controls */}
      <AnimatePresence>
        {!isScanning && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="absolute bottom-8 right-8 z-20 flex gap-4 pointer-events-auto"
          >
            <button
              onClick={() => {
                void loadHistory();
                setIsHistoryOpen(true);
              }}
              aria-label="Open discovery vault"
              className="w-10 h-10 rounded-xl modern-panel flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--accent)] transition-all shadow-xl group"
            >
              <History className="w-5 h-5 group-hover:scale-110" />
            </button>
            <button
              onClick={toggleTheme}
              aria-label="Toggle theme"
              className="w-10 h-10 rounded-xl modern-panel flex items-center justify-center text-[var(--text-muted)] hover:text-white transition-all shadow-xl"
            >
              {theme === 'dark' ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}
            </button>
            <button
              onClick={() => setIsSettingsOpen(true)}
              aria-label="Open settings"
              className="w-10 h-10 rounded-xl modern-panel flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--accent)] transition-all shadow-xl"
            >
              <Settings />
            </button>
            <button
              onClick={() => setIsInfoOpen(true)}
              aria-label="Open system information"
              className="w-10 h-10 rounded-xl modern-panel flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--accent)] transition-all shadow-xl"
            >
              <Info className="w-5 h-5" />
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      <SettingsPanel
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        accentColor={accentColor}
        onAccentChange={setAccentColor}
        mapStyle={mapStyle}
        onMapStyleChange={setMapStyle}
        selectedModel={selectedModel}
        onModelChange={setSelectedModel}
        byok={byok.keys}
        onByokChange={(slug: ProviderSlug, value: string) => byok.setKey(slug, value)}
        rememberKeys={byok.remember}
        onRememberChange={byok.setRemember}
        onClearKeys={byok.clear}
      />

      {/* Info overlay */}
      <AnimatePresence>
        {isInfoOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setIsInfoOpen(false)}
              className="absolute inset-0 bg-black/60 z-[80] backdrop-blur-md pointer-events-auto"
            />
            <motion.div
              initial={{ scale: 0.95, opacity: 0, y: 20 }}
              animate={{ scale: 1, opacity: 1, y: 0 }}
              exit={{ scale: 0.95, opacity: 0, y: 20 }}
              className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-md max-h-[80vh] overflow-y-auto modern-panel p-8 z-[90] pointer-events-auto flex flex-col gap-6"
            >
              <div className="flex items-center justify-between border-b border-[var(--border)] pb-4">
                <div className="flex items-center gap-2 text-[var(--accent)]">
                  <Info className="w-5 h-5" />
                  <h2 className="text-xs font-black uppercase tracking-[0.3em]">
                    System Specifications & Credits
                  </h2>
                </div>
                <button
                  onClick={() => setIsInfoOpen(false)}
                  aria-label="Close system information"
                  className="text-[var(--text-muted)] hover:text-red-500"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="flex flex-col gap-5 text-[10px]">
                <div className="flex justify-between items-center bg-[var(--bg)] p-3 rounded-xl border border-[var(--border)]">
                  <span className="text-[var(--text-muted)] font-black uppercase tracking-wider">
                    Pinpoint Developer
                  </span>
                  <span className="font-mono font-black text-[var(--accent)] tracking-widest uppercase">
                    velo4705
                  </span>
                </div>

                <div className="flex flex-col gap-2">
                  <label className="text-[8px] text-[var(--text-muted)] uppercase tracking-widest font-black">
                    Neural Core Providers
                  </label>
                  <div className="bg-[var(--bg)] p-4 rounded-xl border border-[var(--border)] flex flex-col gap-3 font-mono">
                    <div className="flex justify-between">
                      <span className="text-[var(--text-muted)]">Gemini Fleet:</span>{' '}
                      <span className="font-bold">Google DeepMind</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-[var(--text-muted)]">Qwen Vision:</span>{' '}
                      <span className="font-bold">Groq Alliance</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-[var(--text-muted)]">GPT Cloud:</span>{' '}
                      <span className="font-bold">OpenAI</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-[var(--text-muted)]">Local Clipper:</span>{' '}
                      <span className="font-bold">Airgapped CLIP Node</span>
                    </div>
                  </div>
                </div>

                <div className="flex flex-col gap-2">
                  <label className="text-[8px] text-[var(--text-muted)] uppercase tracking-widest font-black">
                    Geospatial Intelligence
                  </label>
                  <div className="bg-[var(--bg)] p-4 rounded-xl border border-[var(--border)] flex flex-col gap-3 font-mono">
                    <div className="flex justify-between">
                      <span className="text-[var(--text-muted)]">Satellite Layer:</span>{' '}
                      <span className="font-bold">Esri Imagery</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-[var(--text-muted)]">Vector Basemap:</span>{' '}
                      <span className="font-bold">CartoDB & OpenStreetMap</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-[var(--text-muted)]">Mapping SDK:</span>{' '}
                      <span className="font-bold">MapLibre GL</span>
                    </div>
                  </div>
                </div>

                <div className="flex flex-col gap-2">
                  <label className="text-[8px] text-[var(--text-muted)] uppercase tracking-widest font-black">
                    System Architecture
                  </label>
                  <div className="bg-[var(--bg)] p-4 rounded-xl border border-[var(--border)] flex flex-col gap-3 font-mono">
                    <div className="flex justify-between">
                      <span className="text-[var(--text-muted)]">Client Core:</span>{' '}
                      <span className="font-bold">Next.js & Framer Motion</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-[var(--text-muted)]">Server Engine:</span>{' '}
                      <span className="font-bold">FastAPI & Uvicorn</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-[var(--text-muted)]">Intelligence Vault:</span>{' '}
                      <span className="font-bold">Upstash Serverless Redis</span>
                    </div>
                  </div>
                </div>
              </div>

              <div className="text-[8px] text-[var(--text-muted)] font-mono uppercase text-center tracking-widest border-t border-[var(--border)] pt-4 mt-2">
                Project Pinpoint // Operators Console v2.0
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </main>
  );
}
