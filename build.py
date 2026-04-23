"""Build script — run:  python build.py"""

import subprocess
import sys


def main():
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "StemDJ",
        "--onedir",
        "--windowed",
        "--noconfirm",
        "--add-data", "config.py;.",
        "--hidden-import", "demucs",
        "--hidden-import", "demucs.pretrained",
        "--hidden-import", "demucs.apply",
        "--hidden-import", "demucs.hdemucs",
        "--hidden-import", "PySide6.QtOpenGL",
        "--hidden-import", "sounddevice",
        "--hidden-import", "soundfile",
        "--collect-data", "demucs",
        "--collect-data", "torch",
        "main.py",
    ]
    subprocess.run(cmd, check=True)
    print("\n✅ Build complete — output in dist/StemDJ/")


if __name__ == "__main__":
    main()
