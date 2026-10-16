"""Freeze the engine into one executable for the desktop app's sidecar slot.

    python scripts/freeze.py   # writes ../app/src-tauri/binaries/medtimeline-engine-<target triple>[.exe]

Tauri looks for sidecars named with the Rust target triple, so the triple comes from `rustc -vV`
(or $TARGET_TRIPLE when cross-building).
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
OUT = ENGINE.parent / "app" / "src-tauri" / "binaries"


def target_triple() -> str:
    if os.environ.get("TARGET_TRIPLE"):
        return os.environ["TARGET_TRIPLE"]
    info = subprocess.run(["rustc", "-vV"], capture_output=True, text=True, check=True).stdout
    return next(line.split(": ", 1)[1] for line in info.splitlines() if line.startswith("host: "))


def main() -> None:
    work = ENGINE / "build" / "freeze"
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--onefile", "--noconfirm", "--clean",
        "--name", "medtimeline-engine",
        "--collect-data", "medtimeline",       # demo/records.json
        "--collect-submodules", "medtimeline",  # extractors register themselves on import
        "--hidden-import", "anthropic",
        "--hidden-import", "pymupdf",           # imported lazily when a PDF arrives
        "--collect-data", "docx",               # python-docx needs its template files
        "--distpath", str(work / "dist"), "--workpath", str(work / "build"), "--specpath", str(work),
        str(HERE / "engine_entry.py"),
    ], check=True)
    ext = ".exe" if sys.platform == "win32" else ""
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / f"medtimeline-engine-{target_triple()}{ext}"
    shutil.copy2(work / "dist" / f"medtimeline-engine{ext}", dest)
    print(f"wrote {dest}")


if __name__ == "__main__":
    main()
