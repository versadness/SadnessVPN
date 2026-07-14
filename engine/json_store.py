"""Crash-safe JSON persistence helpers for user-owned application data."""

from __future__ import annotations

import json
import os
import tempfile
import threading


_write_lock = threading.RLock()


def _atomic_write_bytes(path: str, payload: bytes) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.",
        suffix=".tmp",
        dir=directory,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            os.remove(temporary)
        except OSError:
            pass
        raise


def atomic_write_json(path: str, data, backup_path: str | None = None) -> None:
    """Replace a JSON file atomically, optionally preserving its valid predecessor."""
    payload = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    with _write_lock:
        if backup_path and os.path.isfile(path):
            try:
                with open(path, "rb") as stream:
                    previous = stream.read()
                json.loads(previous.decode("utf-8-sig"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                pass
            else:
                _atomic_write_bytes(backup_path, previous)

        _atomic_write_bytes(path, payload)
