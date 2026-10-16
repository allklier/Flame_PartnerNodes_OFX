"""Colour conversion for the model (decision 5; LTX decisions 27/28/54: OCIO runs here, in the job).

From LTX Alpha Gen's worker colour.py (verified there against Flame's ACES 2.0 config):
  - config: $OCIO if set, else the newest Flame
    /opt/Autodesk/colour_mgmt/configs/flame_configs/<version>/aces2.0_config/config.ocio
  - transform: DisplayViewTransform(src, display, view), NOT config.getProcessor(src, display).
    A display colour space in an OCIO v2/ACES config is encoding-only; the tone mapping lives on
    the View. The plain path gave out-of-range values.
New here: the model returns a display-referred image, so it goes back to the source colour space
through the INVERSE of the same transform (TRANSFORM_DIR_INVERSE). The round trip is limited to the
SDR view's range (highlights above 100 nits clip), which is in the nature of an 8-bit sRGB model.
Flame's 2026.0 config is ocio_profile_version 2.4: PyOpenColorIO >= 2.4 (the runtime pins 2.6.0).
"""

from __future__ import annotations

import glob
import os

import numpy as np

DISPLAY = "Rec.1886 Rec.709 - Display"
VIEW = "ACES 2.0 - SDR 100 nits (Rec.709)"
FLAME_GLOB = "/opt/Autodesk/colour_mgmt/configs/flame_configs/*/aces2.0_config/config.ocio"

# Plugin dropdown label -> OCIO source colour space. "Bypass" = no conversion. Order matches the
# plugin's kColourSpaces (new entries go at the end: setups store the index).
SOURCES = {
    "Bypass": None,
    "ACEScg": "ACEScg",
    "LogC4": "ARRI LogC4",
    "Log3G10": "Log3G10 REDWideGamutRGB",
    "LogC3": "ARRI LogC3 (EI800)",
    "BMD Film Gen5": "BMDFilm WideGamut Gen5",
}


def _version_key(path: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in os.path.basename(os.path.dirname(os.path.dirname(path))).split("."))
    except ValueError:
        return (0,)


def default_config() -> str:
    """$OCIO, else the newest Flame ACES 2.0 config, else ''."""
    env = os.environ.get("OCIO", "").strip()
    if env:
        return env
    found = glob.glob(FLAME_GLOB)
    return max(found, key=_version_key) if found else ""


class Converter:
    """Source colour space <-> Rec.1886 display values through the fixed ACES 2.0 SDR view."""

    def __init__(self, label: str, config_path: str = "") -> None:
        if label not in SOURCES:
            raise ValueError(f"unknown input colour '{label}' (expected one of {', '.join(SOURCES)})")
        self.label, self.source = label, SOURCES[label]
        self.config_path = ""
        self._fwd = self._inv = None
        if self.source is None:
            return
        import PyOpenColorIO as ocio  # in the runtime venv; only needed when converting

        self.config_path = config_path or default_config()
        if not self.config_path:
            raise ValueError("no OCIO config: set $OCIO or install Flame's ACES 2.0 config")
        config = ocio.Config.CreateFromFile(self.config_path)
        if config.getColorSpace(self.source) is None:
            raise ValueError(f"colour space '{self.source}' is not in {self.config_path}")
        t = ocio.DisplayViewTransform()
        t.setSrc(self.source)
        t.setDisplay(DISPLAY)
        t.setView(VIEW)
        self._fwd = config.getProcessor(t, ocio.TRANSFORM_DIR_FORWARD).getDefaultCPUProcessor()
        self._inv = config.getProcessor(t, ocio.TRANSFORM_DIR_INVERSE).getDefaultCPUProcessor()

    @property
    def active(self) -> bool:
        return self._fwd is not None

    @staticmethod
    def _apply(cpu, image: np.ndarray) -> np.ndarray:
        arr = np.array(image, dtype=np.float32, copy=True, order="C")
        if cpu is not None:
            cpu.applyRGB(arr.reshape(-1, 3))  # in place on the contiguous copy
        return arr

    def to_display(self, image: np.ndarray) -> np.ndarray:
        """(H,W,3) source colour space -> float32 display-referred values (new array)."""
        return self._apply(self._fwd, image)

    def from_display(self, image: np.ndarray) -> np.ndarray:
        """(H,W,3) display-referred values in [0,1] -> float32 source colour space (new array)."""
        return self._apply(self._inv, image)

    def describe(self) -> str:
        if self._fwd is None:
            return "colour: Bypass (frames used as display-referred)"
        return f"colour: {self.source} <-> {DISPLAY} / {VIEW} (config {self.config_path})"
