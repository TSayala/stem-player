"""Application-wide configuration and constants."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import torch
import os


APP_NAME = "StemDJ"
APP_VERSION = "0.1.0"
CACHE_DIR = Path(os.environ.get("STEMDJ_CACHE", Path.home() / ".stemdj" / "cache"))

# The 7 stems we produce: 6 from htdemucs_6s + vocal split
STEM_NAMES = ("lead_vocals", "back_vocals", "drums", "bass", "guitar", "piano", "other")
STEM_COLORS = {
    "lead_vocals": "#E06C75",
    "back_vocals": "#C678DD",
    "drums":       "#E5C07B",
    "bass":        "#61AFEF",
    "guitar":      "#98C379",
    "piano":       "#56B6C2",
    "other":       "#ABB2BF",
}

SUPPORTED_FORMATS = {".mp3", ".wav", ".flac", ".ogg", ".opus", ".m4a", ".aac", ".wma", ".aiff"}


def list_gpu_devices() -> list[dict]:
    """Return available CUDA devices with name and memory.

    Explicitly initialises the CUDA runtime first so that newer GPUs
    (e.g. RTX 5070Ti) are detected even when ``torch.cuda.is_available()``
    would lazily return False before initialisation.
    """
    devices = []
    try:
        if not torch.cuda.is_available():
            return devices
        # Force CUDA runtime init — required for some driver/GPU combos
        torch.cuda.init()
        for i in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(i)
            devices.append({
                "index": i,
                "name": props.name,
                "memory_gb": round(props.total_memory / 1e9, 1),
            })
    except Exception:
        pass
    return devices


@dataclass
class AppConfig:
    """Runtime configuration."""
    gpu_index: Optional[int] = None          # None = CPU
    demucs_model: str = "htdemucs_6s"        # 6-stem model
    opus_bitrate: int = 128                  # kbps per stem
    sample_rate: int = 44100
    buffer_frames: int = 2048                # audio callback buffer
    cache_dir: Path = field(default_factory=lambda: CACHE_DIR)

    @property
    def device(self) -> str:
        if self.gpu_index is not None and torch.cuda.is_available():
            return f"cuda:{self.gpu_index}"
        return "cpu"

    def __post_init__(self):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # Auto-select first available GPU if none specified
        if self.gpu_index is None:
            devs = list_gpu_devices()
            if devs:
                self.gpu_index = devs[0]["index"]
