"""Serialize publication of one cache entry across threads and processes."""

import os
import time
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def cache_lock(entry: Path, checkpoint=lambda: None):
    entry.parent.mkdir(parents=True, exist_ok=True)
    with entry.with_name(entry.name + ".lock").open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        while True:
            checkpoint()
            stream.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(0.05)
            except OSError as error:
                if os.name != "nt" or error.errno not in (13, 36):
                    raise
                time.sleep(0.05)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
