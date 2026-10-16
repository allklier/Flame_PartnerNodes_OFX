import io
import os
import struct
import tempfile
import unittest

import numpy as np
from PIL import Image

from cpo import cache, imageio


def png(w, h, colour=(255, 0, 0)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(buf, "PNG")
    return buf.getvalue()


class ImageIoTest(unittest.TestCase):
    def test_fill_crop_size_and_centre(self):
        # 1360x768 (Krea 1K at 16:9) into 1920x1080: covers, crops a few pixels.
        out = imageio.fill_crop(png(1360, 768), 1920, 1080)
        self.assertEqual(out.shape, (1080, 1920, 3))
        self.assertEqual(out.dtype, np.float32)
        self.assertAlmostEqual(float(out[540, 960, 0]), 1.0)
        # A square into a wide frame: left/right of the source survive only in the centre.
        img = Image.new("RGB", (100, 100), (0, 0, 0))
        img.paste((255, 255, 255), (0, 45, 100, 55))  # white band in the middle rows
        buf = io.BytesIO()
        img.save(buf, "PNG")
        wide = imageio.fill_crop(buf.getvalue(), 200, 50)
        self.assertEqual(wide.shape, (50, 200, 3))
        self.assertGreater(wide[25, 100, 0], 0.9)  # the band is centred
        self.assertLess(wide[2, 100, 0], 0.1)

    def test_to_png_limits_pixels(self):
        disp = np.full((1080, 1920, 3), 0.5, np.float32)
        data = imageio.to_png(disp, 1024 * 1024)
        img = Image.open(io.BytesIO(data))
        self.assertLessEqual(img.width * img.height, 1024 * 1024)
        self.assertAlmostEqual(img.width / img.height, 1920 / 1080, places=2)
        self.assertEqual(img.getpixel((0, 0)), (128, 128, 128))
        small = Image.open(io.BytesIO(imageio.to_png(np.zeros((10, 20, 3)), 1024 * 1024)))
        self.assertEqual(small.size, (20, 10))  # never scaled up
        clipped = Image.open(io.BytesIO(imageio.to_png(np.full((2, 2, 3), 3.0))))
        self.assertEqual(clipped.getpixel((0, 0)), (255, 255, 255))


class CacheTest(unittest.TestCase):
    def test_result_layout_matches_cache_h(self):
        with tempfile.TemporaryDirectory() as root:
            img = np.random.default_rng(1).random((3, 4, 3)).astype(np.float32)
            path = cache.write_result(root, "abcdef0123456789", "display", img)
            self.assertEqual(path, os.path.join(root, "ab", "abcdef0123456789.display.img"))
            with self.assertRaises(ValueError):
                cache.write_result(root, "abcdef0123456789", "other", img)
            raw = cache.write_model_image(root, "abcdef0123456789", b"\x89PNG....")
            self.assertEqual(raw, os.path.join(root, "ab", "abcdef0123456789.model.png"))
            self.assertEqual(cache.model_ext(b"\xff\xd8\xff"), "jpg")
            self.assertEqual(cache.model_ext(b"RIFF0000WEBPVP8 "), "webp")
            raw = open(path, "rb").read()
            self.assertEqual(struct.unpack("<4sIIIII", raw[:24]), (b"CPOI", 1, 4, 3, 1, 3))
            back = np.frombuffer(raw[24:], "<f2").reshape(3, 4, 3)
            np.testing.assert_allclose(back, img, atol=1e-3)

    def test_read_staged(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "in.bin")
            frame = np.arange(2 * 3 * 3, dtype=np.float32).reshape(2, 3, 3)
            with open(p, "wb") as f:
                f.write(struct.pack("<4sIIIII", b"CPOA", 1, 3, 2, 1, 3))
                frame.astype("<f4").tofile(f)
            np.testing.assert_array_equal(cache.read_staged(p), frame)
            with open(p, "r+b") as f:
                f.write(b"XXXX")
            with self.assertRaises(ValueError):
                cache.read_staged(p)

    def test_pending_and_status(self):
        with tempfile.TemporaryDirectory() as root:
            cache.mark_pending(root, "k", 123)
            self.assertEqual(open(cache.pending_path(root, "k")).read(), "123")
            cache.clear_pending(root, "k")
            cache.clear_pending(root, "k")  # twice is fine
            self.assertFalse(os.path.exists(cache.pending_path(root, "k")))
            cache.write_status(root, "j1", "failed", 'bad "quote"')
            text = open(os.path.join(root, "jobs", "j1.json")).read()
            self.assertIn('"state": "failed"', text)  # the plugin's jsonField reads '"key": value'


if __name__ == "__main__":
    unittest.main()
