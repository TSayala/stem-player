"""Per-stem mixer channel strip with volume, mute/solo, and 3-band EQ."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider,
    QPushButton, QFrame,
)

from config import STEM_COLORS, STEM_NAMES


# Canonical display order. Anything not in this list falls to the end.
STEM_DISPLAY_ORDER = list(STEM_NAMES)  # ("lead_vocals", "back_vocals", "drums", "bass", "guitar", "piano", "other")


def order_stems(names) -> list[str]:
    """Return stem names sorted by canonical display order."""
    ordered = [n for n in STEM_DISPLAY_ORDER if n in names]
    extras = [n for n in names if n not in STEM_DISPLAY_ORDER]
    return ordered + extras


class EQDial(QSlider):
    """Vertical slider styled as an EQ band control (–12 … +12 dB)."""

    def __init__(self, label: str, parent=None):
        super().__init__(Qt.Vertical, parent)
        self.setRange(-120, 120)  # tenths of dB
        self.setValue(0)
        self.setFixedWidth(28)
        self.setMinimumHeight(60)
        self.setToolTip(f"{label} EQ")

    @property
    def db(self) -> float:
        return self.value() / 10.0


class StemChannelStrip(QFrame):
    """Single channel strip for one stem."""

    volume_changed = Signal(str, float)
    mute_changed = Signal(str, bool)
    solo_changed = Signal(str, bool)
    eq_changed = Signal(str, float, float, float)  # stem, low, mid, high

    def __init__(self, stem_name: str, parent=None):
        super().__init__(parent)
        self.stem_name = stem_name
        self._color = STEM_COLORS.get(stem_name, "#ABB2BF")
        self.setFrameShape(QFrame.Box)
        self.setFixedWidth(90)
        self.setStyleSheet(f"""
            StemChannelStrip {{
                border: 1px solid {self._color}40;
                border-radius: 8px;
                background: #21252B;
            }}
        """)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(4)
        lay.setContentsMargins(6, 8, 6, 8)

        # Label with colour indicator
        lbl = QLabel(self.stem_name.replace("_", " ").title())
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(f"color: {self._color}; font-size: 11px; font-weight: bold;")
        lay.addWidget(lbl)

        # 3-band EQ
        eq_row = QHBoxLayout()
        eq_row.setSpacing(2)
        self.eq_low = EQDial("Low")
        self.eq_mid = EQDial("Mid")
        self.eq_high = EQDial("High")
        for dial, label in [(self.eq_low, "L"), (self.eq_mid, "M"), (self.eq_high, "H")]:
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(dial, 1, Qt.AlignHCenter)
            l = QLabel(label)
            l.setAlignment(Qt.AlignCenter)
            l.setStyleSheet("font-size: 9px; color: #5C6370;")
            col.addWidget(l)
            eq_row.addLayout(col)
            dial.valueChanged.connect(self._on_eq)
        lay.addLayout(eq_row)

        # Volume fader
        self.volume_slider = QSlider(Qt.Vertical)
        self.volume_slider.setRange(0, 150)
        self.volume_slider.setValue(100)
        self.volume_slider.setMinimumHeight(80)
        self.volume_slider.setToolTip("Volume")
        self.volume_slider.valueChanged.connect(self._on_volume)
        lay.addWidget(self.volume_slider, 1, Qt.AlignHCenter)

        self.vol_label = QLabel("100%")
        self.vol_label.setAlignment(Qt.AlignCenter)
        self.vol_label.setStyleSheet("font-size: 10px; color: #5C6370;")
        lay.addWidget(self.vol_label)

        # Mute / Solo buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)

        self.mute_btn = QPushButton("M")
        self.mute_btn.setCheckable(True)
        self.mute_btn.setFixedSize(30, 24)
        self.mute_btn.setToolTip("Mute")
        self.mute_btn.setStyleSheet("""
            QPushButton {
                background: #2C313A;
                color: #ABB2BF;
                border: 1px solid #3E4451;
                border-radius: 4px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover { background: #3E4451; }
            QPushButton:checked {
                background: #E06C75;
                color: #fff;
                border: 1px solid #E06C75;
            }
        """)
        self.mute_btn.toggled.connect(lambda v: self.mute_changed.emit(self.stem_name, v))

        self.solo_btn = QPushButton("S")
        self.solo_btn.setCheckable(True)
        self.solo_btn.setFixedSize(30, 24)
        self.solo_btn.setToolTip("Solo")
        self.solo_btn.setStyleSheet("""
            QPushButton {
                background: #2C313A;
                color: #ABB2BF;
                border: 1px solid #3E4451;
                border-radius: 4px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover { background: #3E4451; }
            QPushButton:checked {
                background: #E5C07B;
                color: #1B1D23;
                border: 1px solid #E5C07B;
            }
        """)
        self.solo_btn.toggled.connect(lambda v: self.solo_changed.emit(self.stem_name, v))

        btn_row.addWidget(self.mute_btn)
        btn_row.addWidget(self.solo_btn)
        lay.addLayout(btn_row)

    def _on_volume(self, val: int):
        self.vol_label.setText(f"{val}%")
        self.volume_changed.emit(self.stem_name, val / 100.0)

    def _on_eq(self):
        self.eq_changed.emit(
            self.stem_name,
            self.eq_low.db,
            self.eq_mid.db,
            self.eq_high.db,
        )


class StemMixer(QWidget):
    """Horizontal strip of all stem channel strips."""

    volume_changed = Signal(str, float)
    mute_changed = Signal(str, bool)
    solo_changed = Signal(str, bool)
    eq_changed = Signal(str, float, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setSpacing(6)
        self._layout.setContentsMargins(8, 4, 8, 4)
        self._strips: dict[str, StemChannelStrip] = {}

    def set_stems(self, stem_names: list[str]):
        """Rebuild channel strips for the given stem names, in canonical order."""
        # Clear existing
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._strips.clear()

        for name in order_stems(stem_names):
            strip = StemChannelStrip(name)
            strip.volume_changed.connect(self.volume_changed)
            strip.mute_changed.connect(self.mute_changed)
            strip.solo_changed.connect(self.solo_changed)
            strip.eq_changed.connect(self.eq_changed)
            self._layout.addWidget(strip)
            self._strips[name] = strip

        self._layout.addStretch()
