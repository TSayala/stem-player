"""Stem separation engine.

Uses Demucs htdemucs_6s for 6-stem separation, then applies a
centre-panning heuristic to split the 'vocals' stem into
lead vocals (centre) and background vocals (sides).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import torch
import soundfile as sf
import librosa

from config import AppConfig, STEM_NAMES

log = logging.getLogger(__name__)


class Separator:
    """Wraps Demucs model loading and inference."""

    def __init__(self, config: AppConfig):
        self.config = config
        self._model = None
        self._model_sr: int = 44100

    # ------------------------------------------------------------------
    # model management
    # ------------------------------------------------------------------

    def ensure_model(self, progress_cb: Optional[Callable[[str], None]] = None):
        """Download / load the Demucs model if not already loaded."""
        if self._model is not None:
            return
        if progress_cb:
            progress_cb("Loading Demucs model…")

        from demucs.pretrained import get_model
        from demucs.apply import BagOfModels

        model = get_model(self.config.demucs_model)
        if isinstance(model, BagOfModels):
            self._model_sr = model.models[0].samplerate
        else:
            self._model_sr = model.samplerate

        model.to(self.config.device)
        model.eval()
        self._model = model
        if progress_cb:
            progress_cb("Model ready.")

    def unload_model(self):
        if self._model is not None:
            del self._model
            self._model = None
            torch.cuda.empty_cache()

    # ------------------------------------------------------------------
    # separation
    # ------------------------------------------------------------------

    def separate(
        self,
        audio_path: Path,
        progress_cb: Optional[Callable[[str, float], None]] = None,
    ) -> tuple[dict[str, np.ndarray], int]:
        """Run full separation pipeline.

        Args:
            audio_path: path to the source audio file
            progress_cb: optional (message, 0-1 fraction) callback

        Returns:
            (dict[stem_name → float32 ndarray [2, samples]], sample_rate)
        """
        self.ensure_model(progress_cb=lambda m: progress_cb(m, 0.0) if progress_cb else None)

        # --- load audio ------------------------------------------------
        if progress_cb:
            progress_cb("Loading audio…", 0.05)

        wav_np, sr = sf.read(str(audio_path), dtype="float32")
        # sf.read returns [samples] or [samples, channels]
        if wav_np.ndim == 1:
            wav_np = wav_np[np.newaxis, :]          # [1, samples]
        else:
            wav_np = wav_np.T.copy()                # [channels, samples]
        wav = torch.from_numpy(wav_np)

        # Resample to model's expected rate if needed
        if sr != self._model_sr:
            wav_np_mono_or_stereo = wav.numpy()
            wav_resampled = librosa.resample(wav_np_mono_or_stereo, orig_sr=sr, target_sr=self._model_sr)
            wav = torch.from_numpy(wav_resampled.copy())
            sr = self._model_sr
        # Ensure stereo
        if wav.shape[0] == 1:
            wav = wav.expand(2, -1)
        elif wav.shape[0] > 2:
            wav = wav[:2]

        # --- run demucs -------------------------------------------------
        if progress_cb:
            progress_cb("Separating stems (GPU)…" if "cuda" in self.config.device else "Separating stems…", 0.1)

        wav = wav.to(self.config.device)
        ref = wav.mean(0)
        wav_mean = wav - ref.unsqueeze(0)

        from demucs.apply import apply_model

        with torch.no_grad():
            if self.config.device.startswith("cuda") and torch.cuda.is_available():
                with torch.amp.autocast(device_type="cuda"):
                    sources = apply_model(
                        self._model, wav[None], progress=False, device=self.config.device
                    )[0]
            else:
                sources = apply_model(
                    self._model, wav[None], progress=False, device=self.config.device
                )[0]

        # sources shape: [n_sources, channels, samples]
        source_names = self._model.sources  # e.g. ['drums','bass','other','vocals','guitar','piano']

        if progress_cb:
            progress_cb("Splitting vocals…", 0.85)

        raw_stems: dict[str, np.ndarray] = {}
        vocals_np: Optional[np.ndarray] = None

        for i, name in enumerate(source_names):
            arr = sources[i].cpu().numpy().astype(np.float32)
            if name == "vocals":
                vocals_np = arr
            else:
                raw_stems[name] = arr

        # --- split vocals into lead / backing --------------------------
        if vocals_np is not None:
            lead, backs = self._split_vocals(vocals_np)
            raw_stems["lead_vocals"] = lead
            raw_stems["back_vocals"] = backs

        if progress_cb:
            progress_cb("Done.", 1.0)

        return raw_stems, sr

    # ------------------------------------------------------------------
    # vocal lead / backing split via mid-side
    # ------------------------------------------------------------------

    @staticmethod
    def _split_vocals(vocals: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Split a stereo vocal stem into lead (centre) and backing (sides).

        Uses mid-side decomposition: lead vocals are almost always panned
        centre, while backing vocals, harmonies and ad-libs tend to be
        panned wider.

        Args:
            vocals: float32 ndarray [2, samples]

        Returns:
            (lead [2, samples], backing [2, samples])
        """
        if vocals.shape[0] == 1:
            # Mono — all lead, no backing
            return vocals, np.zeros_like(vocals)

        left, right = vocals[0], vocals[1]
        mid = (left + right) / 2.0
        side = (left - right) / 2.0

        # Lead = mid channel duplicated to stereo
        lead = np.stack([mid, mid])

        # Backing = side channel reconstructed to stereo
        backing = np.stack([side, -side])

        return lead, backing
