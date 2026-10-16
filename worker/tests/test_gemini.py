import base64
import unittest

from cpo.models import gemini, load, nano_banana_pro

PARAMS = {"prompt": "make @Image1 dusk", "seed": "7", "aspectRatio": "auto", "resolution": "2K"}


class R:
    def download(self, url):
        return b"file:" + url.encode()


class GeminiTest(unittest.TestCase):
    def test_body(self):
        body = gemini.build_body(PARAMS, [b"PNG"])
        parts = body["contents"][0]["parts"]
        self.assertEqual(body["contents"][0]["role"], "user")
        self.assertEqual(parts[0], {"text": "make image 1 dusk"})
        self.assertEqual(parts[1], {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(b"PNG").decode()}})
        self.assertEqual(body["generationConfig"], {"responseModalities": ["TEXT", "IMAGE"],
                                                    "imageConfig": {"imageSize": "2K"}, "seed": 7})
        self.assertIn("systemInstruction", body)
        b2 = gemini.build_body(dict(PARAMS, prompt="a fox", aspectRatio="16:9", resolution="4K"), [])
        self.assertEqual(len(b2["contents"][0]["parts"]), 1)
        self.assertEqual(b2["generationConfig"]["imageConfig"], {"imageSize": "4K", "aspectRatio": "16:9"})

    def test_response(self):
        ok = {"candidates": [{"content": {"parts": [{"text": "hi"}, {"thought": True, "inlineData": {"data": "eA=="}},
                                                    {"inlineData": {"mimeType": "image/png", "data": "QUJD"}}]}}]}
        self.assertEqual(gemini.images_from_response(R(), ok), [b"ABC"])  # thought images skipped
        uri = {"candidates": [{"content": {"parts": [{"fileData": {"fileUri": "https://x/y.png"}}]}}]}
        self.assertEqual(gemini.images_from_response(R(), uri), [b"file:https://x/y.png"])

    def test_refusals_explained(self):
        with self.assertRaisesRegex(ValueError, "SAFETY"):
            gemini.images_from_response(R(), {"promptFeedback": {"blockReason": "SAFETY"}})
        with self.assertRaisesRegex(ValueError, "cannot edit people"):
            gemini.images_from_response(R(), {"candidates": [{"content": {"parts": [{"text": "I cannot edit people."}]}}]})
        with self.assertRaisesRegex(ValueError, "IMAGE_PROHIBITED_CONTENT"):
            gemini.images_from_response(R(), {"candidates": [{"finishReason": "IMAGE_PROHIBITED_CONTENT"}]})

    def test_module(self):
        self.assertIs(load("nano_banana_pro"), nano_banana_pro)
        self.assertEqual(nano_banana_pro.MODEL_ID, "vertexai/gemini-3-pro-image")
        with self.assertRaises(ValueError):
            load("gemini")  # a family helper, not a model


if __name__ == "__main__":
    unittest.main()
