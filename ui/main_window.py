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
    QFrame, QApplication, QSplitter,
)

from config import AppConfig, SUPPORTED_FORMATS, list_gpu_devices
from engine.separator import Separator
from engine.playback import PlaybackEngine
from engine.stem_cache import StemCache
from engine.analyzer import detect_bpm, detect_key
from engine.metadata import read_metadata, TrackMetadata
from ui.theme import STYLESHEET
from ui.waveform import WaveformWidget
from ui.stem_controls import StemMixer, order_stems
from ui.transport import TransportBar
from ui.metadata_panel import TrackInfoPanel
from ui.library_panel import LibraryPanel

log = logging.getLogger(__name__)


# ── background separation worker ─────────────────────────────────────

class _SeparationWorker(QObject):
    """Separates + analyses a single file, emitting stems + metadata."""
    progress = Signal(str, float)     # message, fraction
    finished = Signal(dict, int, dict)  # stems, sr, analysis {bpm, key}
    error = Signal(str)

    def __init__(self, separator: Separator, cache: StemCache, path: Path):
        super().__init__()
        self.separator = separator
        self.cache = cache
        self.path = path

    @Slot()
    def run(self):
        try:
            if self.cache.is_cached(self.path):
                self.progress.emit("Loading cached stems…", 0.5)
                stems, sr = self.cache.load_stems(self.path)
                analysis = self.cache.load_manifest(self.path)
                self.finished.emit(stems, sr, analysis)
                return

            stems, sr = self.separator.separate(
                self.path,
                progress_cb=lambda msg, frac: self.progress.emit(msg, frac),
            )

            self.progress.emit("Caching stems as Opus…", 0.92)

            first_stem = next(iter(stems.values()))
            bpm = detect_bpm(first_stem, sr)
            key = detect_key(first_stem, sr)
            metadata = {"bpm": round(bpm, 1), "key": key}

            self.cache.save_stems(self.path, stems, sr, metadata)
            self.finished.emit(stems, sr, metadata)

        except Exception as e:
            log.exception("Separation failed for %s", self.path)
            self.error.emit(str(e))


# ── background batch analyse worker ──────────────────────────────────

class _BatchAnalyzeWorker(QObject):
    """Analyses a list of files — stems, BPM, key — caching each."""
    file_started = Signal(Path)
    file_finished = Signal(Path, dict)   # path, {bpm, key}
    progress = Signal(str, float)
    error = Signal(Path, str)
    finished = Signal()

    def __init__(self, separator: Separator, cache: StemCache, paths: list[Path]):
        super().__init__()
        self.separator = separator
        self.cache = cache
        self.paths = list(paths)
        self._stop = False

    @Slot()
    def stop(self):
        self._stop = True

    @Slot()
    def run(self):
        total = len(self.paths)
        for i, path in enumerate(self.paths):
            if self._stop:
                break
            self.file_started.emit(path)
            try:
                if self.cache.is_cached(path):
                    meta = self.cache.load_manifest(path)
                    self.file_finished.emit(path, meta)
                    continue

                def cb(msg, frac, idx=i):
                    self.progress.emit(
                        f"[{idx + 1}/{total}] {msg}",
                        (idx + frac) / total,
                    )

                stems, sr = self.separator.separate(path, progress_cb=cb)
                first_stem = next(iter(stems.values()))
                bpm = detect_bpm(first_stem, sr)
                key = detect_key(first_stem, sr)
                meta = {"bpm": round(bpm, 1), "key": key}
                self.cache.save_stems(path, stems, sr, meta)
                self.file_finished.emit(path, meta)
            except Exception as e:
                log.exception("Batch analysis failed for %s", path)
                self.error.emit(path, str(e))
        self.finished.emit()


# ── background tempo/pitch rebuild worker ────────────────────────────

class _RebuildWorker(QObject):
    """Runs the (heavy) pyrubberband rebuild off the UI thread."""
    finished = Signal()

    def __init__(self, playback: PlaybackEngine):
        super().__init__()
        self.playback = playback

    @Slot()
    def run(self):
        try:
            self.playback._rebuild_if_dirty()
        except Exception:
            log.exception("Rebuild worker failed")
        finally:
            self.finished.emit()


# ── main window ──────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self.separator = Separator(config)
        self.cache = StemCache(config)
        self.playback = PlaybackEngine(config)

        self._current_path: Optional[Path] = None
        self._current_meta: Optional[TrackMetadata] = None
        self._worker_thread: Optional[QThread] = None
        self._analyze_thread: Optional[QThread] = None
        self._analyze_worker: Optional[_BatchAnalyzeWorker] = None

        # Tempo/pitch rebuild background state
        self._rebuild_thread: Optional[QThread] = None
        self._rebuild_busy: bool = False
        self._rebuild_queued: bool = False

        self._setup_window()
        self._build_ui()
        self._connect_signals()
        self._setup_timers()

    # ── window setup ──────────────────────────────────────

    def _setup_window(self):
        self.setWindowTitle("StemDJ")
        self.resize(1250, 820)
        self.setAcceptDrops(True)
        self.setStyleSheet(STYLESHEET)

        menu = self.menuBar()
        file_menu = menu.addMenu("&File")

        open_action = QAction("&Open Audio…", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._on_open)
        file_menu.addAction(open_action)

        add_lib_action = QAction("Add &Library Folder…", self)
        add_lib_action.setShortcut("Ctrl+L")
        add_lib_action.triggered.connect(self._on_add_library_folder)
        file_menu.addAction(add_lib_action)

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

        # Top bar — GPU selector only (track info moved under waveform)
        info_bar = QHBoxLayout()
        info_bar.setSpacing(16)
        info_bar.addStretch(1)

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

        # Splitter lets user resize the library vs the deck
        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        # ── deck: waveform + transport + (track info | stem mixer) ──
        deck = QWidget()
        deck_lay = QVBoxLayout(deck)
        deck_lay.setContentsMargins(0, 0, 0, 0)
        deck_lay.setSpacing(6)

        self.waveform = WaveformWidget()
        deck_lay.addWidget(self.waveform, 2)

        self.transport = TransportBar()
        deck_lay.addWidget(self.transport)

        # Track info (album art + tags) on the left, stem mixer on the right.
        mix_row = QHBoxLayout()
        mix_row.setSpacing(8)
        self.track_info = TrackInfoPanel()
        self.track_info.setFixedWidth(340)
        mix_row.addWidget(self.track_info)

        self.mixer = StemMixer()
        mix_row.addWidget(self.mixer, 1)

        deck_lay.addLayout(mix_row, 3)

        splitter.addWidget(deck)

        # ── library panel (bottom) ────────────────────────
        self.library = LibraryPanel()
        splitter.addWidget(self.library)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([520, 300])

        # ── progress bar (hidden until needed) ────────────
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(18)
        root.addWidget(self.progress_bar)

        self.status_label = QLabel("Ready — drop an audio file, press Ctrl+O, or add a library folder")
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
        self.transport.loop_toggled.connect(self._on_loop_toggled)

        self.waveform.seek_requested.connect(self._on_seek)

        self.mixer.volume_changed.connect(self._on_volume)
        self.mixer.mute_changed.connect(self._on_mute)
        self.mixer.solo_changed.connect(self._on_solo)
        self.mixer.eq_changed.connect(self._on_eq)

        self.library.add_folder_requested.connect(self._on_add_library_folder)
        self.library.load_requested.connect(self._on_library_load_requested)
        self.library.analyze_requested.connect(self._on_analyze_requested)

        self.playback.on_position_changed = self._on_position_tick

    def _setup_timers(self):
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
        if self._analyze_thread is not None and self._analyze_thread.isRunning():
            QMessageBox.warning(
                self, "Busy",
                "An analysis job is running. Please wait for it to finish.",
            )
            return

        # Block deck-replacement while playing
        if self.playback.is_playing:
            QMessageBox.information(
                self, "Deck busy",
                "Stop playback before loading a different track.",
            )
            return

        self._current_path = path
        self.playback.stop()

        self._current_meta = read_metadata(path)
        self.track_info.set_metadata(self._current_meta)
        self.track_info.set_analysis(None, None)

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setText(f"Processing {path.name}…")

        self._worker_thread = QThread()
        worker = _SeparationWorker(self.separator, self.cache, path)
        worker.moveToThread(self._worker_thread)

        self._worker_thread.started.connect(worker.run)
        worker.progress.connect(self._on_worker_progress)
        worker.finished.connect(self._on_worker_finished)
        worker.error.connect(self._on_worker_error)
        worker.finished.connect(self._worker_thread.quit)
        worker.error.connect(self._worker_thread.quit)
        self._worker = worker  # keep ref

        self._worker_thread.start()

    @Slot(str, float)
    def _on_worker_progress(self, msg: str, frac: float):
        self.progress_bar.setValue(int(frac * 100))
        self.status_label.setText(msg)

    @Slot(dict, int, dict)
    def _on_worker_finished(self, stems: dict, sr: int, analysis: dict):
        self.progress_bar.setVisible(False)
        self.status_label.setText("Ready")

        # Canonical stem order
        ordered = {k: stems[k] for k in order_stems(stems.keys())}

        self.playback.load_stems(ordered, sr)
        self.playback.set_loop(self.transport.loop_btn.isChecked())

        self.waveform.set_stems(ordered, sr)
        self.mixer.set_stems(list(ordered.keys()))
        self.transport.set_duration(self.playback.duration_seconds)

        bpm = analysis.get("bpm")
        key = analysis.get("key")
        self.track_info.set_analysis(bpm, key)

        # Reflect analysis into library row if present
        if self._current_path is not None:
            self.library.update_entry(self._current_path, bpm=bpm, key=key, cached=True)

    @Slot(str)
    def _on_worker_error(self, msg: str):
        self.progress_bar.setVisible(False)
        self.status_label.setText("Error")
        QMessageBox.critical(self, "Separation Error", msg)

    # ── transport handlers ────────────────────────────────

    def _on_play_toggle(self):
        self.playback.toggle_play()
        self.transport.set_playing(self.playback.is_playing)

    def _on_stop(self):
        self.playback.stop()
        self.transport.set_playing(False)
        self.transport.set_position(0)
        self.waveform.set_position(0)

    def _on_seek(self, seconds: float):
        self.playback.seek(seconds)

    def _on_loop_toggled(self, enabled: bool):
        self.playback.set_loop(enabled)

    def _on_tempo(self, ratio: float):
        self.playback.set_tempo(ratio)
        self._schedule_rebuild()

    def _on_pitch(self, semitones: float):
        self.playback.set_pitch(semitones)
        self._schedule_rebuild()

    # ── background rebuild orchestration ──────────────────

    def _schedule_rebuild(self):
        """Kick off a background rebuild; coalesces rapid changes."""
        # Don't rebuild while the audio stream is active — stopping /
        # restarting the stream is expensive and the rebuild would stall
        # playback. The change is cached in the engine and will apply the
        # next time play() is called.
        if self.playback.is_playing:
            self.status_label.setText("Tempo/pitch change will apply on next play")
            return

        if self._rebuild_busy:
            self._rebuild_queued = True
            return
        self._rebuild_busy = True

        thread = QThread(self)
        worker = _RebuildWorker(self.playback)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_rebuild_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._rebuild_thread = thread
        self._rebuild_worker = worker
        thread.start()

    @Slot()
    def _on_rebuild_finished(self):
        self._rebuild_busy = False
        if self._rebuild_queued:
            self._rebuild_queued = False
            self._schedule_rebuild()
        else:
            # Duration may have changed after time-stretching
            self.transport.set_duration(self.playback.duration_seconds)

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

    # ── library ───────────────────────────────────────────

    def _on_add_library_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Choose Library Folder", "",
        )
        if not folder:
            return
        root = Path(folder)
        self.library.set_root(root)
        self.status_label.setText(f"Scanning library: {root}")

        # Populate metadata + cached flag in a light pass (no separation).
        for i in range(self.library.tree.topLevelItemCount()):
            item = self.library.tree.topLevelItem(i)
            path = item.data(0, Qt.UserRole)
            if not isinstance(path, Path):
                continue
            meta = read_metadata(path)
            cached = self.cache.is_cached(path)
            manifest_meta = {}
            if cached:
                try:
                    manifest_meta = self.cache.load_manifest(path)
                except Exception:
                    manifest_meta = {}
            self.library.update_entry(
                path,
                title=meta.display_title,
                artist=meta.artist,
                album=meta.album,
                bpm=manifest_meta.get("bpm"),
                key=manifest_meta.get("key"),
                cached=cached,
            )
        self.status_label.setText(f"Library ready: {root}")

    def _on_library_load_requested(self, path: Path):
        if self.playback.is_playing:
            QMessageBox.information(
                self, "Deck busy",
                "Stop playback before loading a different track.",
            )
            return
        self._load_file(path)

    def _on_analyze_requested(self, paths: list[Path]):
        if self._analyze_thread is not None and self._analyze_thread.isRunning():
            QMessageBox.information(
                self, "Busy",
                "An analysis job is already running.",
            )
            return
        if self._worker_thread is not None and self._worker_thread.isRunning():
            QMessageBox.information(
                self, "Busy",
                "A file is being processed. Please wait for it to finish.",
            )
            return
        if not paths:
            return

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setText(f"Analyzing {len(paths)} file(s)…")

        thread = QThread()
        worker = _BatchAnalyzeWorker(self.separator, self.cache, paths)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_analyze_progress)
        worker.file_finished.connect(self._on_analyze_file_finished)
        worker.error.connect(self._on_analyze_error)
        worker.finished.connect(self._on_analyze_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._analyze_thread = thread
        self._analyze_worker = worker
        thread.start()

    @Slot(str, float)
    def _on_analyze_progress(self, msg: str, frac: float):
        self.progress_bar.setValue(int(frac * 100))
        self.status_label.setText(msg)

    @Slot(Path, dict)
    def _on_analyze_file_finished(self, path: Path, meta: dict):
        self.library.update_entry(
            path,
            bpm=meta.get("bpm"),
            key=meta.get("key"),
            cached=True,
        )

    @Slot(Path, str)
    def _on_analyze_error(self, path: Path, msg: str):
        log.warning("Analyze error for %s: %s", path, msg)

    @Slot()
    def _on_analyze_finished(self):
        self.progress_bar.setVisible(False)
        self.status_label.setText("Analysis complete")
        self._analyze_thread = None
        self._analyze_worker = None

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

        # Reflect audio thread transitioning to stopped (e.g. end of track
        # reached with loop off) back into the play button.
        if not self.playback.is_playing and self.transport.play_btn.text() == "⏸":
            self.transport.set_playing(False)

    # ── cleanup ───────────────────────────────────────────

    def closeEvent(self, ev):
        if self._analyze_worker is not None:
            self._analyze_worker.stop()
        self.playback.stop()
        self.separator.unload_model()
        super().closeEvent(ev)
