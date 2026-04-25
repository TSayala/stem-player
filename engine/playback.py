"""Real-time audio playback engine with per-stem mixing, EQ, pitch and tempo."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import sounddevice as sd
from scipy.signal import sosfilt, butter

from config import AppConfig


# ── per-stem state ────────────────────────────────────────────────────

@dataclass
class StemState:
    """Mutable mix parameters for a single stem."""
    volume: float = 1.0       # 0.0 … 1.5
    muted: bool = False
    solo: bool = False
    eq_low: float = 0.0       # dB, –12 … +12
    eq_mid: float = 0.0
    eq_high: float = 0.0


# ── 3-band EQ ────────────────────────────────────────────────────────

def _make_eq_filters(sr: int):
    """Pre-compute second-order-section filters for 3-band EQ."""
    low = butter(2, 300, btype="low", fs=sr, output="sos")
    mid = butter(2, [300, 4000], btype="band", fs=sr, output="sos")
    high = butter(2, 4000, btype="high", fs=sr, output="sos")
    return low, mid, high


def _apply_eq(block: np.ndarray, sos_low, sos_mid, sos_high,
              gain_low_db: float, gain_mid_db: float, gain_high_db: float) -> np.ndarray:
    """Apply 3-band EQ to a [channels, samples] block."""
    if gain_low_db == 0.0 and gain_mid_db == 0.0 and gain_high_db == 0.0:
        return block
    gl = 10 ** (gain_low_db / 20)
    gm = 10 ** (gain_mid_db / 20)
    gh = 10 ** (gain_high_db / 20)
    out = np.zeros_like(block)
    for ch in range(block.shape[0]):
        out[ch] = (sosfilt(sos_low, block[ch]) * gl
                   + sosfilt(sos_mid, block[ch]) * gm
                   + sosfilt(sos_high, block[ch]) * gh)
    return out


# ── playback engine ──────────────────────────────────────────────────

class PlaybackEngine:
    """Mixes loaded stems in real-time through the sounddevice callback."""

    def __init__(self, config: AppConfig):
        self.config = config
        self._lock = threading.Lock()
        self._stream: Optional[sd.OutputStream] = None

        # Audio data: dict[stem_name → float32 ndarray [channels, samples]]
        self._stems: dict[str, np.ndarray] = {}
        self._stem_states: dict[str, StemState] = {}
        self._sr: int = config.sample_rate

        # Transport state
        self._pos: int = 0           # current sample position
        self._playing: bool = False
        self._total_samples: int = 0

        # Pitch / tempo (applied via pre-processed buffers)
        self._tempo_ratio: float = 1.0  # >1 = faster
        self._pitch_semitones: float = 0.0

        # Processed stems cache (after tempo/pitch transform)
        self._processed_stems: dict[str, np.ndarray] = {}
        self._transform_dirty: bool = False
        self._rebuild_lock = threading.Lock()  # serialises rebuild calls

        # Loop
        self._loop: bool = False

        # EQ filter coefficients (computed once per sample rate)
        self._eq_sos = _make_eq_filters(config.sample_rate)

        # Callbacks
        self.on_position_changed: Optional[Callable[[int, int], None]] = None  # (pos, total)
        self.on_playback_finished: Optional[Callable[[], None]] = None

    # ------------------------------------------------------------------
    # loading
    # ------------------------------------------------------------------

    def load_stems(self, stems: dict[str, np.ndarray], sr: int):
        """Load a new set of stems for playback."""
        with self._lock:
            self.stop()
            self._stems = stems
            self._sr = sr
            self._eq_sos = _make_eq_filters(sr)

            # Init per-stem state
            self._stem_states = {name: StemState() for name in stems}

            # Align lengths
            max_len = max(s.shape[-1] for s in stems.values())
            for name in self._stems:
                s = self._stems[name]
                if s.shape[-1] < max_len:
                    pad = max_len - s.shape[-1]
                    self._stems[name] = np.pad(s, ((0, 0), (0, pad)))

            self._total_samples = max_len
            self._pos = 0
            self._processed_stems = dict(self._stems)  # identity until tempo/pitch change
            self._transform_dirty = False

    @property
    def stem_names(self) -> list[str]:
        return list(self._stems.keys())

    @property
    def duration_seconds(self) -> float:
        return self._total_samples / self._sr if self._sr else 0.0

    @property
    def position_seconds(self) -> float:
        return self._pos / self._sr if self._sr else 0.0

    # ------------------------------------------------------------------
    # transport
    # ------------------------------------------------------------------

    def play(self):
        if not self._stems:
            return
        self._rebuild_if_dirty()
        self._playing = True
        if self._stream is None or not self._stream.active:
            self._stream = sd.OutputStream(
                samplerate=self._sr,
                channels=2,
                blocksize=self.config.buffer_frames,
                callback=self._audio_callback,
                finished_callback=self._stream_finished,
            )
            self._stream.start()

    def pause(self):
        self._playing = False

    def stop(self):
        self._playing = False
        if self._stream is not None:
            self._stream.close()
            self._stream = None
        self._pos = 0

    def seek(self, seconds: float):
        with self._lock:
            self._pos = max(0, min(int(seconds * self._sr), self._total_samples))

    def toggle_play(self):
        if self._playing:
            self.pause()
        else:
            self.play()

    # ------------------------------------------------------------------
    # per-stem controls
    # ------------------------------------------------------------------

    def get_state(self, stem: str) -> StemState:
        return self._stem_states.get(stem, StemState())

    def set_volume(self, stem: str, vol: float):
        if stem in self._stem_states:
            self._stem_states[stem].volume = max(0.0, min(vol, 1.5))

    def set_mute(self, stem: str, muted: bool):
        if stem in self._stem_states:
            self._stem_states[stem].muted = muted

    def set_solo(self, stem: str, solo: bool):
        if stem in self._stem_states:
            self._stem_states[stem].solo = solo

    def set_eq(self, stem: str, low: float, mid: float, high: float):
        if stem in self._stem_states:
            s = self._stem_states[stem]
            s.eq_low = np.clip(low, -12, 12)
            s.eq_mid = np.clip(mid, -12, 12)
            s.eq_high = np.clip(high, -12, 12)

    # ------------------------------------------------------------------
    # tempo / pitch
    # ------------------------------------------------------------------

    def set_tempo(self, ratio: float):
        """Set tempo multiplier (1.0 = original, 1.1 = 10% faster)."""
        ratio = max(0.5, min(ratio, 2.0))
        if ratio != self._tempo_ratio:
            self._tempo_ratio = ratio
            self._transform_dirty = True

    def set_pitch(self, semitones: float):
        """Shift pitch by semitones (0 = original, positive = up)."""
        semitones = max(-12.0, min(semitones, 12.0))
        if semitones != self._pitch_semitones:
            self._pitch_semitones = semitones
            self._transform_dirty = True

    def set_loop(self, enabled: bool):
        self._loop = bool(enabled)

    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def loop(self) -> bool:
        return self._loop

    def _rebuild_if_dirty(self):
        """Re-process stems through rubberband when tempo/pitch changes.

        Safe to call from any thread. Serialised by ``_rebuild_lock`` so
        callers cannot overlap heavy rubberband work, which would thrash
        temp files and CPU.
        """
        # Non-blocking acquire: if another thread is already rebuilding,
        # bail. The caller will have set _transform_dirty so the active
        # worker will see the latest state and the next call will redo.
        if not self._rebuild_lock.acquire(blocking=False):
            return
        try:
            if not self._transform_dirty or not self._stems:
                return

            tempo = self._tempo_ratio
            pitch = self._pitch_semitones

            if tempo == 1.0 and pitch == 0.0:
                with self._lock:
                    self._processed_stems = dict(self._stems)
                    self._total_samples = max(s.shape[-1] for s in self._stems.values())
                    self._pos = min(self._pos, self._total_samples)
                self._transform_dirty = False
                return

            try:
                import pyrubberband as pyrb
            except ImportError:
                # Fallback: no time/pitch shift available
                with self._lock:
                    self._processed_stems = dict(self._stems)
                    self._total_samples = max(s.shape[-1] for s in self._stems.values())
                    self._pos = min(self._pos, self._total_samples)
                self._transform_dirty = False
                return

            new_stems: dict[str, np.ndarray] = {}
            try:
                for name, audio in self._stems.items():
                    # pyrubberband expects [samples, channels]
                    stretched = pyrb.time_stretch(audio.T, self._sr, tempo)
                    if pitch != 0.0:
                        stretched = pyrb.pitch_shift(stretched, self._sr, pitch)
                    new_stems[name] = stretched.T.astype(np.float32)
            except Exception:
                # Any failure (missing rubberband CLI, subprocess error, …)
                # — fall back to the untransformed stems so playback keeps
                # working instead of crashing the app.
                with self._lock:
                    self._processed_stems = dict(self._stems)
                    self._total_samples = max(s.shape[-1] for s in self._stems.values())
                    self._pos = min(self._pos, self._total_samples)
                self._transform_dirty = False
                return

            max_len = max(s.shape[-1] for s in new_stems.values()) if new_stems else 0
            for name in new_stems:
                s = new_stems[name]
                if s.shape[-1] < max_len:
                    new_stems[name] = np.pad(s, ((0, 0), (0, max_len - s.shape[-1])))

            with self._lock:
                self._processed_stems = new_stems
                self._total_samples = max_len
                self._pos = min(self._pos, self._total_samples)
            # Only clear dirty if tempo/pitch haven't changed since we
            # snapshotted them. Otherwise a newer change arrived mid-rebuild
            # and the next call should run again.
            if tempo == self._tempo_ratio and pitch == self._pitch_semitones:
                self._transform_dirty = False
        finally:
            self._rebuild_lock.release()

    # ------------------------------------------------------------------
    # audio callback (runs on audio thread)
    # ------------------------------------------------------------------

    def _audio_callback(self, outdata: np.ndarray, frames: int, time_info, status):
        if not self._playing:
            outdata[:] = 0
            return

        pos = self._pos
        # If we've reached the end, either loop or stop
        if pos >= self._total_samples:
            if self._loop and self._total_samples > 0:
                pos = 0
                self._pos = 0
            else:
                outdata[:] = 0
                self._playing = False
                return

        end = min(pos + frames, self._total_samples)
        n = end - pos

        if n <= 0:
            outdata[:] = 0
            self._playing = False
            return

        # Determine which stems are audible
        any_solo = any(s.solo for s in self._stem_states.values())

        mix = np.zeros((2, n), dtype=np.float32)
        sos_l, sos_m, sos_h = self._eq_sos

        for name, audio in self._processed_stems.items():
            st = self._stem_states.get(name)
            if st is None:
                continue
            if st.muted:
                continue
            if any_solo and not st.solo:
                continue

            chunk = audio[:, pos:end]
            if chunk.shape[-1] < n:
                chunk = np.pad(chunk, ((0, 0), (0, n - chunk.shape[-1])))

            # EQ
            chunk = _apply_eq(chunk, sos_l, sos_m, sos_h, st.eq_low, st.eq_mid, st.eq_high)

            mix += chunk * st.volume

        # Clip to prevent distortion
        np.clip(mix, -1.0, 1.0, out=mix)

        # sounddevice expects [frames, channels]
        outdata[:n] = mix.T
        if n < frames:
            outdata[n:] = 0

        self._pos = end

        # Notify UI (non-blocking)
        if self.on_position_changed:
            try:
                self.on_position_changed(self._pos, self._total_samples)
            except Exception:
                pass

    def _stream_finished(self):
        if self.on_playback_finished:
            try:
                self.on_playback_finished()
            except Exception:
                pass
