"""Images between Flame's float frames and the model's 8-bit sRGB PNGs (Pillow)."""

from __future__ import annotations

import io
import math

import numpy as np
from PIL import Image


def to_png(display: np.ndarray, max_pixels: int = 0) -> bytes:
    """(H,W,3) display-referred float -> 8-bit PNG, scaled down (never up) to at most max_pixels.
    ComfyUI's Krea node does the same before upload (nodes_krea.py tensor_to_bytesio total_pixels)."""
    arr = (np.clip(display, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    img = Image.fromarray(arr, "RGB")
    if max_pixels and img.width * img.height > max_pixels:
        s = math.sqrt(max_pixels / (img.width * img.height))
        img = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def fill_crop(data: bytes, width: int, height: int) -> np.ndarray:
    """Decision 9: the model's image scaled to cover width x height, centre-cropped.
    Returns (height,width,3) float32 display-referred values in [0,1]."""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    s = max(width / img.width, height / img.height)
    sw, sh = max(width, round(img.width * s)), max(height, round(img.height * s))
    if (sw, sh) != img.size:
        img = img.resize((sw, sh), Image.LANCZOS)
    x0, y0 = (sw - width) // 2, (sh - height) // 2
    img = img.crop((x0, y0, x0 + width, y0 + height))
    return np.asarray(img, dtype=np.float32) / 255.0
