"""Atomic writes and bounded cross-process locking on Linux."""

import os
import tempfile
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from baba_is_agent.errors import BridgeTimeoutError


def atomic_write(path: Path, text: str) -> None:
    """Replace a UTF-8 file without exposing a partially written request."""
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


@contextmanager
def game_lock(path: Path, timeout: float) -> Generator[None]:
    """Serialize complete batches across threads, clients, and server processes."""
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    deadline = time.monotonic() + timeout
    with path.open("a", encoding="utf-8") as stream:
        while True:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise BridgeTimeoutError(
                        "Another client is using the game; try again later"
                    ) from None
                time.sleep(0.025)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)
