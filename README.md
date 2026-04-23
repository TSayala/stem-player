# StemDJ

A standalone DJ player that separates audio into 7 stems and lets you mix them in real-time.

## Stems

| Stem | Source |
|------|--------|
| Lead Vocals | Centre-panned content from Demucs vocal stem |
| Back Vocals | Side-panned content from Demucs vocal stem |
| Drums | Demucs `htdemucs_6s` |
| Bass | Demucs `htdemucs_6s` |
| Guitar | Demucs `htdemucs_6s` |
| Piano | Demucs `htdemucs_6s` |
| Other | Demucs `htdemucs_6s` |

## Features

- **7-stem separation** via Demucs with GPU acceleration
- **Opus caching** — stems stored at ~128 kbps per stem (~90% smaller than WAV)
- **Per-stem mixer** — volume fader, mute, solo, 3-band EQ
- **Waveform display** — colour-coded per stem
- **BPM & key detection** on import
- **Tempo & pitch controls** via rubberband
- **GPU selection** — choose which CUDA device to use
- **Hardware-accelerated UI** — PySide6 with OpenGL RHI backend
- **Drag & drop** audio files

## Prerequisites

- Python 3.10+
- **ffmpeg** on PATH (required for Opus encoding/decoding)
- CUDA toolkit (optional, for GPU acceleration)

## Setup

```bash
# Create a virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Install rubberband (optional, for tempo/pitch)
pip install pyrubberband
# Note: pyrubberband requires the rubberband CLI tool on PATH
```

## Run

```bash
python main.py
```

## Build standalone .exe (Windows)

```bash
python build.py
```

Output will be in `dist/StemDJ/`.

## Usage

1. Launch the app
2. Open an audio file (Ctrl+O) or drag & drop
3. Wait for stem separation (first time only — cached afterward)
4. Use the mixer strips to mute/solo/EQ individual stems
5. Adjust tempo and pitch with the transport controls
