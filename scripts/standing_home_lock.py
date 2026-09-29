"""Serialize cooperating writers of the four global agent instruction homes."""

from __future__ import annotations

import fcntl
import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


LOCK_PATH = Path.home() / ".bb" / ".agent-config-kit-home-writers.lock"


@contextmanager
def exclusive_home_writer(*, blocking: bool = True) -> Iterator[None]:
    """Hold the per-user instruction-home lock until the writer finishes."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(LOCK_PATH, flags, 0o600)
    locked = False
    try:
        opened = os.fstat(fd)
        path_stat = LOCK_PATH.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != os.getuid()
            or stat.S_ISLNK(path_stat.st_mode)
            or (opened.st_dev, opened.st_ino) != (path_stat.st_dev, path_stat.st_ino)
        ):
            raise RuntimeError(f"unsafe instruction-home lock file: {LOCK_PATH}")
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        locked = True
        yield
    finally:
        if locked:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
