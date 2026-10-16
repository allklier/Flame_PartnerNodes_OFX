"""A fake response per model module, in the provider's own shape, for the contract test.
Adding a model module without a fixture here fails tests/test_models_contract.py on purpose."""

from __future__ import annotations

import base64

from tests.fake_router import png


def krea3(router):
    return {"status": "completed", "job_id": "k1",
            "result": {"urls": [f"http://localhost:{router.port}/images/out.png"]}}


def gemini(router):
    data = base64.b64encode(png(*router.result_size)).decode()
    return {"candidates": [{"content": {"role": "model", "parts": [
        {"text": "Here is the edited image."},
        {"inlineData": {"mimeType": "image/png", "data": data}}]}, "finishReason": "STOP"}]}


FIXTURES = {"krea3": krea3, "nano_banana_pro": gemini}
