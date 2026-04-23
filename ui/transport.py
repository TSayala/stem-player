"""Transport bar: play/pause, seek slider, time, tempo, pitch."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QSlider,
    QLabel, QFrame,
)


def _fmt_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


class TransportBar(QFrame):
    """Play/pause button, seek slider, time display, tempo & pitch knobs."""

    play_toggled = Signal()
    stop_clicked = Signal()
    seek_requested = Signal(float)     # seconds
    tempo_changed = Signal(float)      # ratio
    pitch_changed = Signal(float)      # semitones

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("background: #1B1D23; border-radius: 8px; padding: 4px;")
        self._duration: float = 0.0
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setSpacing(4)
        outer.setContentsMargins(12, 6, 12, 6)

        # ── row 1: seek bar ──────────────────────────────
        seek_row = QHBoxLayout()
        seek_row.setSpacing(8)

        self.time_label = QLabel("0:00")
        self.time_label.setFixedWidth(40)
        self.time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.time_label.setStyleSheet("font-size: 12px; color: #ABB2BF;")

        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 10000)
        self.seek_slider.sliderReleased.connect(self._on_seek)
        self.seek_slider.sliderMoved.connect(self._on_seek_preview)

        self.duration_label = QLabel("0:00")
        self.duration_label.setFixedWidth(40)
        self.duration_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.duration_label.setStyleSheet("font-size: 12px; color: #5C6370;")

        seek_row.addWidget(self.time_label)
        seek_row.addWidget(self.seek_slider, 1)
        seek_row.addWidget(self.duration_label)
        outer.addLayout(seek_row)

        # ── row 2: transport + tempo/pitch ────────────────
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(12)

        # Play / Stop
        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedSize(44, 36)
        self.play_btn.setStyleSheet("font-size: 18px; border-radius: 18px;")
        self.play_btn.clicked.connect(self.play_toggled)

        self.stop_btn = QPushButton("■")
        self.stop_btn.setFixedSize(36, 36)
        self.stop_btn.setStyleSheet("font-size: 16px; border-radius: 18px;")
        self.stop_btn.clicked.connect(self.stop_clicked)

        ctrl_row.addStretch()
        ctrl_row.addWidget(self.stop_btn)
        ctrl_row.addWidget(self.play_btn)
        ctrl_row.addStretch()

        # Tempo control
        ctrl_row.addWidget(self._separator())
        tempo_col = QVBoxLayout()
        tempo_col.setSpacing(0)
        tl = QLabel("Tempo")
        tl.setAlignment(Qt.AlignCenter)
        tl.setStyleSheet("font-size: 10px; color: #5C6370;")
        self.tempo_slider = QSlider(Qt.Horizontal)
        self.tempo_slider.setRange(50, 200)  # percent
        self.tempo_slider.setValue(100)
        self.tempo_slider.setFixedWidth(120)
        self.tempo_slider.valueChanged.connect(self._on_tempo)
        self.tempo_label = QLabel("100%")
        self.tempo_label.setAlignment(Qt.AlignCenter)
        self.tempo_label.setStyleSheet("font-size: 11px;")
        self.tempo_label.setFixedWidth(50)
        tempo_row = QHBoxLayout()
        tempo_row.addWidget(self.tempo_slider)
        tempo_row.addWidget(self.tempo_label)
        tempo_col.addWidget(tl)
        tempo_col.addLayout(tempo_row)
        ctrl_row.addLayout(tempo_col)

        # Pitch control
        ctrl_row.addWidget(self._separator())
        pitch_col = QVBoxLayout()
        pitch_col.setSpacing(0)
        pl = QLabel("Pitch")
        pl.setAlignment(Qt.AlignCenter)
        pl.setStyleSheet("font-size: 10px; color: #5C6370;")
        self.pitch_slider = QSlider(Qt.Horizontal)
        self.pitch_slider.setRange(-120, 120)  # tenths of semitone
        self.pitch_slider.setValue(0)
        self.pitch_slider.setFixedWidth(120)
        self.pitch_slider.valueChanged.connect(self._on_pitch)
        self.pitch_label = QLabel("0 st")
        self.pitch_label.setAlignment(Qt.AlignCenter)
        self.pitch_label.setStyleSheet("font-size: 11px;")
        self.pitch_label.setFixedWidth(50)
        pitch_row = QHBoxLayout()
        pitch_row.addWidget(self.pitch_slider)
        pitch_row.addWidget(self.pitch_label)
        pitch_col.addWidget(pl)
        pitch_col.addLayout(pitch_row)
        ctrl_row.addLayout(pitch_col)

        ctrl_row.addStretch()
        outer.addLayout(ctrl_row)

    def _separator(self) -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color: #3E4451;")
        return sep

    # ── public setters ────────────────────────────────────

    def set_duration(self, seconds: float):
        self._duration = seconds
        self.duration_label.setText(_fmt_time(seconds))

    def set_position(self, seconds: float):
        self.time_label.setText(_fmt_time(seconds))
        if not self.seek_slider.isSliderDown() and self._duration > 0:
            self.seek_slider.blockSignals(True)
            self.seek_slider.setValue(int(seconds / self._duration * 10000))
            self.seek_slider.blockSignals(False)

    def set_playing(self, playing: bool):
        self.play_btn.setText("⏸" if playing else "▶")

    # ── handlers ──────────────────────────────────────────

    def _on_seek(self):
        if self._duration > 0:
            frac = self.seek_slider.value() / 10000
            self.seek_requested.emit(frac * self._duration)

    def _on_seek_preview(self, val: int):
        if self._duration > 0:
            self.time_label.setText(_fmt_time(val / 10000 * self._duration))

    def _on_tempo(self, val: int):
        self.tempo_label.setText(f"{val}%")
        self.tempo_changed.emit(val / 100.0)

    def _on_pitch(self, val: int):
        st = val / 10.0
        self.pitch_label.setText(f"{st:+.1f} st")
        self.pitch_changed.emit(st)
