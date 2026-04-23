"""Main application window."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal, Slot, QThread, QObject
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFileDialog, QMessageBox, QProgressBar, QComboBox, QStatusBar,
    QFrame, QApplication,
)

from config import AppConfig, SUPPORTED_FORMATS, list_gpu_devices
from engine.separator import Separator
from engine.playback import PlaybackEngine
from engine.stem_cache import StemCache
from engine.analyzer import detect_bpm, detect_key
from ui.theme import STYLESHEET
from ui.waveform import WaveformWidget
from ui.stem_controls import StemMixer
from ui.transport import TransportBar

log = logging.getLogger(__name__)


# ── background separation worker ─────────────────────────────────────

class _SeparationWorker(QObject):
    progress = Signal(str, float)     # message, fraction
    finished = Signal(dict, int)      # stems, sr
    error = Signal(str)

    def __init__(self, separator: Separator, cache: StemCache, path: Path):
        super().__init__()
        self.separator = separator
        self.cache = cache
        self.path = path

    @Slot()
    def run(self):
        try:
            # Check cache first
            if self.cache.is_cached(self.path):
                self.progress.emit("Loading cached stems…", 0.5)
                stems, sr = self.cache.load_stems(self.path)
                self.finished.emit(stems, sr)
                return

            # Run separation
            stems, sr = self.separator.separate(
                self.path,
                progress_cb=lambda msg, frac: self.progress.emit(msg, frac),
            )

            # Cache results
            self.progress.emit("Caching stems as Opus…", 0.92)

            # Gather metadata
            first_stem = next(iter(stems.values()))
            bpm = detect_bpm(first_stem, sr)
            key = detect_key(first_stem, sr)
            metadata = {"bpm": round(bpm, 1), "key": key}

            self.cache.save_stems(self.path, stems, sr, metadata)
            self.finished.emit(stems, sr)

        except Exception as e:
            self.error.emit(str(e))


# ── main window ──────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self.separator = Separator(config)
        self.cache = StemCache(config)
        self.playback = PlaybackEngine(config)

        self._current_path: Optional[Path] = None
        self._worker_thread: Optional[QThread] = None

        self._setup_window()
        self._build_ui()
        self._connect_signals()
        self._setup_timers()

    # ── window setup ──────────────────────────────────────

    def _setup_window(self):
        self.setWindowTitle("StemDJ")
        self.resize(1100, 680)
        self.setAcceptDrops(True)
        self.setStyleSheet(STYLESHEET)

        # Menu bar
        menu = self.menuBar()
        file_menu = menu.addMenu("&File")

        open_action = QAction("&Open Audio…", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._on_open)
        file_menu.addAction(open_action)

        file_menu.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    # ── UI construction ───────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(6)
        root.setContentsMargins(8, 8, 8, 8)

        # ── top info bar ──────────────────────────────────
        info_bar = QHBoxLayout()
        info_bar.setSpacing(16)

        self.song_label = QLabel("No file loaded")
        self.song_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        info_bar.addWidget(self.song_label, 1)

        self.bpm_label = QLabel("")
        self.bpm_label.setStyleSheet("font-size: 13px; color: #E5C07B;")
        info_bar.addWidget(self.bpm_label)

        self.key_label = QLabel("")
        self.key_label.setStyleSheet("font-size: 13px; color: #98C379;")
        info_bar.addWidget(self.key_label)

        # GPU selector
        gpu_label = QLabel("Device:")
        gpu_label.setStyleSheet("font-size: 11px; color: #5C6370;")
        info_bar.addWidget(gpu_label)

        self.gpu_combo = QComboBox()
        self.gpu_combo.addItem("CPU", None)
        for dev in list_gpu_devices():
            self.gpu_combo.addItem(f"GPU {dev['index']}: {dev['name']} ({dev['memory_gb']} GB)", dev["index"])
        if self.config.gpu_index is not None:
            idx = self.gpu_combo.findData(self.config.gpu_index)
            if idx >= 0:
                self.gpu_combo.setCurrentIndex(idx)
        self.gpu_combo.currentIndexChanged.connect(self._on_gpu_changed)
        self.gpu_combo.setFixedWidth(260)
        info_bar.addWidget(self.gpu_combo)

        root.addLayout(info_bar)

        # ── waveform ──────────────────────────────────────
        self.waveform = WaveformWidget()
        root.addWidget(self.waveform, 2)

        # ── transport bar ─────────────────────────────────
        self.transport = TransportBar()
        root.addWidget(self.transport)

        # ── stem mixer ────────────────────────────────────
        self.mixer = StemMixer()
        root.addWidget(self.mixer, 3)

        # ── progress bar (hidden until needed) ────────────
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(18)
        root.addWidget(self.progress_bar)

        # Status bar
        self.status_label = QLabel("Ready — drop an audio file or press Ctrl+O")
        sb = QStatusBar()
        sb.addWidget(self.status_label, 1)
        self.setStatusBar(sb)

    # ── signal wiring ─────────────────────────────────────

    def _connect_signals(self):
        self.transport.play_toggled.connect(self._on_play_toggle)
        self.transport.stop_clicked.connect(self._on_stop)
        self.transport.seek_requested.connect(self._on_seek)
        self.transport.tempo_changed.connect(self._on_tempo)
        self.transport.pitch_changed.connect(self._on_pitch)

        self.waveform.seek_requested.connect(self._on_seek)

        self.mixer.volume_changed.connect(self._on_volume)
        self.mixer.mute_changed.connect(self._on_mute)
        self.mixer.solo_changed.connect(self._on_solo)
        self.mixer.eq_changed.connect(self._on_eq)

        self.playback.on_position_changed = self._on_position_tick

    def _setup_timers(self):
        # UI refresh timer (not tied to audio thread)
        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(50)  # 20 fps
        self._ui_timer.timeout.connect(self._refresh_ui)
        self._ui_timer.start()

    # ── drag & drop ───────────────────────────────────────

    def dragEnterEvent(self, ev: QDragEnterEvent):
        if ev.mimeData().hasUrls():
            for url in ev.mimeData().urls():
                if Path(url.toLocalFile()).suffix.lower() in SUPPORTED_FORMATS:
                    ev.acceptProposedAction()
                    return

    def dropEvent(self, ev: QDropEvent):
        for url in ev.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.suffix.lower() in SUPPORTED_FORMATS:
                self._load_file(p)
                return

    # ── file loading ──────────────────────────────────────

    def _on_open(self):
        exts = " ".join(f"*{e}" for e in sorted(SUPPORTED_FORMATS))
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Audio File", "", f"Audio Files ({exts});;All Files (*)"
        )
        if path:
            self._load_file(Path(path))

    def _load_file(self, path: Path):
        if self._worker_thread is not None and self._worker_thread.isRunning():
            QMessageBox.warning(self, "Busy", "A file is already being processed.")
            return

        self._current_path = path
        self.playback.stop()
        self.song_label.setText(path.name)
        self.bpm_label.setText("")
        self.key_label.setText("")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setText(f"Processing {path.name}…")

        # Launch worker thread
        self._worker_thread = QThread()
        worker = _SeparationWorker(self.separator, self.cache, path)
        worker.moveToThread(self._worker_thread)

        self._worker_thread.started.connect(worker.run)
        worker.progress.connect(self._on_worker_progress)
        worker.finished.connect(self._on_worker_finished)
        worker.error.connect(self._on_worker_error)
        worker.finished.connect(self._worker_thread.quit)
        worker.error.connect(self._worker_thread.quit)
        # prevent GC
        self._worker = worker

        self._worker_thread.start()

    @Slot(str, float)
    def _on_worker_progress(self, msg: str, frac: float):
        self.progress_bar.setValue(int(frac * 100))
        self.status_label.setText(msg)

    @Slot(dict, int)
    def _on_worker_finished(self, stems: dict, sr: int):
        self.progress_bar.setVisible(False)
        self.status_label.setText("Ready")

        # Load into playback engine
        self.playback.load_stems(stems, sr)

        # Update UI
        self.waveform.set_stems(stems, sr)
        self.mixer.set_stems(list(stems.keys()))
        self.transport.set_duration(self.playback.duration_seconds)

        # Show analysis info (from cache manifest)
        if self._current_path and self.cache.is_cached(self._current_path):
            meta = self.cache.load_manifest(self._current_path)
            bpm = meta.get("bpm")
            key = meta.get("key")
            if bpm:
                self.bpm_label.setText(f"♩ {bpm} BPM")
            if key:
                self.key_label.setText(f"♪ {key}")

    @Slot(str)
    def _on_worker_error(self, msg: str):
        self.progress_bar.setVisible(False)
        self.status_label.setText("Error")
        QMessageBox.critical(self, "Separation Error", msg)

    # ── transport handlers ────────────────────────────────

    def _on_play_toggle(self):
        self.playback.toggle_play()
        self.transport.set_playing(self.playback._playing)

    def _on_stop(self):
        self.playback.stop()
        self.transport.set_playing(False)
        self.transport.set_position(0)
        self.waveform.set_position(0)

    def _on_seek(self, seconds: float):
        self.playback.seek(seconds)

    def _on_tempo(self, ratio: float):
        self.playback.set_tempo(ratio)
        # Rebuild in background — simple for now
        if not self.playback._playing:
            self.playback._rebuild_if_dirty()

    def _on_pitch(self, semitones: float):
        self.playback.set_pitch(semitones)
        if not self.playback._playing:
            self.playback._rebuild_if_dirty()

    # ── mixer handlers ────────────────────────────────────

    def _on_volume(self, stem: str, vol: float):
        self.playback.set_volume(stem, vol)

    def _on_mute(self, stem: str, muted: bool):
        self.playback.set_mute(stem, muted)
        self.waveform.set_stem_visible(stem, not muted)

    def _on_solo(self, stem: str, solo: bool):
        self.playback.set_solo(stem, solo)

    def _on_eq(self, stem: str, low: float, mid: float, high: float):
        self.playback.set_eq(stem, low, mid, high)

    # ── GPU selector ──────────────────────────────────────

    def _on_gpu_changed(self, idx: int):
        gpu_idx = self.gpu_combo.currentData()
        self.config.gpu_index = gpu_idx
        self.separator.unload_model()
        device_name = "CPU" if gpu_idx is None else f"CUDA:{gpu_idx}"
        self.status_label.setText(f"Device changed to {device_name}. Model will reload on next separation.")

    # ── periodic UI refresh ───────────────────────────────

    def _on_position_tick(self, pos: int, total: int):
        """Called from audio thread — just store values."""
        self._last_pos = pos
        self._last_total = total

    _last_pos: int = 0
    _last_total: int = 1

    def _refresh_ui(self):
        if self._last_total > 0:
            secs = self._last_pos / self.playback._sr if self.playback._sr else 0
            self.transport.set_position(secs)
            self.waveform.set_position(self._last_pos / self._last_total)

    # ── cleanup ───────────────────────────────────────────

    def closeEvent(self, ev):
        self.playback.stop()
        self.separator.unload_model()
        super().closeEvent(ev)
