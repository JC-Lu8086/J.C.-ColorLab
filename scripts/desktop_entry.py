"""Minimal entry point used by the native PyInstaller launcher."""

from __future__ import annotations

import multiprocessing
import runpy


if __name__ == "__main__":
    multiprocessing.freeze_support()
    runpy.run_module("jc_colorlab", run_name="__main__")

