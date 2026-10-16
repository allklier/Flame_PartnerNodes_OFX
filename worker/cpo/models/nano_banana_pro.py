"""Nano Banana Pro = Google Gemini 3 Pro Image on Comfy Router (vertexai/gemini-3-pro-image), the
backend of ComfyUI's GeminiImage2Node. Request and response: the gemini family (gemini.py)."""

from __future__ import annotations

from . import gemini

MODEL_ID = "vertexai/gemini-3-pro-image"


def reference_pixels(params: dict) -> int:
    return {"1K": 1024 * 1024, "2K": 2048 * 2048}.get(params.get("resolution"), 4096 * 4096)


def build_request(router, params: dict, refs: list, log) -> dict:
    return gemini.build_body(params, refs)


def result_images(router, response: dict) -> list:
    return gemini.images_from_response(router, response)
