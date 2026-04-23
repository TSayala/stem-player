"""Stacked waveform visualisation for all stems."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QLinearGradient, QMouseEvent
from PySide6.QtWidgets import QWidget

from config import STEM_COLORS


class WaveformWidget(QWidget):
    """Draws colour-coded waveform envelopes for each stem and a playhead."""

    seek_requested = Signal(float)  # emits seconds

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(140)
        self.setMouseTracking(True)
        self._envelopes: dict[str, np.ndarray] = {}  # stem → downsampled RMS
        self._visible: dict[str, bool] = {}
        self._position: float = 0.0  # 0–1 fraction
        self._duration: float = 0.0
        self._hover_x: int | None = None
        self._resolution = 800  # bins for downsampling

    # ── data loading ──────────────────────────────────────

    def set_stems(self, stems: dict[str, np.ndarray], sr: int):
        """Compute downsampled RMS envelopes for each stem."""
        self._envelopes.clear()
        if not stems:
            self.update()
            return

        max_len = max(s.shape[-1] for s in stems.values())
        self._duration = max_len / sr
        bins = min(self._resolution, max_len)
        chunk = max(1, max_len // bins)

        for name, audio in stems.items():
            mono = audio.mean(axis=0) if audio.ndim > 1 else audio
            # Pad to multiple of chunk
            padded = np.pad(mono, (0, chunk - len(mono) % chunk)) if len(mono) % chunk else mono
            reshaped = padded[: bins * chunk].reshape(bins, chunk)
            self._envelopes[name] = np.sqrt(np.mean(reshaped ** 2, axis=1))
            self._visible[name] = True

        self.update()

    def set_stem_visible(self, name: str, visible: bool):
        self._visible[name] = visible
        self.update()

    def set_position(self, fraction: float):
        """Update playhead position (0–1)."""
        self._position = max(0.0, min(fraction, 1.0))
        self.update()

    # ── painting ──────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # Background
        p.fillRect(0, 0, w, h, QColor("#1B1D23"))

        if not self._envelopes:
            p.setPen(QColor("#5C6370"))
            p.drawText(self.rect(), Qt.AlignCenter, "Drop an audio file or click Open")
            p.end()
            return

        # Determine visible stems for stacking
        visible = [(n, e) for n, e in self._envelopes.items() if self._visible.get(n, True)]
        if not visible:
            p.end()
            return

        n_stems = len(visible)
        lane_h = h / n_stems

        for idx, (name, env) in enumerate(visible):
            color = QColor(STEM_COLORS.get(name, "#ABB2BF"))
            y_off = idx * lane_h
            mid = y_off + lane_h / 2

            # Normalise envelope
            peak = env.max() if env.max() > 0 else 1.0
            normed = env / peak

            # Draw filled waveform
            half_h = lane_h * 0.4
            bins = len(normed)

            grad = QLinearGradient(0, y_off, 0, y_off + lane_h)
            grad.setColorAt(0, QColor(color.red(), color.green(), color.blue(), 100))
            grad.setColorAt(0.5, QColor(color.red(), color.green(), color.blue(), 200))
            grad.setColorAt(1, QColor(color.red(), color.green(), color.blue(), 100))

            pen = QPen(color, 1)
            p.setPen(pen)

            for i in range(bins):
                x = int(i / bins * w)
                x2 = int((i + 1) / bins * w)
                amp = normed[i] * half_h
                p.fillRect(x, int(mid - amp), max(1, x2 - x), int(amp * 2), grad)

            # Stem label
            p.setPen(QColor(color.red(), color.green(), color.blue(), 180))
            p.drawText(6, int(y_off + 14), name.replace("_", " ").title())

            # Lane separator
            if idx > 0:
                p.setPen(QPen(QColor("#3E4451"), 1))
                p.drawLine(0, int(y_off), w, int(y_off))

        # Playhead
        px = int(self._position * w)
        p.setPen(QPen(QColor("#FFFFFF"), 2))
        p.drawLine(px, 0, px, h)

        # Hover position
        if self._hover_x is not None:
            p.setPen(QPen(QColor(255, 255, 255, 60), 1))
            p.drawLine(self._hover_x, 0, self._hover_x, h)

        p.end()

    # ── interaction ───────────────────────────────────────

    def mousePressEvent(self, ev: QMouseEvent):
        if ev.button() == Qt.LeftButton and self._duration > 0:
            frac = ev.position().x() / self.width()
            self.seek_requested.emit(frac * self._duration)

    def mouseMoveEvent(self, ev: QMouseEvent):
        self._hover_x = int(ev.position().x())
        if ev.buttons() & Qt.LeftButton and self._duration > 0:
            frac = ev.position().x() / self.width()
            self.seek_requested.emit(frac * self._duration)
        self.update()

    def leaveEvent(self, ev):
        self._hover_x = None
        self.update()
