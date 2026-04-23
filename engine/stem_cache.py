"""Stem caching with Opus encoding for compact storage.

Each song's stems are stored as individual .opus files inside a folder
named by a hash of the source file path + modification time.  A small
JSON manifest sits alongside them with metadata (BPM, key, duration…).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from config import AppConfig, STEM_NAMES


def _song_hash(source_path: Path) -> str:
    """Deterministic hash for a source file (path + mtime + size)."""
    stat = source_path.stat()
    blob = f"{source_path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}"
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _find_ffmpeg() -> str:
    """Locate ffmpeg binary."""
    path = shutil.which("ffmpeg")
    if path is None:
        raise FileNotFoundError(
            "ffmpeg not found on PATH.  Install ffmpeg and ensure it is on your system PATH."
        )
    return path


class StemCache:
    """Manages on-disk Opus-encoded stem files."""

    def __init__(self, config: AppConfig):
        self.config = config
        self._ffmpeg = _find_ffmpeg()

    # ------------------------------------------------------------------
    # public helpers
    # ------------------------------------------------------------------

    def cache_dir_for(self, source_path: Path) -> Path:
        h = _song_hash(source_path)
        return self.config.cache_dir / h

    def is_cached(self, source_path: Path) -> bool:
        d = self.cache_dir_for(source_path)
        if not d.exists():
            return False
        manifest = d / "manifest.json"
        if not manifest.exists():
            return False
        # Quick check: all expected stems present
        meta = json.loads(manifest.read_text())
        for s in meta.get("stems", []):
            if not (d / f"{s}.opus").exists():
                return False
        return True

    def load_manifest(self, source_path: Path) -> dict:
        d = self.cache_dir_for(source_path)
        return json.loads((d / "manifest.json").read_text())

    # ------------------------------------------------------------------
    # save / load stems
    # ------------------------------------------------------------------

    def save_stems(
        self,
        source_path: Path,
        stems: dict[str, np.ndarray],
        sr: int,
        metadata: Optional[dict] = None,
    ) -> Path:
        """Encode each stem to Opus and write manifest.

        Args:
            source_path: original audio file (for hashing)
            stems: mapping stem_name → float32 numpy array [channels, samples]
            sr: sample rate of the arrays
            metadata: optional extra fields (bpm, key, …)

        Returns:
            cache directory Path
        """
        d = self.cache_dir_for(source_path)
        d.mkdir(parents=True, exist_ok=True)

        stem_names_written: list[str] = []
        for name, audio in stems.items():
            opus_path = d / f"{name}.opus"
            self._encode_opus(audio, sr, opus_path)
            stem_names_written.append(name)

        manifest = {
            "source": str(source_path.resolve()),
            "sample_rate": sr,
            "stems": stem_names_written,
            **(metadata or {}),
        }
        (d / "manifest.json").write_text(json.dumps(manifest, indent=2))
        return d

    def load_stems(self, source_path: Path) -> tuple[dict[str, np.ndarray], int]:
        """Load all cached stems back into float32 numpy arrays.

        Returns:
            (dict[stem_name → ndarray[channels, samples]], sample_rate)
        """
        d = self.cache_dir_for(source_path)
        meta = json.loads((d / "manifest.json").read_text())
        sr = meta["sample_rate"]

        stems: dict[str, np.ndarray] = {}
        for name in meta["stems"]:
            opus_path = d / f"{name}.opus"
            stems[name] = self._decode_opus(opus_path, sr)

        return stems, sr

    # ------------------------------------------------------------------
    # ffmpeg Opus encode / decode
    # ------------------------------------------------------------------

    def _encode_opus(self, audio: np.ndarray, sr: int, out_path: Path) -> None:
        """Encode float32 numpy audio to Opus via ffmpeg."""
        # audio shape: [channels, samples] or [samples]
        if audio.ndim == 1:
            audio = audio[np.newaxis, :]
        channels, samples = audio.shape

        # Write to a temp wav first (ffmpeg reads wav reliably)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            # soundfile expects [samples, channels]
            sf.write(tmp_path, audio.T, sr, subtype="FLOAT")
            cmd = [
                self._ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(tmp_path),
                "-c:a", "libopus",
                "-b:a", f"{self.config.opus_bitrate}k",
                "-ar", "48000",  # Opus only supports 48k/24k/16k/12k/8k
                str(out_path),
            ]
            subprocess.run(cmd, check=True)
        finally:
            tmp_path.unlink(missing_ok=True)

    def _decode_opus(self, opus_path: Path, target_sr: int) -> np.ndarray:
        """Decode Opus file back to float32 numpy array [channels, samples]."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            cmd = [
                self._ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(opus_path),
                "-ar", str(target_sr),
                "-c:a", "pcm_f32le",
                str(tmp_path),
            ]
            subprocess.run(cmd, check=True)
            data, sr = sf.read(tmp_path, dtype="float32")
            # data is [samples, channels] or [samples] for mono
            if data.ndim == 1:
                return data[np.newaxis, :]
            return data.T  # → [channels, samples]
        finally:
            tmp_path.unlink(missing_ok=True)
