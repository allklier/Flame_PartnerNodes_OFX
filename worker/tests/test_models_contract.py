"""Every model in the C++ tables (ofx/src/models/*.cpp) works end to end on the Python side.

ctest dumps the tables to JSON (ofx/tests/dump_model_specs.cpp) and passes the path in
$CPO_MODEL_SPECS. For each model: its module exists and loads, a fixture exists
(tests/model_fixtures.py), every param it reads is defined in its table, and job.py turns the
table's default values (plus a prompt) into a request and a cached result, against the fake Router,
with and without the source as reference. Without $CPO_MODEL_SPECS the test skips.
"""

import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from cpo import models
from tests import model_fixtures
from tests.fake_router import KEY, FakeRouter

WORKER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPECS = os.environ.get("CPO_MODEL_SPECS", "")


def default_params(spec: dict) -> dict:
    out = {}
    for p in spec["params"]:
        if p["kind"] == "choice":
            out[p["name"]] = p["options"][p["def"]]
        elif p["kind"] == "int":
            out[p["name"]] = str(p["def"])
        elif p["kind"] == "bool":
            out[p["name"]] = "1" if p["def"] else "0"
        else:
            out[p["name"]] = p["defText"]
    out["prompt"] = "change the sky in @Image1 to dusk"
    return out


class TrackingParams(dict):
    """Records every key a module reads, to catch names that aren't in the C++ table."""

    def __init__(self, *a):
        super().__init__(*a)
        self.read = set()

    def get(self, k, *d):
        self.read.add(k)
        return super().get(k, *d)

    def __getitem__(self, k):
        self.read.add(k)
        return super().__getitem__(k)


@unittest.skipUnless(SPECS, "set CPO_MODEL_SPECS (ctest does)")
class ModelsContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(SPECS) as f:
            cls.specs = json.load(f)

    def test_tables_are_unique(self):
        self.assertGreaterEqual(len(self.specs), 1)
        for key in ("pluginId", "module", "label"):
            values = [s[key] for s in self.specs]
            self.assertEqual(len(values), len(set(values)), key)

    def test_modules_fixtures_and_param_names(self):
        for spec in self.specs:
            with self.subTest(model=spec["label"]):
                mod = models.load(spec["module"])
                self.assertIn(spec["module"], model_fixtures.FIXTURES, "add a fixture in tests/model_fixtures.py")
                for name in ("MODEL_ID", "reference_pixels", "build_request", "result_images"):
                    self.assertTrue(hasattr(mod, name), name)
                params = TrackingParams(default_params(spec))

                class Up:
                    def upload_multipart(self, *a):
                        return {"image_url": "https://example.invalid/ref.png"}
                refs = [b"png"] if spec["maxReferences"] else []
                mod.build_request(Up(), params, refs, _Log())
                unknown = params.read - {p["name"] for p in spec["params"]}
                self.assertEqual(unknown, set(), "the module reads params that its C++ table doesn't define")

    def test_end_to_end(self):
        for spec in self.specs:
            for with_source in ([True, False] if spec["maxReferences"] else [False]):
                with self.subTest(model=spec["label"], source=with_source):
                    self.run_job(spec, with_source)

    def run_job(self, spec, with_source):
        fake = FakeRouter()
        fake.response = lambda: model_fixtures.FIXTURES[spec["module"]](fake)
        with tempfile.TemporaryDirectory() as tmp:
            staging, root = os.path.join(tmp, "staging"), os.path.join(tmp, "cache")
            os.makedirs(staging)
            job, w, h = "9-0-1", 40, 24
            inp = ""
            if with_source:
                inp = os.path.join(staging, f"cpo_job_{job}_in.bin")
                with open(inp, "wb") as f:
                    f.write(struct.pack("<4sIIIII", b"CPOA", 1, w, h, 1, 3))
                    # noise: an incompressible PNG, so leaked image data would be long enough to spot
                    np.random.default_rng(0).random((h, w, 3), np.float32).tofile(f)
            params = default_params(spec)
            if not with_source:
                params["prompt"] = "a fox in the snow"
            manifest = os.path.join(staging, f"cpo_job_{job}.json")
            with open(manifest, "w") as f:
                json.dump({"job_id": job, "node_id": "n", "model": spec["module"], "label": spec["label"],
                           "input": inp, "width": w, "height": h, "colour": "Bypass", "ocio_config": "",
                           "params": params, "cache_root": root, "key": "00aa00aa00aa00aa", "flame_pid": 0,
                           "title": "t"}, f)
            env = dict(os.environ, HOME=tmp, CPO_ROUTER_BASE=fake.base, COMFY_API_KEY=KEY)
            p = subprocess.run([sys.executable, "-I", "-B", os.path.join(WORKER, "job.py"), manifest, "--no-ui"],
                               env=env, capture_output=True, text=True, timeout=60)
            fake.close()
            with open(os.path.join(root, "jobs", f"{job}.json")) as f:
                status = json.load(f)
            self.assertEqual(status["state"], "done", f"{status} {p.stderr[-500:]}")
            with open(os.path.join(root, "00", "00aa00aa00aa00aa.img"), "rb") as f:
                self.assertEqual(struct.unpack("<4sIIIII", f.read(24)), (b"CPOI", 1, w, h, 1, 3))
            self.assertEqual(os.listdir(staging), [])
            # LTX decision 39: no image data in the log (a request body with inline base64 leaked once).
            with open(os.path.join(tmp, ".cache/partner-models-ofx/logs/partner-models.log")) as f:
                for line in f:
                    self.assertLess(len(line), 4000, f"suspiciously long log line: {line[:200]}")
                    self.assertNotRegex(line, r"[A-Za-z0-9+/]{200,}", "base64 data in the log")


class _Log:
    def info(self, m):
        pass

    warn = error = debug = info


if __name__ == "__main__":
    unittest.main()
