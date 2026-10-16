"""job.py end to end against the fake Router: staging in, cached result out, no credits spent."""

import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from cpo import colour as _colour
from tests.fake_router import KEY, FakeRouter

try:
    import PyOpenColorIO  # noqa: F401
    HAVE_OCIO = bool(_colour.default_config())
except ImportError:
    HAVE_OCIO = False

WORKER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class JobTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeRouter()
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home")
        self.staging = os.path.join(self.tmp.name, "staging")
        self.root = os.path.join(self.tmp.name, "cache")
        os.makedirs(self.home)
        os.makedirs(self.staging)

    def tearDown(self):
        self.fake.close()
        self.tmp.cleanup()

    def run_job(self, with_source=True, key=KEY, params=None, w=32, h=18, colour="Bypass", n_inputs=1):
        job = "123-0-1"
        inputs = []
        for i in range(n_inputs if with_source else 0):
            path = os.path.join(self.staging, f"cpo_job_{job}_in{i + 1}.bin")
            frame = np.full((h, w, 3), 0.25 + 0.1 * i, np.float32)
            with open(path, "wb") as f:
                f.write(struct.pack("<4sIIIII", b"CPOA", 1, w, h, 1, 3))
                frame.tofile(f)
            inputs.append(path)
        inp = inputs[0] if inputs else ""
        manifest = os.path.join(self.staging, f"cpo_job_{job}.json")
        m = {"job_id": job, "node_id": "n1", "model": "krea3", "label": "Krea 3", "inputs": inputs,
             "width": w, "height": h, "colour": colour, "ocio_config": "",
             "params": params or {"prompt": "remove @Image1 person", "thinkingMode": "fast", "seed": "1",
                                  "aspectRatio": "auto", "resolution": "1K", "preciseEdit": "1"},
             "cache_root": self.root, "key": "0123456789abcdef", "flame_pid": 0, "title": "test"}
        m["reference_pixels"] = getattr(self, "limit", 0)
        with open(manifest, "w") as f:
            json.dump(m, f)
        env = dict(os.environ, HOME=self.home, CPO_ROUTER_BASE=self.fake.base, COMFY_API_KEY=key)
        p = subprocess.run([sys.executable, "-I", "-B", os.path.join(WORKER, "job.py"), manifest, "--no-ui"],
                           env=env, capture_output=True, text=True, timeout=60)
        with open(os.path.join(self.root, "jobs", f"{job}.json")) as f:
            status = json.load(f)
        return p, status, inp, manifest

    def test_edit_end_to_end(self):
        p, status, inp, manifest = self.run_job()
        self.assertEqual(status["state"], "done", status)
        self.assertEqual(p.returncode, 0)
        # Decision 16: the API's image byte for byte, plus both variants.
        with open(os.path.join(self.root, "01", "0123456789abcdef.model.png"), "rb") as f:
            from tests.fake_router import png
            self.assertEqual(f.read(), png(*self.fake.result_size))
        self.assertTrue(os.path.exists(os.path.join(self.root, "01", "0123456789abcdef.source.img")))
        res = os.path.join(self.root, "01", "0123456789abcdef.display.img")
        raw = open(res, "rb").read()
        self.assertEqual(struct.unpack("<4sIIIII", raw[:24]), (b"CPOI", 1, 32, 18, 1, 3))
        img = np.frombuffer(raw[24:], "<f2").reshape(18, 32, 3)
        self.assertTrue(np.all(img >= 0) and np.all(img <= 1))
        # Cleanup: staged files, pid file, pending marker.
        for path in (inp, manifest, os.path.join(self.root, "pending", "0123456789abcdef")):
            self.assertFalse(os.path.exists(path), path)
        self.assertEqual(os.listdir(self.staging), [])
        # Request: uploaded reference, the body the module built, the key only to the Router host.
        self.assertEqual(len(self.fake.find("POST", "/proxy/krea/assets")), 1)
        sub = self.fake.find("POST", "/v2/models/krea/krea-3/requests")
        body = json.loads(sub[0][3])
        self.assertEqual(body["prompt"], "remove image 1 person")
        self.assertEqual(body["regional_edit"], True)
        self.assertTrue({k.lower(): v for k, v in sub[0][2].items()}.get("idempotency-key"))
        for method, path, headers, _ in self.fake.requests:
            lower = {k.lower(): v for k, v in headers.items()}  # header names are case-insensitive
            if path.startswith("/images/"):
                self.assertNotIn("x-api-key", lower)
            else:
                self.assertEqual(lower.get("x-api-key"), KEY, path)
        # The log has the run but never the key.
        with open(os.path.join(self.home, ".cache/partner-models-ofx/logs/partner-models.log")) as f:
            log = f.read()
        self.assertIn("end: done", log)
        self.assertNotIn(KEY, log)

    def result(self, variant="display"):
        with open(os.path.join(self.root, "01", f"0123456789abcdef.{variant}.img"), "rb") as f:
            raw = f.read()
        return np.frombuffer(raw[24:], "<f2").reshape(18, 32, 3).astype(np.float32)

    @unittest.skipUnless(HAVE_OCIO, "needs PyOpenColorIO and Flame's ACES 2.0 config")
    def test_output_variants(self):
        # Decision 16: one run caches both: "display" = the model's pixels, "source" = back to ACEScg.
        from cpo import imageio
        from tests.fake_router import png
        expected = imageio.fill_crop(png(*self.fake.result_size), 32, 18)
        _, status, _, _ = self.run_job(colour="ACEScg")
        self.assertEqual(status["state"], "done", status)
        display = self.result("display")
        np.testing.assert_allclose(display, expected, atol=2e-3)
        self.assertGreater(float(np.abs(self.result("source") - display).max()), 0.05)
        self.assertEqual(len(self.fake.find("POST", "/requests")), 1)

    def test_three_inputs(self):
        # Decision 15: Image 1..3 uploaded in order; @Image3 refers to the third.
        p, status, _, _ = self.run_job(n_inputs=3, params={"prompt": "put the hat of @Image3 on @Image1",
                                                           "thinkingMode": "fast", "seed": "1", "aspectRatio": "auto",
                                                           "resolution": "1K", "preciseEdit": "0"})
        self.assertEqual(status["state"], "done", status)
        self.assertEqual(len(self.fake.find("POST", "/proxy/krea/assets")), 3)
        body = json.loads(self.fake.find("POST", "/requests")[0][3])
        self.assertEqual(body["prompt"], "put the hat of image 3 on image 1")
        self.assertEqual(len(body["image_urls"]), 3)
        self.assertEqual(os.listdir(self.staging), [])  # all three staged files cleaned up

    def test_scaled_to_the_manifest_limit(self):
        # Decision 17: job.py scales inputs to the plugin's limit and says so in the log.
        self.limit = 200
        _, status, _, _ = self.run_job()
        self.assertEqual(status["state"], "done", status)
        with open(os.path.join(self.home, ".cache/partner-models-ofx/logs/partner-models.log")) as f:
            self.assertIn("scaled down to the model's 0.0 MP", f.read())

    def test_reference_beyond_inputs_fails(self):
        _, status, _, _ = self.run_job(n_inputs=1, params={"prompt": "use @Image2", "thinkingMode": "fast",
                                                           "seed": "1", "aspectRatio": "auto", "resolution": "1K",
                                                           "preciseEdit": "0"})
        self.assertEqual(status["state"], "failed")
        self.assertIn("@Image2", status["message"])

    def test_text_to_image(self):
        p, status, _, _ = self.run_job(with_source=False,
                                       params={"prompt": "a fox", "thinkingMode": "high", "seed": "3",
                                               "aspectRatio": "16:9", "resolution": "2K", "preciseEdit": "0"})
        self.assertEqual(status["state"], "done", status)
        self.assertEqual(self.fake.find("POST", "/proxy/krea/assets"), [])
        body = json.loads(self.fake.find("POST", "/requests")[0][3])
        self.assertEqual(body, {"prompt": "a fox", "resolution": "2k", "thinking_mode": "high", "seed": 3,
                                "aspect_ratio": "16:9"})

    def test_model_refusal(self):
        self.fake.error_type = "content_policy_violation"
        p, status, _, _ = self.run_job()
        self.assertEqual(status["state"], "failed")
        self.assertIn("content_policy_violation", status["message"])
        self.assertEqual(p.returncode, 1)
        self.assertFalse(os.path.exists(os.path.join(self.root, "01", "0123456789abcdef.display.img")))

    def test_no_credits(self):
        self.fake.submit_code = 402
        _, status, _, _ = self.run_job()
        self.assertEqual(status["state"], "failed")
        self.assertIn("credits", status["message"])

    def test_bad_key(self):
        _, status, _, _ = self.run_job(key="comfyui-wrong")
        self.assertEqual(status["state"], "failed")
        self.assertIn("401", status["message"])

    def test_no_key(self):
        _, status, _, _ = self.run_job(key="")
        self.assertEqual(status["state"], "failed")
        self.assertIn("API key", status["message"])
        self.assertEqual(self.fake.requests, [])


if __name__ == "__main__":
    unittest.main()


class LoggableTest(unittest.TestCase):
    def test_no_image_data_in_logs(self):
        sys.path.insert(0, WORKER)
        import job

        body = {"contents": [{"parts": [{"text": "a fox"}, {"inlineData": {"mimeType": "image/png", "data": "QUJD" * 100}}]}],
                "image_urls": ["https://u/1.png"], "prompt": "x"}
        out = json.dumps(job.loggable(body))
        self.assertNotIn("QUJD", out)
        self.assertNotIn("https://u/1.png", out)
        self.assertIn("a fox", out)
        self.assertIn("<300 bytes base64>", out)
        self.assertIn("<1 reference URL(s)>", out)
