"""Portable GUI entry point that never reads the default user data directory."""

from __future__ import annotations

import sys
from pathlib import Path

from run_gui import main


def _data_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "EdgeIEManager-Clean-Data"
    return Path(__file__).resolve().parent / "_clean-data"


if __name__ == "__main__":
    base_dir = _data_dir()
    base_dir.mkdir(parents=True, exist_ok=True)
    raise SystemExit(main(str(base_dir / "config.json")))
