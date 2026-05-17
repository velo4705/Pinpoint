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
  
  // Navigation State: 'map' or 'scanner'
  const [view, setView] = useState<'map' | 'scanner'>('scanner');

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

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
            className={`flex items-center gap-3 px-6 py-2.5 rounded-xl text-[10px] font-black uppercase tracking-[0.2em] transition-all ${view === 'map' ? 'bg-blue-600 text-white' : 'text-white/60 hover:text-white'}`}
          >
            <MapIcon className="w-4 h-4" />
            World Discovery
          </button>
          <button 
            onClick={() => setView('scanner')}
            className={`flex items-center gap-3 px-6 py-2.5 rounded-xl text-[10px] font-black uppercase tracking-[0.2em] transition-all ${view === 'scanner' ? 'bg-blue-600 text-white' : 'text-white/60 hover:text-white'}`}
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
            initial={{ opacity: 0, scale: 0.9, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.9, y: 20 }}
            className="absolute inset-0 flex items-center justify-center p-4 md:p-8 z-30 pointer-events-none"
          >
            <div className="pointer-events-auto w-full max-w-xl">
              <Scanner 
                onScanResult={handleScanResult} 
                onScanStart={() => setIsScanning(true)}
                onModeChange={(mode) => setCurrentMode(mode)}
                onGameChange={(game) => setCurrentGame(game)}
                isCollapsed={isScanning}
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
            className="absolute top-1/2 right-4 md:right-12 -translate-y-1/2 w-72 md:w-80 modern-panel p-6 md:p-8 border-r-4 border-r-blue-500 z-40 shadow-2xl"
          >
            <div className="flex items-center justify-between mb-8">
              <div className="flex flex-col">
                <h3 className="text-[10px] font-black text-blue-500 uppercase tracking-[0.3em]">Discovery Confirmed</h3>
                <p className="text-[8px] text-[var(--text-muted)] font-bold uppercase mt-1">Neural Vector Logged</p>
              </div>
              <button onClick={() => setScanResult(null)} className="text-[var(--text-muted)] hover:text-red-500 transition-colors">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex flex-col gap-6">
                <div>
                  <p className="text-[9px] text-[var(--text-muted)] uppercase tracking-widest font-black mb-1">Target Identity</p>
                  <p className="text-xl font-black tracking-tighter italic">{scanResult.location}</p>
                </div>

                {/* Neural Insights Section */}
                {scanResult.insights && (
                  <div className="flex flex-wrap gap-2">
                    {scanResult.insights.map((insight: string, i: number) => (
                      <span key={i} className="px-3 py-1 bg-blue-600/10 border border-blue-500/20 rounded-lg text-[8px] font-black uppercase text-blue-500 tracking-widest">
                        {insight}
                      </span>
                    ))}
                  </div>
                )}

                <div className="p-4 bg-[var(--bg)] rounded-xl border border-[var(--border)] shadow-inner">
                <p className="text-[8px] text-blue-500 uppercase font-black mb-3 tracking-widest">Neural Vectors</p>
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
                <div className="p-4 bg-blue-600/5 rounded-xl border border-blue-500/20">
                  <p className="text-[8px] text-blue-500 uppercase font-black mb-1">World Seed</p>
                  <p className="text-[10px] font-mono truncate">{scanResult.seed}</p>
                </div>
              )}

              <button 
                onClick={() => copyToClipboard(scanResult.seed ? scanResult.seed : `${scanResult.coordinates.lat}, ${scanResult.coordinates.lng}`)}
                className="w-full py-4 bg-blue-600 text-white rounded-xl text-[9px] font-black uppercase tracking-[0.2em] shadow-lg shadow-blue-500/20"
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
                  <div key={item.id} onClick={() => { setScanResult(item); setIsHistoryOpen(false); }} className="modern-panel p-4 hover:border-blue-500/50 cursor-pointer transition-all group">
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
            <button onClick={() => { fetchHistory(); setIsHistoryOpen(true); }} className="w-10 h-10 rounded-xl modern-panel flex items-center justify-center text-[var(--text-muted)] hover:text-blue-500 transition-all shadow-xl group">
              <History className="w-5 h-5 group-hover:scale-110" />
            </button>
            <button onClick={toggleTheme} className="w-10 h-10 rounded-xl modern-panel flex items-center justify-center text-[var(--text-muted)] hover:text-white transition-all shadow-xl">
              {theme === 'dark' ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}
            </button>
            <button className="w-10 h-10 rounded-xl modern-panel flex items-center justify-center text-[var(--text-muted)] hover:text-white transition-all shadow-xl">
              <Settings className="w-5 h-5" />
            </button>
          </motion.div>
        )}
      </AnimatePresence>

    </main>
  );
}
