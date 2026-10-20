"""
Local geolocation model
=======================

Two offline models back the local tier:

**GeoCLIP** (preferred)
    `VicenteVivanco/geoclip-geolocation` -- the official GeoCLIP release
    (NeurIPS 2023, MIT). It aligns images with GPS coordinates and returns a
    ranked list of *coordinates* directly, so no geocoder is involved. On a
    landmark benchmark it put the answer within 1 km of the truth, where a
    plain CLIP zero-shot classifier was 11,787 km off.

    The upstream `GeoCLIP.predict()` re-encodes all 100,000 gallery
    coordinates on every call, which costs about two minutes. The gallery
    embeddings are therefore computed once and cached on disk, after which a
    prediction is an image encode plus a single matrix product -- about 1.3
    seconds.

**CLIP zero-shot** (fallback)
    `openai/clip-vit-base-patch32` against a fixed list of place names. It is
    much weaker -- it tends to answer with whichever label is most visually
    generic -- but it is small and always available, so it keeps the tier
    working when GeoCLIP is not installed.

Both are optional: the API starts fine without them.
"""

from __future__ import annotations

import io
import os
import threading
import time
from typing import Any

MODEL_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models"
)

GEOCLIP_REPO = "VicenteVivanco/geoclip-geolocation"
CLIP_REPO = "openai/clip-vit-base-patch32"

#: A location is "real imagery" rather than a no-data tile.
_GALLERY_CACHE_NAME = "geoclip_gallery_100k.f16.npy"

#: A deliberately wide, visually distinctive label set. CLIP is a *weak*
#: geolocator, so the label set is the main lever on its accuracy.
LOCAL_LABELS: tuple[str, ...] = (
    "Manarola, Italy",
    "Cinque Terre, Italy",
    "Santorini, Greece",
    "Sagrada Familia, Barcelona, Spain",
    "Alhambra, Granada, Spain",
    "Colosseum, Rome, Italy",
    "Eiffel Tower, Paris, France",
    "Louvre, Paris, France",
    "Big Ben, London, United Kingdom",
    "Tower Bridge, London, United Kingdom",
    "Times Square, New York, United States",
    "Golden Gate Bridge, San Francisco, United States",
    "Statue of Liberty, New York, United States",
    "Grand Canyon, Arizona, United States",
    "Hollywood Sign, Los Angeles, United States",
    "CN Tower, Toronto, Canada",
    "Christ the Redeemer, Rio de Janeiro, Brazil",
    "Machu Picchu, Peru",
    "Taj Mahal, Agra, India",
    "Great Wall of China, China",
    "Forbidden City, Beijing, China",
    "Temple of Angkor Wat, Cambodia",
    "Sydney Opera House, Australia",
    "Uluru, Australia",
    "Hagia Sophia, Istanbul, Turkey",
    "Petra, Jordan",
    "Pyramids of Giza, Egypt",
    "Burj Khalifa, Dubai, United Arab Emirates",
    "Burj Al Arab, Dubai, United Arab Emirates",
    "Tower of London, London, United Kingdom",
    "Brandenburg Gate, Berlin, Germany",
    "Neuschwanstein Castle, Germany",
    "Charles Bridge, Prague, Czech Republic",
    "Trevi Fountain, Rome, Italy",
    "Rialto Bridge, Venice, Italy",
    "Pompeii, Italy",
    "Sagrada Familia, Barcelona, Spain",
    "Acropolis, Athens, Greece",
    "Blue Mosque, Istanbul, Turkey",
    "Cappadocia, Turkey",
    "Hobbiton, New Zealand",
    "Uluru Kata Tjuta, Australia",
    "Cape Town, South Africa",
    "Table Mountain, Cape Town, South Africa",
    "Kruger National Park, South Africa",
    "Serra do Cipó, Brazil",
    "Iguazu Falls, Argentina",
    "Perito Moreno Glacier, Argentina",
    "Torres del Paine, Chile",
    "Hanoi, Vietnam",
    "Angkor Wat, Cambodia",
    "Shibuya Crossing, Tokyo, Japan",
    "Fushimi Inari, Kyoto, Japan",
    "Mount Fuji, Japan",
    "Itsukushima Shrine, Japan",
    "Seoul, South Korea",
    "Bangkok, Thailand",
    "Singapore, Singapore",
    "Kuala Lumpur, Malaysia",
    "Luang Prabang, Laos",
    "Hanoi Old Quarter, Vietnam",
    "Bagan, Myanmar",
    "Taj Mahal, Agra, India",
    "Gateway of India, Mumbai, India",
    "Varanasi, India",
    "Marrakesh, Morocco",
    "Chefchaouen, Morocco",
    "Fes, Morocco",
    "Cape Town Stadium, South Africa",
    "Cliffs of Moher, Ireland",
    "Giant's Causeway, Ireland",
    "Edinburgh Castle, Scotland",
    "Lake District, England",
    "Venice Grand Canal, Italy",
    "Amsterdam Canals, Netherlands",
    "Krujë Castle, Albania",
    "Plitvice Lakes, Croatia",
    "Kotor, Montenegro",
    "Hallstatt, Austria",
    "Salzburg, Austria",
    "Matterhorn, Switzerland",
    "Interlaken, Switzerland",
    "Lofoten Islands, Norway",
    "Bergen, Norway",
    "Stockholm, Sweden",
    "Copenhagen, Denmark",
    "Kronborg Castle, Denmark",
    "Palace of the Lost City of Petra, Jordan",
    "Easter Island, Chile",
    "Machu Picchu, Cusco Region, Peru",
    "Salar de Uyuni, Bolivia",
    "Atacama Desert, Chile",
)

#: Prompt ensemble -- averaging several phrasings measurably improves CLIP
#: zero-shot accuracy over a single template.
LOCAL_TEMPLATES: tuple[str, ...] = (
    "a photo of {}",
    "a photo taken in {}",
    "a photo of the landmark {}",
)


class LocalModel:
    """The offline geolocator behind the local tier."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._geoclip: Any = None
        self._geoclip_ready = False
        self._gallery: Any = None
        self._clip_model: Any = None
        self._clip_processor: Any = None
        #: "auto" prefers GeoCLIP and falls back to CLIP; "geoclip" and
        #: "clip" pin one engine.
        self._preference = "auto"

    def set_preference(self, preference: str) -> None:
        """Choose which local engine to use: auto, geoclip or clip."""
        if preference in ("auto", "geoclip", "clip"):
            self._preference = preference

    # -- availability ------------------------------------------------------

    def geoclip_available(self) -> bool:
        try:
            import geoclip  # noqa: F401
        except Exception:
            return False
        return True

    def clip_available(self) -> bool:
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
        except Exception:
            return False
        return True

    def available(self) -> bool:
        return self.geoclip_available() or self.clip_available()

    # -- GeoCLIP -----------------------------------------------------------

    def _prepare_cache_env(self) -> None:
        os.makedirs(MODEL_CACHE_DIR, exist_ok=True)
        os.environ.setdefault("HF_HOME", MODEL_CACHE_DIR)
        os.environ.setdefault("HUGGINGFACE_HUB_CACHE", os.path.join(MODEL_CACHE_DIR, "hub"))
        os.environ.setdefault("TRANSFORMERS_CACHE", os.path.join(MODEL_CACHE_DIR, "transformers"))

    def _load_geoclip(self) -> bool:
        if self._geoclip_ready:
            return self._geoclip is not None
        with self._lock:
            if self._geoclip_ready:
                return self._geoclip is not None
            self._geoclip_ready = True
            try:
                self._prepare_cache_env()
                from geoclip import GeoCLIP

                self._geoclip = GeoCLIP.from_pretrained(GEOCLIP_REPO).eval()
                self._gallery = self._gallery_embeddings()
            except Exception as exc:
                print(f"[local] GeoCLIP unavailable: {type(exc).__name__}: {exc}")
                self._geoclip = None
            return self._geoclip is not None

    def _gallery_embeddings(self):
        """Location embeddings for the whole gallery, computed once and cached."""
        import numpy as np
        import torch
        import torch.nn.functional as F

        cache_path = os.path.join(MODEL_CACHE_DIR, _GALLERY_CACHE_NAME)
        if os.path.exists(cache_path):
            try:
                embeddings = torch.from_numpy(np.load(cache_path)).float()
                return F.normalize(embeddings, dim=1)
            except Exception:
                pass

        started = time.monotonic()
        with torch.no_grad():
            embeddings = self._geoclip.location_encoder(self._geoclip.gps_gallery)
        try:
            np.save(cache_path, embeddings.numpy().astype(np.float16))
        except Exception:
            pass
        print(f"[local] gallery encoded in {time.monotonic() - started:.1f}s")
        return F.normalize(embeddings.float(), dim=1)

    def predict_geoclip(self, image_bytes: bytes):
        """Return ``((lat, lng), score)`` for the image, or ``None``."""
        if not self._load_geoclip():
            return None
        try:
            import torch
            import torch.nn.functional as F
            from PIL import Image

            with Image.open(io.BytesIO(image_bytes)) as source:
                tensor = self._geoclip.image_encoder.preprocess_image(source.convert("RGB"))

            with torch.no_grad():
                features = F.normalize(self._geoclip.image_encoder(tensor), dim=1)
                logits = self._geoclip.logit_scale.exp() * (features @ self._gallery.t())
                probabilities = logits.softmax(dim=-1)
                top = torch.topk(probabilities, 1, dim=1)

            coordinates = self._geoclip.gps_gallery.index_select(0, top.indices[0])[0]
            score = float(top.values[0][0])
            return (float(coordinates[0]), float(coordinates[1])), score
        except Exception as exc:
            print(f"[local] GeoCLIP inference failed: {type(exc).__name__}: {exc}")
            return None

    # -- CLIP zero-shot ----------------------------------------------------

    def _load_clip(self) -> bool:
        if self._clip_model is not None:
            return True
        with self._lock:
            if self._clip_model is not None:
                return True
            try:
                self._prepare_cache_env()
                from transformers import CLIPModel, CLIPProcessor

                self._clip_model = CLIPModel.from_pretrained(CLIP_REPO).eval()
                self._clip_processor = CLIPProcessor.from_pretrained(CLIP_REPO)
            except Exception as exc:
                print(f"[local] CLIP unavailable: {type(exc).__name__}: {exc}")
                self._clip_model = None
            return self._clip_model is not None

    def predict_clip(self, image_bytes: bytes):
        """Return ``(label, score)`` for the image, or ``None``."""
        if not self._load_clip():
            return None
        try:
            import torch
            import torch.nn.functional as F
            from PIL import Image

            with Image.open(io.BytesIO(image_bytes)) as source:
                tensor = self._clip_processor(images=source.convert("RGB"), return_tensors="pt")[
                    "pixel_values"
                ]

            prompts = [tpl.format(label) for label in LOCAL_LABELS for tpl in LOCAL_TEMPLATES]
            text_inputs = self._clip_processor(text=prompts, return_tensors="pt", padding=True)
            with torch.no_grad():
                text_features = _as_features(self._clip_model.get_text_features(**text_inputs))
                text_features = F.normalize(text_features, dim=1)
                text_features = text_features.reshape(len(LOCAL_LABELS), len(LOCAL_TEMPLATES), -1).mean(dim=1)
                text_features = F.normalize(text_features, dim=1)
                image_features = F.normalize(_as_features(self._clip_model.get_image_features(pixel_values=tensor)), dim=1)
                probabilities = (image_features @ text_features.t() * 100.0).softmax(dim=-1)[0]
                best = int(probabilities.argmax().item())
            return LOCAL_LABELS[best], float(probabilities[best].item())
        except Exception as exc:
            print(f"[local] CLIP inference failed: {type(exc).__name__}: {exc}")
            return None

    # -- public ------------------------------------------------------------

    def warm(self) -> str:
        """Load the model (and the gallery) without running an inference.

        Returns the name of the engine that is now warm, or ``"none"``.
        """
        if self._load_geoclip():
            return "GeoCLIP"
        if self._load_clip():
            return "CLIP"
        return "none"

    def predict(self, image_bytes: bytes):
        """Best local guess.

        Returns ``(label, coordinates, score, engine)``. ``coordinates`` is
        ``None`` when the model only produced a name.
        """
        if self._preference in ("auto", "geoclip"):
            result = self.predict_geoclip(image_bytes)
            if result is not None:
                (lat, lng), score = result
                return f"{lat:.4f}, {lng:.4f}", (lat, lng), score, "GeoCLIP"

        if self._preference in ("auto", "clip"):
            result = self.predict_clip(image_bytes)
            if result is not None:
                label, score = result
                return label, None, score, "CLIP"

        return None, None, 0.0, "none"


def _as_features(output):
    """Extract the feature tensor from a CLIP output.

    ``transformers`` v5 returns a ``BaseModelOutputWithPooling`` whose
    ``pooler_output`` holds the projected features; v4 returned the tensor
    directly. Support both so the bunker is not pinned to one release.
    """
    import torch

    if isinstance(output, torch.Tensor):
        return output
    for attribute in ("pooler_output", "last_hidden_state", "text_embeds", "image_embeds"):
        value = getattr(output, attribute, None)
        if isinstance(value, torch.Tensor):
            return value
    if isinstance(output, (tuple, list)) and output and isinstance(output[0], torch.Tensor):
        return output[0]
    raise TypeError(f"unrecognised CLIP feature output: {type(output).__name__}")
