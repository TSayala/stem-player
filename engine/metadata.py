"""Audio file metadata + embedded cover art extraction.

Uses mutagen when available; falls back to a filename-only TrackMetadata
otherwise so nothing crashes on unusual containers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class TrackMetadata:
    path: Path
    title: str = ""
    artist: str = ""
    album: str = ""
    cover: Optional[bytes] = None  # raw image bytes (jpeg / png)

    @property
    def display_title(self) -> str:
        return self.title or self.path.stem

    @property
    def display_artist(self) -> str:
        return self.artist or "Unknown Artist"


def read_metadata(path: Path) -> TrackMetadata:
    """Read tags + embedded cover art for an audio file.

    Never raises — returns a TrackMetadata with at least a title derived
    from the filename if tag parsing fails.
    """
    meta = TrackMetadata(path=path)
    try:
        import mutagen
        from mutagen.id3 import ID3, APIC
        from mutagen.flac import FLAC, Picture
        from mutagen.mp4 import MP4
    except ImportError:
        return meta

    try:
        f = mutagen.File(str(path))
    except Exception:
        return meta

    if f is None:
        return meta

    # Generic tag lookup (mutagen.File exposes .tags on most formats)
    def _get(keys) -> str:
        for k in keys:
            try:
                val = f.get(k)
            except Exception:
                val = None
            if val:
                if isinstance(val, list):
                    val = val[0]
                s = str(val).strip()
                if s:
                    return s
        return ""

    meta.title = _get(["title", "TIT2", "\xa9nam", "TITLE"])
    meta.artist = _get(["artist", "TPE1", "\xa9ART", "ARTIST"])
    meta.album = _get(["album", "TALB", "\xa9alb", "ALBUM"])

    # Cover extraction (format-specific)
    try:
        # ID3 (MP3, WAV with ID3, AIFF)
        if hasattr(f, "tags") and f.tags is not None:
            for key in f.tags.keys() if hasattr(f.tags, "keys") else []:
                if key.startswith("APIC"):
                    apic = f.tags[key]
                    if hasattr(apic, "data"):
                        meta.cover = apic.data
                        break
        # FLAC
        if meta.cover is None and hasattr(f, "pictures") and f.pictures:
            meta.cover = f.pictures[0].data
        # MP4 / M4A
        if meta.cover is None and hasattr(f, "tags") and f.tags is not None:
            covr = f.tags.get("covr")
            if covr:
                first = covr[0]
                meta.cover = bytes(first) if hasattr(first, "__bytes__") or isinstance(first, (bytes, bytearray)) else None
    except Exception:
        pass

    return meta
