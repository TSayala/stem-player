"""StemDJ — entry point."""

import sys
import os

# Enable Qt hardware-accelerated rendering
os.environ.setdefault("QSG_RHI_BACKEND", "opengl")

# ── Patch torchaudio to avoid torchcodec requirement ──────────────
# Newer torchaudio (2.6+) defaults to a "torchcodec" backend.  Its
# dispatcher calls ``load_with_torchcodec`` even before checking other
# backends, raising an error if torchcodec isn't installed.
#
# Strategy:
#   1. Suppress any import-time torchcodec probing via warnings + stderr
#   2. Replace ``torchaudio.load`` with a pure-soundfile implementation
#      so ALL callers (including Demucs internals) bypass torchaudio's
#      backend dispatcher entirely.
import warnings
import contextlib
import io
import torch
import soundfile as sf

# Some torchaudio versions probe torchcodec at import time
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    with contextlib.redirect_stderr(io.StringIO()):
        try:
            import torchaudio
        except Exception:
            pass  # will be imported by demucs anyway

def _soundfile_load(filepath, *args, **kwargs):
    """Drop-in replacement for torchaudio.load using soundfile."""
    data, sr = sf.read(str(filepath), dtype="float32")
    if data.ndim == 1:
        tensor = torch.from_numpy(data).unsqueeze(0)          # [1, samples]
    else:
        tensor = torch.from_numpy(data.T.copy()).contiguous()  # [channels, samples]
    return tensor, sr

# Patch on the module — catches Demucs and any other caller
if "torchaudio" in sys.modules:
    _ta = sys.modules["torchaudio"]
    _ta.load = _soundfile_load

    # Also patch torchaudio.info — demucs may call it, and it can also
    # trigger the torchcodec dispatcher.
    def _soundfile_info(filepath, *args, **kwargs):
        """Drop-in replacement for torchaudio.info using soundfile."""
        info = sf.info(str(filepath))
        # Return a simple namespace matching what callers expect
        class _Info:
            sample_rate = info.samplerate
            num_frames = info.frames
            num_channels = info.channels
        return _Info()

    _ta.info = _soundfile_info
# ──────────────────────────────────────────────────────────────────

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from config import AppConfig
from ui.main_window import MainWindow


def main():
    # High-DPI support
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("StemDJ")
    app.setApplicationVersion("0.1.0")

    # Set an explicit default font to prevent QFont::setPointSize(-1) warnings
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    # Enable OpenGL rendering for the widget pipeline
    app.setAttribute(Qt.AA_ShareOpenGLContexts, True)

    config = AppConfig()
    window = MainWindow(config)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
