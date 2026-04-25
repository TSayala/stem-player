"""Library panel — browse audio files in a folder, select + analyze + load."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QFrame, QAbstractItemView,
    QHeaderView,
)

from config import SUPPORTED_FORMATS


@dataclass
class LibraryEntry:
    """Runtime state for one library row."""
    path: Path
    title: str = ""
    artist: str = ""
    album: str = ""
    bpm: Optional[float] = None
    key: Optional[str] = None
    cached: bool = False


def _scan_folder(root: Path) -> list[Path]:
    """Recursively collect supported audio files under *root*."""
    out: list[Path] = []
    try:
        for p in sorted(root.rglob("*")):
            if p.is_file() and p.suffix.lower() in SUPPORTED_FORMATS:
                out.append(p)
    except (OSError, PermissionError):
        pass
    return out


class LibraryPanel(QFrame):
    """Bottom-of-window list of tracks in the chosen library folder.

    Emits:
        load_requested(Path)     — user double-clicked a row
        analyze_requested(list[Path]) — user clicked "Analyze Files"
    """

    load_requested = Signal(Path)
    analyze_requested = Signal(list)       # list[Path]
    add_folder_requested = Signal()

    COLS = ("Title", "Artist", "Album", "BPM", "Key", "File")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("background: #21252B; border-radius: 8px;")
        self._root: Optional[Path] = None
        self._entries: dict[Path, LibraryEntry] = {}
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        # Header row
        header = QHBoxLayout()
        header.setSpacing(8)

        self.header_label = QLabel("Library: (no folder selected)")
        self.header_label.setStyleSheet("font-size: 12px; color: #ABB2BF; font-weight: bold;")
        header.addWidget(self.header_label, 1)

        self.add_folder_btn = QPushButton("Add Folder…")
        self.add_folder_btn.setToolTip("Choose a folder to scan for audio files")
        self.add_folder_btn.clicked.connect(self._on_add_folder_clicked)
        header.addWidget(self.add_folder_btn)

        self.analyze_btn = QPushButton("Analyze Files")
        self.analyze_btn.setToolTip(
            "Run stem separation, BPM and key detection on the selected tracks"
        )
        self.analyze_btn.clicked.connect(self._on_analyze_clicked)
        self.analyze_btn.setEnabled(False)
        header.addWidget(self.analyze_btn)

        lay.addLayout(header)

        # Tree
        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(self.COLS))
        self.tree.setHeaderLabels(self.COLS)
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setUniformRowHeights(True)
        self.tree.setStyleSheet("""
            QTreeWidget {
                background: #1B1D23;
                alternate-background-color: #21252B;
                border: 1px solid #3E4451;
                border-radius: 6px;
            }
            QTreeWidget::item { padding: 4px 6px; }
            QTreeWidget::item:selected {
                background: #3E4451;
                color: #ffffff;
            }
            QHeaderView::section {
                background: #2C313A;
                color: #ABB2BF;
                padding: 4px;
                border: none;
                border-right: 1px solid #3E4451;
            }
        """)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)

        header_view = self.tree.header()
        header_view.setSectionResizeMode(0, QHeaderView.Stretch)         # Title
        header_view.setSectionResizeMode(1, QHeaderView.Interactive)     # Artist
        header_view.setSectionResizeMode(2, QHeaderView.Interactive)     # Album
        header_view.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # BPM
        header_view.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Key
        header_view.setSectionResizeMode(5, QHeaderView.Interactive)     # File
        self.tree.setColumnWidth(1, 160)
        self.tree.setColumnWidth(2, 160)
        self.tree.setColumnWidth(5, 280)

        lay.addWidget(self.tree, 1)

    # ── public API ────────────────────────────────────────

    def set_root(self, folder: Path):
        """Scan *folder* recursively and populate the tree."""
        self._root = folder
        self._entries.clear()
        self.tree.clear()

        files = _scan_folder(folder)
        self.header_label.setText(f"Library: {folder}   ({len(files)} tracks)")

        for p in files:
            entry = LibraryEntry(path=p, title=p.stem)
            self._entries[p] = entry
            self._add_row(entry)

    def update_entry(self, path: Path, *, title: str | None = None,
                     artist: str | None = None, album: str | None = None,
                     bpm: float | None = None, key: str | None = None,
                     cached: bool | None = None):
        """Merge in newly-read metadata / analysis for *path*."""
        entry = self._entries.get(path)
        if entry is None:
            return
        if title is not None:
            entry.title = title
        if artist is not None:
            entry.artist = artist
        if album is not None:
            entry.album = album
        if bpm is not None:
            entry.bpm = bpm
        if key is not None:
            entry.key = key
        if cached is not None:
            entry.cached = cached
        self._refresh_row(entry)

    def selected_paths(self) -> list[Path]:
        return [item.data(0, Qt.UserRole) for item in self.tree.selectedItems()]

    # ── internal ──────────────────────────────────────────

    def _add_row(self, entry: LibraryEntry):
        item = QTreeWidgetItem([
            entry.title,
            entry.artist,
            entry.album,
            f"{entry.bpm:.1f}" if entry.bpm else "",
            entry.key or "",
            str(entry.path),
        ])
        item.setData(0, Qt.UserRole, entry.path)
        item.setToolTip(0, str(entry.path))
        self.tree.addTopLevelItem(item)

    def _refresh_row(self, entry: LibraryEntry):
        # Find matching item and update
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.data(0, Qt.UserRole) == entry.path:
                item.setText(0, entry.title or entry.path.stem)
                item.setText(1, entry.artist)
                item.setText(2, entry.album)
                item.setText(3, f"{entry.bpm:.1f}" if entry.bpm else "")
                item.setText(4, entry.key or "")
                return

    def _on_add_folder_clicked(self):
        # Parent handles file dialog — bubble up via a distinct request
        # so it shares code with the menu entry.
        self.add_folder_requested.emit()

    def _on_analyze_clicked(self):
        paths = self.selected_paths()
        if paths:
            self.analyze_requested.emit(paths)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        path = item.data(0, Qt.UserRole)
        if isinstance(path, Path):
            self.load_requested.emit(path)

    def _on_selection_changed(self):
        self.analyze_btn.setEnabled(bool(self.tree.selectedItems()))
