import os
import base64
import io
import time
import hashlib
import json
import re
import requests
import torch
import redis
from transformers import CLIPProcessor, CLIPModel
from PIL import Image
from typing import Any
from geopy.geocoders import Nominatim
from dotenv import load_dotenv

# --- SETUP ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
load_dotenv(os.path.join(ROOT_DIR, '.env'))

class ModelHub:
    def __init__(self):
        self.keys = {"GROQ": os.getenv("GROQ_API_KEY"), "GOOGLE": os.getenv("GOOGLE_API_KEY"), "GITHUB": os.getenv("GITHUB_API_KEY")}
        self.groq_lead = "meta-llama/llama-4-scout-17b-16e-instruct"
        self.gemini_fleet = ["gemini-3.1-flash-lite", "gemini-3-flash-preview", "gemini-robotics-er-1.6-preview", "gemini-2.5-flash"]
        self.github_fleet = ["Llama-3.2-11b-vision-instruct", "gpt-4o"]
        self.local_model = None
        self.local_processor = None

    def _init_local_bunker(self):
        if self.local_model is not None: return
        try:
            self.local_model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
            self.local_processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
        except: pass

    def call_local_engine(self, image_bytes):
        self._init_local_bunker()
        if not self.local_model: return None
        try:
            image = Image.open(io.BytesIO(image_bytes))
            labels = ["Manarola, Italy", "Santorini, Greece", "Tokyo, Japan", "New York, USA"]
            inputs = self.local_processor(text=labels, images=image)
            outputs = self.local_model(**inputs)
            return f"[NAME: {labels[outputs.logits_per_image.argmax().item()]}]"
        except: return None

    def call_groq(self, b64, mode="real-world", game=""):
        prompt = "Identity: [NAME: City, Country]"
        if mode == "game":
            prompt = f"Analyze this {game} screenshot. Identify the exact natural biome or terrain type (e.g., Plains Coast, Ocean, Forest), explicitly ignoring player-built structures for the location. Estimate the specific game version based on textures/lighting (e.g., Alpha 1.2, Java 1.20), dimension, XYZ coordinates, and generate a highly unique 10-digit World Seed based on the natural terrain generation. Format strictly: [LOC: Natural Biome/Terrain] [X: int] [Y: int] [Z: int] [VER: Specific Version] [DIM: Dimension] [SEED: unique 10-digit number]"
        return self._call_api("https://api.groq.com/openai/v1/chat/completions", {"Authorization": f"Bearer {self.keys['GROQ']}"}, {"model": self.groq_lead, "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}]})

    def call_gemini(self, b64, mid, mode="real-world", game=""):
        prompt = "Identity: [NAME: City, Country]"
        if mode == "game":
            prompt = f"Analyze this {game} screenshot. Identify the exact natural biome or terrain type (e.g., Plains Coast, Ocean, Forest), explicitly ignoring player-built structures for the location. Estimate the specific game version based on textures/lighting (e.g., Alpha 1.2, Java 1.20), dimension, XYZ coordinates, and generate a highly unique 10-digit World Seed based on the natural terrain generation. Format strictly: [LOC: Natural Biome/Terrain] [X: int] [Y: int] [Z: int] [VER: Specific Version] [DIM: Dimension] [SEED: unique 10-digit number]"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{mid}:generateContent?key={self.keys['GOOGLE']}"
        payload = {"contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": "image/jpeg", "data": b64}}]}]}
        try:
            res = requests.post(url, json=payload, timeout=15)
            return res.json()['candidates'][0]['content']['parts'][0]['text'] if res.status_code == 200 else None
        except: return None

    def call_github(self, b64, mid, mode="real-world", game=""):
        prompt = "Identity: [NAME: City, Country]"
        if mode == "game":
            prompt = f"Analyze this {game} screenshot. Identify the exact natural biome or terrain type (e.g., Plains Coast, Ocean, Forest), explicitly ignoring player-built structures for the location. Estimate the specific game version based on textures/lighting (e.g., Alpha 1.2, Java 1.20), dimension, XYZ coordinates, and generate a highly unique 10-digit World Seed based on the natural terrain generation. Format strictly: [LOC: Natural Biome/Terrain] [X: int] [Y: int] [Z: int] [VER: Specific Version] [DIM: Dimension] [SEED: unique 10-digit number]"
        return self._call_api("https://models.inference.ai.azure.com/chat/completions", {"Authorization": f"Bearer {self.keys['GITHUB']}"}, {"model": mid, "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}]})

    def _call_api(self, url, headers, payload):
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=12)
            return res.json()['choices'][0]['message']['content'] if res.status_code == 200 else None
        except: return None

class AIEngine:
    def __init__(self):
        self.hub = ModelHub()
        self.geolocator = Nominatim(user_agent=f"pinpoint_pro_{int(time.time())}")
        
        # --- INITIALIZE REDIS CACHE (VERCEL READY) ---
        self.redis = None
        try:
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            self.redis = redis.from_url(redis_url, decode_responses=True)
            self.redis.ping()
            print(f"💾 REDIS CACHE: Connected to {redis_url.split('@')[-1]}")
        except:
            print("⚠️ REDIS CACHE: Offline. Running in stateless mode.")
            self.redis = None

    def sanitize_location(self, text):
        match = re.search(r'\[NAME:\s*(.*?)\]', text, re.IGNORECASE)
        return match.group(1).strip().replace("**", "") if match else text.replace("**", "").split('\n')[0].strip()

    def parse_game_response(self, text, game):
        # Default fallbacks
        loc = f"Procedural Sector ({game})"
        x, y, z = 0, 64, 0
        ver, dim, seed = "Unknown", "Unknown", "0000000000"
        
        try:
            loc_match = re.search(r'\[LOC:\s*(.*?)\]', text, re.IGNORECASE)
            x_match = re.search(r'\[X:\s*(-?\d+)\]', text, re.IGNORECASE)
            y_match = re.search(r'\[Y:\s*(-?\d+)\]', text, re.IGNORECASE)
            z_match = re.search(r'\[Z:\s*(-?\d+)\]', text, re.IGNORECASE)
            ver_match = re.search(r'\[VER:\s*(.*?)\]', text, re.IGNORECASE)
            dim_match = re.search(r'\[DIM:\s*(.*?)\]', text, re.IGNORECASE)
            seed_match = re.search(r'\[SEED:\s*(-?\d+)\]', text, re.IGNORECASE)

            if loc_match: loc = loc_match.group(1).strip()
            if x_match: x = int(x_match.group(1))
            if y_match: y = int(y_match.group(1))
            if z_match: z = int(z_match.group(1))
            if ver_match: ver = ver_match.group(1).strip()
            if dim_match: dim = dim_match.group(1).strip()
            if seed_match: seed = seed_match.group(1).strip()
        except: pass
        
        return loc, x, y, z, ver, dim, seed

    def scan_real_world(self, image_bytes):
        # 1. EXACT IMAGE HASH CACHE
        img_hash = hashlib.md5(image_bytes).hexdigest()
        img_cache_key = f"pinpoint:img:{img_hash}"
        
        if self.redis:
            cached_result = self.redis.get(img_cache_key)
            if cached_result:
                print(f"💾 REDIS HIT: {img_hash[:8]}")
                return json.loads(cached_result)

        # 2. NEURAL SCAN
        base64_img = base64.b64encode(image_bytes).decode('utf-8')
        hint, source = None, "Unknown"
        
        hint = self.hub.call_groq(base64_img)
        if not hint:
            for m in self.hub.gemini_fleet:
                hint = self.hub.call_gemini(base64_img, m)
                if hint: source=f"Gemini({m})"; break
        if not hint:
            for m in self.hub.github_fleet:
                hint = self.hub.call_github(base64_img, m)
                if hint: source=f"GitHub({m})"; break
        if not hint: hint = self.hub.call_local_engine(image_bytes); source="Local"

        if not hint: return {"error": "All 14 channels failed."}

        clean_hint = self.sanitize_location(hint)
        
        # 3. GEOCODING CACHE (Protects Nominatim Limits)
        geo_cache_key = f"pinpoint:geo:{clean_hint.lower().replace(' ', '_')}"
        
        if self.redis:
            cached_geo = self.redis.get(geo_cache_key)
            if cached_geo:
                cached_coords = json.loads(cached_geo)
                result = {
                    "location": clean_hint,
                    "coordinates": cached_coords,
                    "confidence": 0.99,
                    "mode": "real-world",
                    "insights": [f"Source: {source} (Geo Cached)"]
                }
                self.redis.setex(img_cache_key, 604800, json.dumps(result))
                return result

        # 4. LIVE MAP LOCK (FLAWLESS V40 LOGIC)
        loc = None
        try:
            loc = self.geolocator.geocode(clean_hint, addressdetails=True, language='en', timeout=10)
            if not loc and clean_hint.count(",") >= 2:
                # Fallback A: Try First + Last word (e.g. Manarola, Italy)
                parts = [p.strip() for p in clean_hint.split(",")]
                loc = self.geolocator.geocode(f"{parts[0]}, {parts[-1]}", addressdetails=True, language='en', timeout=10)
            if not loc and "," in clean_hint:
                # Fallback B: Try Last two words (e.g. La Spezia, Italy)
                loc = self.geolocator.geocode(",".join(clean_hint.split(",")[-2:]).strip(), addressdetails=True, language='en', timeout=10)
        except: pass

        if loc:
            result = {
                "location": clean_hint,
                "coordinates": {"lat": loc.latitude, "lng": loc.longitude},
                "confidence": 0.99,
                "mode": "real-world",
                "insights": [f"Source: {source}"]
            }
            if self.redis:
                self.redis.set(geo_cache_key, json.dumps({"lat": loc.latitude, "lng": loc.longitude}))
                self.redis.setex(img_cache_key, 604800, json.dumps(result))
            return result
        
        return {"error": "Map lock failed."}

    def scan_game(self, image_bytes, game_name):
        # 1. EXACT IMAGE HASH CACHE
        img_hash = hashlib.md5(image_bytes).hexdigest()
        img_cache_key = f"pinpoint:game:{img_hash}"
        
        if self.redis:
            cached_result = self.redis.get(img_cache_key)
            if cached_result:
                print(f"💾 REDIS HIT (Game): {img_hash[:8]}")
                return json.loads(cached_result)

        # 2. NEURAL SCAN
        base64_img = base64.b64encode(image_bytes).decode('utf-8')
        hint, source = None, "Unknown"
        
        hint = self.hub.call_groq(base64_img, mode="game", game=game_name)
        if not hint:
            for m in self.hub.gemini_fleet:
                hint = self.hub.call_gemini(base64_img, m, mode="game", game=game_name)
                if hint: source=f"Gemini({m})"; break
        if not hint:
            for m in self.hub.github_fleet:
                hint = self.hub.call_github(base64_img, m, mode="game", game=game_name)
                if hint: source=f"GitHub({m})"; break
                
        if not hint: return {"error": "All channels failed to process virtual environment."}

        # 3. PARSE GAME INTELLIGENCE
        loc, x, y, z, ver, dim, seed = self.parse_game_response(hint, game_name)

        result = {
            "game": game_name, 
            "location": loc, 
            "coordinates": {"x": x, "y": y, "z": z},
            "seed": seed,
            "version": ver,
            "type": dim,
            "mode": "game",
            "confidence": 0.95,
            "insights": [f"Engine: {source}"]
        }
        
        if self.redis:
            self.redis.setex(img_cache_key, 604800, json.dumps(result))
            
        return result

engine = None
def get_engine():
    global engine
    if engine is None: engine = AIEngine()
    return engine
