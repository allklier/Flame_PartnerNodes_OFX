"""Result cache, writer side. Layout must match ofx/src/core/cache.h:
  <root>/<k[0:2]>/<key>.img    b"CPOI" u32 version W H 1 3, then H*W*3 float16, rows top-down
  <root>/pending/<key>         holds the pid of the job generating it
  <root>/jobs/<job id>.json    final job status, read by the plugin
"""

from __future__ import annotations

import json
import os
import struct
import time

import numpy as np

VERSION = 1
HEADER = struct.Struct("<4sIIIII")  # 24 bytes, ofx/src/core/cache.h FrameFileHeader
IN_MAGIC = b"CPOA"   # staged reference frame: float32 RGB
OUT_MAGIC = b"CPOI"  # result: float16 RGB


def result_path(root: str, key: str) -> str:
    return os.path.join(root, key[:2], key + ".img")


def pending_path(root: str, key: str) -> str:
    return os.path.join(root, "pending", key)


def read_staged(path: str) -> np.ndarray:
    """The plugin's staged reference frame -> (H,W,3) float32, rows top-down."""
    with open(path, "rb") as f:
        magic, version, w, h, n, c = HEADER.unpack(f.read(HEADER.size))
        if magic != IN_MAGIC or version != VERSION or n != 1 or c != 3:
            raise ValueError(f"bad staged frame header {magic!r} v{version} n={n} c={c}")
        data = np.fromfile(f, dtype="<f4", count=h * w * 3)
    if data.size != h * w * 3:
        raise ValueError(f"short staged frame: {data.size} of {h * w * 3} values")
    return data.reshape(h, w, 3)


def write_result(root: str, key: str, image: np.ndarray) -> str:
    """Atomic: a temp file in the target folder, then rename over the final name."""
    h, w, c = image.shape
    if c != 3:
        raise ValueError(f"result must be RGB, got {c} channels")
    path = result_path(root, key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "wb") as f:
        f.write(HEADER.pack(OUT_MAGIC, VERSION, w, h, 1, 3))
        np.ascontiguousarray(image, dtype="<f2").tofile(f)
    os.replace(tmp, path)
    return path


def mark_pending(root: str, key: str, pid: int) -> None:
    os.makedirs(os.path.join(root, "pending"), exist_ok=True)
    with open(pending_path(root, key), "w") as f:
        f.write(str(pid))


def clear_pending(root: str, key: str) -> None:
    try:
        os.unlink(pending_path(root, key))
    except FileNotFoundError:
        pass


def write_status(root: str, job_id: str, state: str, message: str = "", **extra) -> None:
    """state: running | done | failed | cancelled. Read by the plugin (partner_effect.cpp jsonField)."""
    d = os.path.join(root, "jobs")
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, f".{job_id}.tmp")
    with open(tmp, "w") as f:
        json.dump({"state": state, "message": message, "time": time.time(), **extra}, f)
    os.replace(tmp, os.path.join(d, job_id + ".json"))
