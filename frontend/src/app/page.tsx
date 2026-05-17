'use client';

import React, { useState, useEffect } from 'react';
import MapComponent from '@/components/MapComponent';
import Scanner from '@/components/Scanner';
import { motion, AnimatePresence } from 'framer-motion';
import { Sun, Moon, Settings, Info, History, Map as MapIcon, Crosshair, Menu as MenuIcon, X } from 'lucide-react';

export default function Home() {
  const [scanResult, setScanResult] = useState<any>(null);
  const [isScanning, setIsScanning] = useState(false);
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const [history, setHistory] = useState<any[]>([]);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [currentMode, setCurrentMode] = useState<'real-world' | 'game'>('real-world');
  const [currentGame, setCurrentGame] = useState('Minecraft');
  
  // Settings Panel States
  const [accentColor, setAccentColor] = useState<'red' | 'blue' | 'green' | 'purple' | 'orange'>('red');
  const [mapStyle, setMapStyle] = useState<'dark' | 'light' | 'satellite'>('dark');
  const [selectedModel, setSelectedModel] = useState<string>('auto');
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isInfoOpen, setIsInfoOpen] = useState(false);

  // Navigation State: 'map' or 'scanner'
  const [view, setView] = useState<'map' | 'scanner'>('scanner');

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  // Reactive Custom Accent Stylesheet injector
  useEffect(() => {
    const root = document.documentElement;
    const colors = {
      red: { accent: '#ef4444', hover: '#dc2626' },
      blue: { accent: '#3b82f6', hover: '#2563eb' },
      green: { accent: '#10b981', hover: '#059669' },
      purple: { accent: '#8b5cf6', hover: '#7c3aed' },
      orange: { accent: '#f97316', hover: '#ea580c' },
    }[accentColor];

    root.style.setProperty('--accent', colors.accent);
    root.style.setProperty('--accent-hover', colors.hover);
  }, [accentColor]);

  const fetchHistory = async () => {
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
      const res = await fetch(`${apiUrl}/history`);
      const data = await res.json();
      setHistory(data);
    } catch (e) { console.error("History fetch error", e); }
  };

  const toggleTheme = () => setTheme(prev => prev === 'dark' ? 'light' : 'dark');

  const handleScanResult = (result: any) => {
    setScanResult(result);
    setIsScanning(false);
    fetchHistory();
    // After a successful scan, keep the results visible but the scanner will be collapsed
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    alert("Coordinates copied to clipboard! Share this with your fellow explorers.");
  };

  return (
    <main className="relative h-screen w-screen overflow-hidden text-[var(--text)] font-sans">
      
      {/* BACKGROUND LAYER: HIGH-DETAIL WORLD MAP */}
      <div className="absolute inset-0 z-0 bg-[#0a0a0b]">
        <MapComponent 
          marker={scanResult?.mode === 'real-world' ? scanResult.coordinates : undefined} 
          gameCoords={scanResult?.mode === 'game' ? scanResult.coordinates : undefined}
          seed={scanResult?.seed}
          center={scanResult?.mode === 'real-world' ? [scanResult.coordinates.lng, scanResult.coordinates.lat] : [0, 20]} 
          zoom={scanResult ? 14 : 2} 
          mode={scanResult?.mode || currentMode}
          game={scanResult?.game || currentGame}
          mapStyle={mapStyle}
        />
      </div>

      {/* NAVIGATION LAYER: COMMAND CENTER HEADER */}
      <nav className="absolute top-0 left-0 w-full z-50 p-4 md:p-6 flex justify-center pointer-events-none">
        <motion.div 
          initial={{ y: -50, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          className="pointer-events-auto flex items-center gap-1 p-1.5 bg-black/40 backdrop-blur-xl border border-white/10 rounded-2xl shadow-2xl"
        >
          <button 
            onClick={() => setView('map')}
            className={`flex items-center gap-3 px-6 py-2.5 rounded-xl text-[10px] font-black uppercase tracking-[0.2em] transition-all ${view === 'map' ? 'bg-[var(--accent)] text-white' : 'text-white/60 hover:text-white'}`}
          >
            <MapIcon className="w-4 h-4" />
            World Discovery
          </button>
          <button 
            onClick={() => setView('scanner')}
            className={`flex items-center gap-3 px-6 py-2.5 rounded-xl text-[10px] font-black uppercase tracking-[0.2em] transition-all ${view === 'scanner' ? 'bg-[var(--accent)] text-white' : 'text-white/60 hover:text-white'}`}
          >
            <Crosshair className="w-4 h-4" />
            Neural Scanner
          </button>
        </motion.div>
      </nav>

      {/* SCANNER LAYER: THE DROP-DOWN INTERFACE */}
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
            <div className={`pointer-events-auto w-full transition-all duration-700 ease-in-out ${
              isScanning ? 'max-w-md shadow-2xl rounded-2xl overflow-hidden' : 'max-w-md'
            }`}>
              <Scanner 
                onScanResult={handleScanResult} 
                onScanStart={() => setIsScanning(true)}
                onModeChange={(mode) => setCurrentMode(mode)}
                onGameChange={(game) => setCurrentGame(game)}
                isCollapsed={isScanning}
                selectedModel={selectedModel}
                currentMode={currentMode}
                currentGame={currentGame}
              />
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* RESULTS LAYER: FLOATING DATA CARD */}
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
                <h3 className="text-[10px] font-black text-[var(--accent)] uppercase tracking-[0.3em]">Discovery Confirmed</h3>
                <p className="text-[8px] text-[var(--text-muted)] font-bold uppercase mt-1">Neural Vector Logged</p>
              </div>
              <button onClick={() => setScanResult(null)} className="text-[var(--text-muted)] hover:text-red-500 transition-colors">
                <X className="w-4 h-4" />
              </button>
            </div>

            {scanResult.image && (
              <div className="w-full aspect-[16/10] rounded-xl overflow-hidden border border-[var(--border)] mb-6 shadow-inner flex-shrink-0">
                <img 
                  src={scanResult.image} 
                  alt="Scanned Scenery" 
                  className="w-full h-full object-cover" 
                />
              </div>
            )}

            <div className="flex flex-col gap-6">
                <div>
                  <p className="text-[9px] text-[var(--text-muted)] uppercase tracking-widest font-black mb-1">Target Identity</p>
                  <p className="text-xl font-black tracking-tighter italic">{scanResult.location}</p>
                </div>

                {/* Neural Confidence Indicator */}
                <div className="flex flex-col gap-2">
                  <div className="flex justify-between items-center text-[9px] text-[var(--text-muted)] uppercase tracking-widest font-black">
                    <span>Neural Confidence</span>
                    <span className="font-mono text-[var(--accent)] font-bold">{Math.round((scanResult.confidence || 0.95) * 100)}%</span>
                  </div>
                  <div className="w-full h-1.5 bg-[var(--border)] rounded-full overflow-hidden">
                    <div 
                      className="h-full bg-[var(--accent)] rounded-full transition-all duration-1000"
                      style={{ width: `${Math.round((scanResult.confidence || 0.95) * 100)}%`, boxShadow: '0 0 10px var(--accent)' }}
                    />
                  </div>
                </div>

                {/* Neural Insights Section */}
                {scanResult.insights && (
                  <div className="flex flex-wrap gap-2">
                    {scanResult.insights.map((insight: string, i: number) => (
                      <span key={i} className="px-3 py-1 bg-[var(--accent)]/10 border border-[var(--accent)]/20 rounded-lg text-[8px] font-black uppercase text-[var(--accent)] tracking-widest">
                        {insight}
                      </span>
                    ))}
                  </div>
                )}

                <div className="p-4 bg-[var(--bg)] rounded-xl border border-[var(--border)] shadow-inner">
                <p className="text-[8px] text-[var(--accent)] uppercase font-black mb-3 tracking-widest">Neural Vectors</p>
                  {scanResult.mode === 'real-world' ? (
                    <div className="flex flex-col gap-1 text-[10px] font-mono">
                      <p><span className="text-[var(--text-muted)]">LAT:</span> {scanResult.coordinates.lat?.toFixed(6)}</p>
                      <p><span className="text-[var(--text-muted)]">LNG:</span> {scanResult.coordinates.lng?.toFixed(6)}</p>
                    </div>
                  ) : (
                    <div className="flex flex-col gap-1 text-[10px] font-mono">
                      <p><span className="text-[var(--text-muted)]">X:</span> {scanResult.coordinates.x}</p>
                      <p><span className="text-[var(--text-muted)]">Y:</span> {scanResult.coordinates.y}</p>
                      <p><span className="text-[var(--text-muted)]">Z:</span> {scanResult.coordinates.z}</p>
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
                onClick={() => copyToClipboard(scanResult.seed ? scanResult.seed : `${scanResult.coordinates.lat}, ${scanResult.coordinates.lng}`)}
                className="w-full py-4 bg-[var(--accent)] text-white rounded-xl text-[9px] font-black uppercase tracking-[0.2em] shadow-lg shadow-[var(--accent)]/20"
              >
                Copy Intelligence
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* SIDEBAR: DISCOVERY VAULT */}
      <AnimatePresence>
        {isHistoryOpen && (
          <>
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setIsHistoryOpen(false)} className="absolute inset-0 bg-black/40 z-[60] backdrop-blur-sm pointer-events-auto" />
            <motion.div initial={{ x: -400 }} animate={{ x: 0 }} exit={{ x: -400 }} className="absolute top-0 left-0 h-full w-80 bg-[var(--bg)] border-r border-[var(--border)] z-[70] p-8 flex flex-col gap-8 shadow-2xl pointer-events-auto">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-black tracking-[0.3em] uppercase">Discovery Vault</h2>
                <button onClick={() => setIsHistoryOpen(false)} className="text-[var(--text-muted)] hover:text-red-500 transition-colors uppercase text-[10px] font-bold">Close</button>
              </div>
              <div className="flex-1 overflow-y-auto no-scrollbar flex flex-col gap-4">
                {history.map((item) => (
                  <div key={item.id} onClick={() => { setScanResult(item); setIsHistoryOpen(false); }} className="modern-panel p-4 hover:border-red-500/50 cursor-pointer transition-all group">
                    <p className="text-[11px] font-black truncate">{item.location}</p>
                    <p className="text-[9px] text-[var(--text-muted)] mt-1 font-mono uppercase tracking-tighter">Verified Entry #{item.id}</p>
                  </div>
                ))}
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>

      {/* UTILITY LAYER: FLOATING CONTROLS */}
      <AnimatePresence>
        {!isScanning && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="absolute bottom-8 right-8 z-20 flex gap-4 pointer-events-auto">
            <button onClick={() => { fetchHistory(); setIsHistoryOpen(true); }} className="w-10 h-10 rounded-xl modern-panel flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--accent)] transition-all shadow-xl group">
              <History className="w-5 h-5 group-hover:scale-110" />
            </button>
            <button onClick={toggleTheme} className="w-10 h-10 rounded-xl modern-panel flex items-center justify-center text-[var(--text-muted)] hover:text-white transition-all shadow-xl">
              {theme === 'dark' ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}
            </button>
            <button onClick={() => setIsSettingsOpen(true)} className="w-10 h-10 rounded-xl modern-panel flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--accent)] transition-all shadow-xl">
              <Settings className="w-5 h-5" />
            </button>
            <button onClick={() => setIsInfoOpen(true)} className="w-10 h-10 rounded-xl modern-panel flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--accent)] transition-all shadow-xl">
              <Info className="w-5 h-5" />
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* SETTINGS OVERLAY: COMMAND DRAWER */}
      <AnimatePresence>
        {isSettingsOpen && (
          <>
            <motion.div 
              initial={{ opacity: 0 }} 
              animate={{ opacity: 1 }} 
              exit={{ opacity: 0 }} 
              onClick={() => setIsSettingsOpen(false)} 
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
                  <Settings className="w-5 h-5" />
                  <h2 className="text-xs font-black uppercase tracking-[0.3em]">System Control Panel</h2>
                </div>
                <button onClick={() => setIsSettingsOpen(false)} className="text-[var(--text-muted)] hover:text-red-500">
                  <X className="w-4 h-4" />
                </button>
              </div>

              {/* Accent Color Selection */}
              <div className="flex flex-col gap-3">
                <label className="text-[9px] text-[var(--text-muted)] uppercase tracking-widest font-black">Interface Accent Spectrum</label>
                <div className="flex gap-3">
                  {(['red', 'blue', 'green', 'purple', 'orange'] as const).map((color) => {
                    const bgColors = { red: 'bg-red-500', blue: 'bg-blue-500', green: 'bg-emerald-500', purple: 'bg-violet-500', orange: 'bg-orange-500' }[color];
                    return (
                      <button 
                        key={color} 
                        onClick={() => setAccentColor(color)}
                        className={`w-8 h-8 rounded-full ${bgColors} transition-all flex items-center justify-center border-2 ${accentColor === color ? 'border-white scale-110 shadow-lg shadow-black/20' : 'border-transparent opacity-60 hover:opacity-100 hover:scale-105'}`}
                      />
                    );
                  })}
                </div>
              </div>

              {/* Map Style Selector */}
              <div className="flex flex-col gap-3">
                <label className="text-[9px] text-[var(--text-muted)] uppercase tracking-widest font-black">Map Vision Mode</label>
                <div className="grid grid-cols-3 gap-2 bg-[var(--bg)] p-1 rounded-xl border border-[var(--border)]">
                  {(['dark', 'light', 'satellite'] as const).map((style) => (
                    <button
                      key={style}
                      onClick={() => setMapStyle(style)}
                      className={`py-2 text-[8px] font-black uppercase tracking-widest rounded-lg transition-all ${mapStyle === style ? 'bg-[var(--accent)] text-white shadow-sm' : 'text-[var(--text-muted)] hover:text-[var(--text)]'}`}
                    >
                      {style}
                    </button>
                  ))}
                </div>
              </div>

              {/* Specific AI Model Selection */}
              <div className="flex flex-col gap-3">
                <label className="text-[9px] text-[var(--text-muted)] uppercase tracking-widest font-black">Targeting AI Engine</label>
                <select
                  value={selectedModel}
                  onChange={(e) => setSelectedModel(e.target.value)}
                  className="w-full bg-[var(--bg)] border border-[var(--border)] rounded-xl p-4 text-xs font-black outline-none focus:border-[var(--accent)]/50 transition-all cursor-pointer shadow-sm text-[var(--text)]"
                >
                  <option value="auto">Automatic</option>
                  <option value="groq-only">Groq-Only</option>
                  <option value="gemini-only">Gemini-Only</option>
                  <option value="github-only">Github-Only</option>
                  <option value="local-only">Local AI Engine</option>
                </select>
              </div>

              <div className="text-[8px] text-[var(--text-muted)] font-mono uppercase text-center mt-2 tracking-widest">
                Pinpoint OS // Core System Panel Active
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>

      {/* INFO & CREDITS OVERLAY */}
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
                  <h2 className="text-xs font-black uppercase tracking-[0.3em]">System Specifications & Credits</h2>
                </div>
                <button onClick={() => setIsInfoOpen(false)} className="text-[var(--text-muted)] hover:text-red-500">
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="flex flex-col gap-5 text-[10px]">
                {/* Core Operator */}
                <div className="flex justify-between items-center bg-[var(--bg)] p-3 rounded-xl border border-[var(--border)]">
                  <span className="text-[var(--text-muted)] font-black uppercase tracking-wider">Pinpoint Developer</span>
                  <span className="font-mono font-black text-[var(--accent)] tracking-widest uppercase">velo4705</span>
                </div>

                {/* AI Alliance */}
                <div className="flex flex-col gap-2">
                  <label className="text-[8px] text-[var(--text-muted)] uppercase tracking-widest font-black">Neural Core Providers</label>
                  <div className="bg-[var(--bg)] p-4 rounded-xl border border-[var(--border)] flex flex-col gap-3 font-mono">
                    <div className="flex justify-between"><span className="text-[var(--text-muted)]">Gemini Fleet:</span> <span className="font-bold">Google DeepMind</span></div>
                    <div className="flex justify-between"><span className="text-[var(--text-muted)]">LLaMA 4 Scout:</span> <span className="font-bold">Groq Alliance</span></div>
                    <div className="flex justify-between"><span className="text-[var(--text-muted)]">GPT Cloud:</span> <span className="font-bold">GitHub Azure Hub</span></div>
                    <div className="flex justify-between"><span className="text-[var(--text-muted)]">Local Clipper:</span> <span className="font-bold">Airgapped CLIP Node</span></div>
                  </div>
                </div>

                {/* Mapping */}
                <div className="flex flex-col gap-2">
                  <label className="text-[8px] text-[var(--text-muted)] uppercase tracking-widest font-black">Geospatial Intelligence</label>
                  <div className="bg-[var(--bg)] p-4 rounded-xl border border-[var(--border)] flex flex-col gap-3 font-mono">
                    <div className="flex justify-between"><span className="text-[var(--text-muted)]">Satellite Layer:</span> <span className="font-bold">Esri Imagery</span></div>
                    <div className="flex justify-between"><span className="text-[var(--text-muted)]">Vector Basemap:</span> <span className="font-bold">CartoDB & OpenStreetMap</span></div>
                    <div className="flex justify-between"><span className="text-[var(--text-muted)]">Mapping SDK:</span> <span className="font-bold">MapLibre GL</span></div>
                  </div>
                </div>

                {/* Frameworks */}
                <div className="flex flex-col gap-2">
                  <label className="text-[8px] text-[var(--text-muted)] uppercase tracking-widest font-black">System Architecture</label>
                  <div className="bg-[var(--bg)] p-4 rounded-xl border border-[var(--border)] flex flex-col gap-3 font-mono">
                    <div className="flex justify-between"><span className="text-[var(--text-muted)]">Client Core:</span> <span className="font-bold">Next.js & Framer Motion</span></div>
                    <div className="flex justify-between"><span className="text(--text-muted)">Server Engine:</span> <span className="font-bold">FastAPI & Uvicorn</span></div>
                    <div className="flex justify-between"><span className="text-[var(--text-muted)]">Intelligence Vault:</span> <span className="font-bold">Upstash Serverless Redis</span></div>
                  </div>
                </div>
              </div>

              <div className="text-[8px] text-[var(--text-muted)] font-mono uppercase text-center tracking-widest border-t border-[var(--border)] pt-4 mt-2">
                Project Pinpoint // Operators Console v1.0
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>

    </main>
  );
}
