"""Audio analysis: BPM and musical key detection."""

from __future__ import annotations

import numpy as np
import librosa


def detect_bpm(audio: np.ndarray, sr: int) -> float:
    """Return estimated BPM for a mono or stereo signal."""
    y = _to_mono(audio)
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    return float(np.atleast_1d(tempo)[0])


def detect_key(audio: np.ndarray, sr: int) -> str:
    """Return estimated musical key, e.g. 'C Major' or 'A Minor'."""
    y = _to_mono(audio)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    chroma_avg = chroma.mean(axis=1)
    chroma_avg /= chroma_avg.sum() + 1e-12

    major = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    minor = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

    best_corr, best_label = -2.0, "C Major"
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

    for i in range(12):
        for profile, mode in [(major, "Major"), (minor, "Minor")]:
            corr = float(np.corrcoef(np.roll(profile, i), chroma_avg)[0, 1])
            if corr > best_corr:
                best_corr, best_label = corr, f"{names[i]} {mode}"

    return best_label


def _to_mono(audio: np.ndarray) -> np.ndarray:
    if audio.ndim == 1:
        return audio
    return audio.mean(axis=0)
