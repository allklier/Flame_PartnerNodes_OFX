"""Model modules (decision 2). Each worker/cpo/models/<module>.py provides:

  MODEL_ID                                  Router model id, e.g. "krea/krea-3"
  build_request(router, params, refs, log) -> dict
                                            the Router request body; refs are 8-bit sRGB PNGs
                                            (bytes), uploaded or inlined however the model needs
  result_images(router, response) -> list[bytes]
                                            the generated images (PNG/JPEG bytes) in the response

params are the plugin's strings (model_spec.h): choices as their label, booleans "1"/"0".
Shared code per request format lives in family modules (common.py, gemini.py); a model module
should be little more than its MODEL_ID and parameter mapping. Every model listed in the C++ specs
runs through tests/test_models_contract.py against the fake Router (a fixture per module).
"""

from __future__ import annotations

import importlib
import re

FAMILY_MODULES = {"common", "gemini"}  # helpers, not models


def load(name: str):
    if not re.fullmatch(r"[a-z0-9_]+", name or "") or name in FAMILY_MODULES:
        raise ValueError(f"bad model module name {name!r}")
    return importlib.import_module(f"cpo.models.{name}")
