#!/usr/bin/env python3
"""Validate the installed UI/UX skill from its own filesystem location."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    scripts_dir = Path(__file__).resolve().parent
    subprocess.run(
        [sys.executable, str(scripts_dir / "validate_data.py")],
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            str(scripts_dir / "tests"),
            "-p",
            "test_*.py",
        ],
        check=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
