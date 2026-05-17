'use client';

import React, { useState, useRef, useEffect } from 'react';
import { Upload, Scan, Globe, Gamepad2, X, MapPin, Loader2, Layers } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import axios from 'axios';

interface ScannerProps {
  onScanResult: (result: any) => void;
  onScanStart?: () => void;
  onModeChange?: (mode: 'real-world' | 'game') => void;
  onGameChange?: (game: string) => void;
  isCollapsed?: boolean;
  selectedModel?: string;
  currentMode?: 'real-world' | 'game';
  currentGame?: string;
}

const Scanner: React.FC<ScannerProps> = ({ 
  onScanResult, 
  onScanStart, 
  onModeChange, 
  onGameChange, 
  isCollapsed, 
  selectedModel = 'auto',
  currentMode = 'real-world',
  currentGame = 'Minecraft'
}) => {
  const [isScanning, setIsScanning] = useState(false);
  const [selectedImage, setSelectedImage] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [mode, setMode] = useState<'real-world' | 'game'>(currentMode);
  const [selectedGame, setSelectedGame] = useState(currentGame);
  const [scanTime, setScanTime] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleImageUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setSelectedFile(file);
      const reader = new FileReader();
      reader.onload = (event) => {
        setSelectedImage(event.target?.result as string);
      };
      reader.readAsDataURL(file);
    }
  };

  const startScan = async () => {
    if (!selectedFile) return;
    
    setIsScanning(true);
    setScanTime(0);
    onScanStart?.();

    // Start High-Precision Timer
    const startTime = Date.now();
    const timerInterval = setInterval(() => {
      setScanTime((Date.now() - startTime) / 1000);
    }, 100);

    try {
      const formData = new FormData();
      formData.append('file', selectedFile);
      formData.append('mode', mode);
      formData.append('model', selectedModel);
      if (mode === 'game') formData.append('game', selectedGame);

      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
      const response = await axios.post(`${apiUrl}/scan`, formData);
      const data = response.data;
      clearInterval(timerInterval);
      setIsScanning(false);

      if (data.error) {
        alert(`Neural Scan Error: ${data.error}`);
        onScanResult(null);
        return;
      }
      
      // Map result to frontend structure
      onScanResult({
        coordinates: mode === 'real-world' ? { lat: data.coordinates.lat, lng: data.coordinates.lng } : { x: data.coordinates.x, y: data.coordinates.y, z: data.coordinates.z },
        location: data.location,
        confidence: data.confidence,
        mode: mode,
        game: data.game,
        seed: data.seed,
        version: data.version,
        type: data.type,
        image: selectedImage
      });
    } catch (error) {
      console.error("Scan failed:", error);
      clearInterval(timerInterval);
      setIsScanning(false);
      alert("Neural link failed. Ensure the AI engine is running.");
    }
  };

  if (isCollapsed) {
    const getStatusText = () => {
      if (mode === 'game' && selectedGame === 'Minecraft') {
        if (scanTime < 2) return 'INITIALIZING SEED-CRACKER';
        if (scanTime < 5) return 'ANALYZING BIOME DNA & BLOCKS';
        if (scanTime < 10) return 'CRACKING WORLD SEED VECTORS';
        return 'FINALIZING SEED-DNA';
      }
      if (scanTime < 3) return 'ANALYZING FOLIAGE & LEAF DNA';
      if (scanTime < 6) return 'MAPPING REGIONAL IDENTITY';
      if (scanTime < 9) return 'IDENTIFYING ICONIC LANDMARKS';
      return 'SYNTHESIZING NEURAL VECTORS';
    };

    return (
      <div className="w-full modern-panel p-4 px-6 flex items-center justify-between shadow-2xl border-[var(--accent)] bg-[var(--accent)]/5 relative overflow-hidden">
        <div className="absolute top-0 left-0 w-1 h-full bg-[var(--accent)]" />
        
        <div className="flex items-center gap-4">
          <div className="w-10 h-10 rounded-xl bg-[var(--accent)] flex items-center justify-center shadow-lg shadow-[var(--accent)]/20">
            <Loader2 className="w-5 h-5 text-white animate-spin" />
          </div>
          <div className="flex flex-col">
            <span className="text-[10px] font-black tracking-[0.2em] uppercase text-[var(--accent)] animate-pulse">
              {getStatusText()}
            </span>
            <span className="text-[8px] text-[var(--text-muted)] font-bold uppercase tracking-widest mt-1 italic">
              Neural Helper is calculating...
            </span>
          </div>
        </div>

        <div className="flex flex-col items-end">
          <span className="text-xl font-mono font-black text-[var(--accent)] tabular-nums">
            {scanTime.toFixed(1)}<span className="text-[10px] ml-1">S</span>
          </span>
          <span className="text-[8px] font-black uppercase tracking-tighter text-[var(--text-muted)]">Elapsed Time</span>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full max-w-xl modern-panel flex flex-col max-h-[85vh] transition-all duration-500 overflow-hidden">
      <div className="flex flex-col gap-4 sm:flex-row sm:justify-between sm:items-center border-b border-[var(--border)] p-5 md:p-6 flex-shrink-0">
        <div className="flex flex-col">
          <h2 className="text-sm font-black flex items-center gap-2 tracking-[0.2em]">
            <Scan className="w-4 h-4 text-[var(--accent)]" />
            IDENTIFIER
          </h2>
          <span className="text-[9px] text-[var(--text-muted)] font-bold uppercase tracking-widest mt-1">Core Engine v1.0</span>
        </div>
        <div className="flex bg-[var(--bg)] rounded-lg p-1.5 border border-[var(--border)]">
          <button 
            onClick={() => { setMode('real-world'); onModeChange?.('real-world'); }}
            className={`px-4 py-1.5 rounded-md text-[10px] font-black tracking-wider uppercase transition-all ${mode === 'real-world' ? 'bg-[var(--accent)] text-white shadow-sm' : 'text-[var(--text-muted)] hover:text-[var(--text)]'}`}
          >
            Real World
          </button>
          <button 
            onClick={() => { setMode('game'); onModeChange?.('game'); }}
            className={`px-4 py-1.5 rounded-md text-[10px] font-black tracking-wider uppercase transition-all ${mode === 'game' ? 'bg-[var(--accent)] text-white shadow-sm' : 'text-[var(--text-muted)] hover:text-[var(--text)]'}`}
          >
            Gaming
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6 md:p-8 flex flex-col gap-6 md:gap-8 no-scrollbar">
        <div 
          onClick={() => !isScanning && fileInputRef.current?.click()}
          className={`relative aspect-[16/10] w-full rounded-2xl border flex flex-col items-center justify-center cursor-pointer transition-all duration-500 group flex-shrink-0 ${selectedImage ? 'border-[var(--accent)]/30 bg-[var(--accent)]/5' : 'border-[var(--border)] hover:border-[var(--accent)]/50 hover:bg-[var(--bg)] shadow-sm'}`}
        >
          <input 
            type="file" 
            ref={fileInputRef} 
            className="hidden" 
            accept="image/*" 
            onChange={handleImageUpload} 
          />
          
          <AnimatePresence mode="wait">
            {selectedImage ? (
              <motion.div 
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                className="absolute inset-0 p-3"
              >
                <img src={selectedImage} alt="Selected" className="w-full h-full object-cover rounded-xl" />
                {!isScanning && (
                  <button 
                    onClick={(e) => { e.stopPropagation(); setSelectedImage(null); setSelectedFile(null); }}
                    className="absolute top-6 right-6 bg-[var(--panel)] p-2 rounded-lg border border-[var(--border)] hover:bg-red-500 hover:text-white transition-all z-20 shadow-lg"
                  >
                    <X className="w-4 h-4" />
                  </button>
                )}
                
                {isScanning && (
                  <div className="absolute inset-0 bg-[var(--accent)]/20 backdrop-blur-[4px] flex items-center justify-center rounded-xl overflow-hidden">
                    <div className="absolute top-0 left-0 w-full h-full scan-line" />
                    <div className="flex flex-col items-center gap-4 z-10">
                      <Loader2 className="w-10 h-10 animate-spin text-white" />
                      <span className="text-white text-[11px] font-black tracking-[0.4em] uppercase drop-shadow-lg">
                        {mode === 'game' && selectedGame === 'Minecraft' ? 'Cracking World Seed' : 'Neural Triangulation'}
                      </span>
                    </div>
                  </div>
                )}
              </motion.div>
            ) : (
              <motion.div 
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                className="flex flex-col items-center gap-4 text-[var(--text-muted)] group-hover:text-[var(--accent)] transition-colors"
              >
                <div className="p-5 rounded-full bg-[var(--bg)] border border-[var(--border)] group-hover:border-[var(--accent)]/50 transition-all shadow-sm">
                  <Upload className="w-8 h-8" />
                </div>
                <div className="flex flex-col items-center">
                  <p className="text-xs font-black uppercase tracking-[0.2em] text-[var(--text)]">Initialize Imagery</p>
                  <p className="text-[10px] mt-2 uppercase tracking-widest opacity-60">Upload photo for neural scan</p>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {mode === 'game' && (
          <div className="flex flex-col gap-3">
            <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-[0.2em] font-black">Virtual Universe</label>
            <select 
              value={selectedGame}
              onChange={(e) => { setSelectedGame(e.target.value); onGameChange?.(e.target.value); }}
              className="bg-[var(--bg)] border border-[var(--border)] rounded-xl p-4 text-xs font-black outline-none focus:border-[var(--accent)]/50 transition-all cursor-pointer shadow-sm text-[var(--text)]"
            >
              <option>Minecraft</option>
              <option>GTA V</option>
              <option>Genshin Impact</option>
              <option>Fortnite</option>
              <option>Warzone</option>
              <option>Apex Legends</option>
              <option>PUBG</option>
              <option>Elden Ring</option>
              <option>RDR 2</option>
              <option>Cyberpunk 2077</option>
            </select>
          </div>
        )}

        <button
          disabled={!selectedFile || isScanning}
          onClick={startScan}
          className={`w-full py-5 rounded-2xl font-black text-[11px] uppercase tracking-[0.4em] flex items-center justify-center gap-4 transition-all ${!selectedFile || isScanning ? 'bg-[var(--border)] text-[var(--text-muted)] cursor-not-allowed' : 'bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white shadow-xl shadow-[var(--accent)]/20 active:scale-95'}`}
        >
          {isScanning ? `SCANNING [${scanTime.toFixed(1)}S]` : 'INITIALIZE NEURAL SCAN'}
        </button>
      </div>

      <div className="flex items-center gap-4 p-5 md:p-6 border-t border-[var(--border)] bg-[var(--panel)] flex-shrink-0">
        <div className="w-8 h-8 rounded-lg bg-[var(--bg)] border border-[var(--border)] flex items-center justify-center">
          <Globe className="w-3.5 h-3.5 text-[var(--text-muted)]" />
        </div>
        <div className="flex-1">
          <p className="text-[8px] text-[var(--text-muted)] uppercase tracking-widest font-black">Pinpoint Intelligence</p>
          <p className="text-[10px] font-medium leading-tight">Universal Geolocation Helper active.</p>
        </div>
      </div>
    </div>
  );
};

export default Scanner;
