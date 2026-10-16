"""Family helper: Google Gemini image models on Comfy Router (vertexai/...), native Gemini format.

Router schema (GET /v2/models/vertexai/gemini-3-pro-image/openapi.json, 2026-10-16): body
{contents: [{role, parts: [{text} | {inlineData: {mimeType, data(base64)}} | {fileData}]}],
generationConfig: {responseModalities, imageConfig, seed, ...}, systemInstruction: {parts}};
the response is Gemini's own: candidates[].content.parts[] with inlineData (base64) or fileData,
promptFeedback.blockReason when refused. The request shape follows ComfyUI's GeminiImage2Node
(nodes_gemini.py): text part first, then the images; imageConfig {imageSize, aspectRatio (omitted
for auto)}. Differences: references go inline as base64 (ComfyUI uploads them to its storage), the
seed is sent (generationConfig.seed exists in the schema), and responses ask for TEXT+IMAGE so a
refusal comes with the model's explanation.
"""

from __future__ import annotations

import base64

from .common import require_prompt, resolve_image_refs

SYSTEM_PROMPT = ("Always respond with an image. Treat the user's text as instructions for the picture "
                 "to create or the edit to make to the attached image.")


def build_body(params: dict, refs: list) -> dict:
    prompt = resolve_image_refs(require_prompt(params), len(refs))
    parts = [{"text": prompt}]
    for png in refs:
        parts.append({"inlineData": {"mimeType": "image/png", "data": base64.b64encode(png).decode("ascii")}})
    image_config = {"imageSize": params.get("resolution", "1K")}
    if params.get("aspectRatio", "auto") != "auto":
        image_config["aspectRatio"] = params["aspectRatio"]
    config = {"responseModalities": ["TEXT", "IMAGE"], "imageConfig": image_config}
    if params.get("seed"):
        config["seed"] = int(params["seed"])
    return {"contents": [{"role": "user", "parts": parts}], "generationConfig": config,
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]}}


def images_from_response(router, response: dict) -> list:
    response = response or {}
    candidates = response.get("candidates") or []
    if not candidates:
        fb = response.get("promptFeedback") or {}
        if fb.get("blockReason"):
            raise ValueError(f"Gemini refused the request: {fb['blockReason']} {fb.get('blockReasonMessage', '')}".strip())
        raise ValueError(f"Gemini returned no result ({str(response)[:200]})")
    images, texts, reasons = [], [], []
    for c in candidates:
        if (c.get("finishReason") or "").upper() not in ("", "STOP"):
            reasons.append(c["finishReason"])
        for part in (c.get("content") or {}).get("parts") or []:
            if part.get("thought"):
                continue
            if part.get("inlineData", {}).get("data"):
                images.append(base64.b64decode(part["inlineData"]["data"]))
            elif part.get("fileData", {}).get("fileUri"):
                images.append(router.download(part["fileData"]["fileUri"]))
            elif part.get("text"):
                texts.append(part["text"].strip())
    if not images:
        why = " ".join(texts)[:300] or ", ".join(reasons) or "no reason given"
        raise ValueError(f"Gemini did not return an image: {why}")
    return images
