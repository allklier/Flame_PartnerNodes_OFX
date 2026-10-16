import unittest

from cpo.models import krea3, load


class Log:
    def __init__(self):
        self.lines = []

    def info(self, m):
        self.lines.append(m)

    warn = error = debug = info


class FakeRouter:
    def __init__(self):
        self.uploads = []

    def upload_multipart(self, path, field, filename, data, mime):
        self.uploads.append((path, field, filename, len(data), mime))
        return {"image_url": f"https://app-uploads.krea.ai/{filename}", "width": 4, "height": 2}


PARAMS = {"prompt": "remove the person from @Image1", "thinkingMode": "fast", "seed": "7",
          "aspectRatio": "auto", "resolution": "1K", "preciseEdit": "1"}


class Krea3Test(unittest.TestCase):
    def test_load(self):
        self.assertIs(load("krea3"), krea3)
        with self.assertRaises(ValueError):
            load("../etc")

    def test_image_refs_as_comfyui(self):
        self.assertEqual(krea3.resolve_image_refs("swap @Image1 sky", 1), "swap image 1 sky")
        self.assertEqual(krea3.resolve_image_refs("@image keep", 1), "image 1 keep")
        self.assertEqual(krea3.resolve_image_refs("mail me@Image1", 1), "mail me@Image1")  # inside a word
        self.assertEqual(krea3.resolve_image_refs("no refs", 0), "no refs")
        with self.assertRaises(ValueError):
            krea3.resolve_image_refs("use @Image2", 1)

    def test_edit_request(self):
        r, log = FakeRouter(), Log()
        body = krea3.build_request(r, PARAMS, [b"png"], log)
        self.assertEqual(r.uploads, [("/proxy/krea/assets", "file", "reference_1.png", 3, "image/png")])
        self.assertEqual(body, {"prompt": "remove the person from image 1", "resolution": "1k",
                                "thinking_mode": "fast", "seed": 7,
                                "image_urls": ["https://app-uploads.krea.ai/reference_1.png"],
                                "regional_edit": True})

    def test_text_to_image_request(self):
        p = dict(PARAMS, prompt="a fox", aspectRatio="16:9", resolution="2K", preciseEdit="1")
        body = krea3.build_request(FakeRouter(), p, [], Log())
        self.assertEqual(body, {"prompt": "a fox", "resolution": "2k", "thinking_mode": "fast", "seed": 7,
                                "aspect_ratio": "16:9"})  # no regional_edit without an image

    def test_empty_prompt(self):
        with self.assertRaises(ValueError):
            krea3.build_request(FakeRouter(), dict(PARAMS, prompt="  "), [], Log())

    def test_result_images(self):
        class R:
            def download(self, url):
                return b"img:" + url.encode()
        self.assertEqual(krea3.result_images(R(), {"result": {"urls": ["u"]}}), [b"img:u"])
        with self.assertRaises(ValueError):
            krea3.result_images(R(), {"status": "completed", "result": None})


if __name__ == "__main__":
    unittest.main()
