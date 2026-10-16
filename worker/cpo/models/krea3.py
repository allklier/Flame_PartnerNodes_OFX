"""Krea 3 on Comfy Router (krea/krea-3). Body schema from GET /v2/models/krea/krea-3/openapi.json
(2026-10-16): prompt, resolution ("1k"/"2k") required; aspect_ratio (omit = auto), image_urls
(<= 8, from POST /proxy/krea/assets), regional_edit, seed, thinking_mode. Uploads and the prompt's
@Image references work as in ComfyUI's Krea3ImageNode (comfy_api_nodes/nodes_krea.py).
Verified live: text-to-image and a reference edit (upload + regional_edit), both ~10 s.
"""

from __future__ import annotations

from .common import require_prompt, resolve_image_refs

MODEL_ID = "krea/krea-3"


def build_request(router, params: dict, refs: list, log) -> dict:
    prompt = require_prompt(params)
    urls = []
    for i, png in enumerate(refs):
        up = router.upload_multipart("/proxy/krea/assets", "file", f"reference_{i + 1}.png", png, "image/png")
        if "image_url" not in up:
            raise ValueError(f"Krea did not accept the reference image: {str(up)[:200]}")
        log.info(f"krea3: reference {i + 1} uploaded ({len(png)} bytes, {up.get('width')}x{up.get('height')})")
        urls.append(up["image_url"])
    body = {
        "prompt": resolve_image_refs(prompt, len(urls)),
        "resolution": params.get("resolution", "2K").lower(),
        "thinking_mode": params.get("thinkingMode", "fast"),
        "seed": int(params.get("seed", "42")),
    }
    if params.get("aspectRatio", "auto") != "auto":
        body["aspect_ratio"] = params["aspectRatio"]
    if urls:
        body["image_urls"] = urls
        body["regional_edit"] = params.get("preciseEdit") == "1"
    elif params.get("preciseEdit") == "1":
        log.info("krea3: Precise Edit ignored: it needs the source as reference")
    return body


def result_images(router, response: dict) -> list:
    urls = ((response or {}).get("result") or {}).get("urls") or []
    if not urls:
        raise ValueError(f"Krea returned no image ({str(response)[:200]})")
    return [router.download(urls[0])]
