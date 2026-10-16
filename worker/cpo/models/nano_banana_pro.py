"""Nano Banana Pro = Google Gemini 3 Pro Image on Comfy Router (vertexai/gemini-3-pro-image), the
backend of ComfyUI's GeminiImage2Node. Request and response: the gemini family (gemini.py)."""

from __future__ import annotations

from . import gemini

MODEL_ID = "vertexai/gemini-3-pro-image"


def build_request(router, params: dict, refs: list, log) -> dict:
    return gemini.build_body(params, refs)


def result_images(router, response: dict) -> list:
    return gemini.images_from_response(router, response)
