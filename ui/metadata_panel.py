"""Track metadata panel — album art + title/artist/album."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel

from engine.metadata import TrackMetadata


class TrackInfoPanel(QFrame):
    """Shows album art + title/artist/album + BPM/key.

    Designed to sit to the left of the stem mixer under the waveform.
    """

    COVER_SIZE = 96

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("background: #21252B; border-radius: 8px;")
        self.setFixedHeight(self.COVER_SIZE + 20)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(12)

        self.cover_label = QLabel()
        self.cover_label.setFixedSize(self.COVER_SIZE, self.COVER_SIZE)
        self.cover_label.setAlignment(Qt.AlignCenter)
        self.cover_label.setStyleSheet(
            "background: #1B1D23; border-radius: 6px; color: #5C6370; font-size: 10px;"
        )
        self.cover_label.setText("No\ncover")
        lay.addWidget(self.cover_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        self.title_label = QLabel("No track loaded")
        self.title_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #ABB2BF;")
        self.title_label.setWordWrap(True)

        self.artist_label = QLabel("")
        self.artist_label.setStyleSheet("font-size: 12px; color: #61AFEF;")
        self.artist_label.setWordWrap(True)

        self.album_label = QLabel("")
        self.album_label.setStyleSheet("font-size: 11px; color: #5C6370;")
        self.album_label.setWordWrap(True)

        self.bpm_key_label = QLabel("")
        self.bpm_key_label.setStyleSheet("font-size: 11px; color: #98C379;")

        text_col.addWidget(self.title_label)
        text_col.addWidget(self.artist_label)
        text_col.addWidget(self.album_label)
        text_col.addStretch()
        text_col.addWidget(self.bpm_key_label)

        lay.addLayout(text_col, 1)

    # ── public API ────────────────────────────────────────

    def set_metadata(self, meta: Optional[TrackMetadata]):
        if meta is None:
            self.title_label.setText("No track loaded")
            self.artist_label.setText("")
            self.album_label.setText("")
            self.bpm_key_label.setText("")
            self._clear_cover()
            return

        self.title_label.setText(meta.display_title)
        self.artist_label.setText(meta.display_artist)
        self.album_label.setText(meta.album)

        if meta.cover:
            pix = QPixmap()
            if pix.loadFromData(meta.cover):
                pix = pix.scaled(
                    self.COVER_SIZE, self.COVER_SIZE,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation,
                )
                self.cover_label.setPixmap(pix)
                self.cover_label.setText("")
                return
        self._clear_cover()

    def set_analysis(self, bpm: Optional[float], key: Optional[str]):
        parts = []
        if bpm:
            parts.append(f"♩ {bpm:.1f} BPM")
        if key:
            parts.append(f"♪ {key}")
        self.bpm_key_label.setText("   ".join(parts))

    # ── internal ──────────────────────────────────────────

    def _clear_cover(self):
        self.cover_label.clear()
        self.cover_label.setText("No\ncover")
