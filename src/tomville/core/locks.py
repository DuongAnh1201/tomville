"""Bounded advisory locks; never hold these across network/subprocess calls."""
from contextlib import contextmanager
import fcntl
import os
import time


@contextmanager
def file_lock(path, *, timeout=1):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('file lock timed out') from None
                time.sleep(.01)
        yield
    finally:
        os.close(fd)
