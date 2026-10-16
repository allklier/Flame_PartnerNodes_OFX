"""Helpers shared by model modules."""

from __future__ import annotations

import re

# ComfyUI's nodes_krea.py _IMAGE_REF_RE / _resolve_image_refs: "@Image1" -> "image 1".
_IMAGE_REF_RE = re.compile(r"@image(?P<idx>\d*)(?!\w)", re.IGNORECASE | re.ASCII)


def resolve_image_refs(prompt: str, total_images: int) -> str:
    parts, pos, prev_end = [], 0, -1
    for match in _IMAGE_REF_RE.finditer(prompt):
        start = match.start()
        if (start > 0 and start != prev_end and prompt[start - 1].isascii()
                and (prompt[start - 1].isalnum() or prompt[start - 1] == "_")):
            continue
        idx = int(match.group("idx") or 1)
        if not 1 <= idx <= total_images:
            raise ValueError(f"The prompt refers to @Image{idx}, but only {total_images} image(s) are sent "
                             f"(is Use Source on?).")
        parts.append(prompt[pos:start])
        parts.append(f"image {idx}")
        pos = prev_end = match.end()
    parts.append(prompt[pos:])
    return "".join(parts)


def require_prompt(params: dict) -> str:
    prompt = params.get("prompt", "").strip()
    if not prompt:
        raise ValueError("The prompt is empty.")
    return prompt
