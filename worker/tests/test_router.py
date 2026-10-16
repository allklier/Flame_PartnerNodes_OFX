import unittest

from cpo.router import Cancelled, Router, RouterError
from tests.fake_router import KEY, FakeRouter
from tests.test_krea3 import Log


class RouterTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeRouter()
        self.r = Router(KEY, Log(), base=self.fake.base)

    def tearDown(self):
        self.fake.close()

    def test_submit_wait_download(self):
        h = self.r.submit("krea/krea-3", {"prompt": "x", "resolution": "1k"})
        seen = []
        resp = self.r.wait(h, lambda: False, lambda st, _: seen.append(st))
        self.assertEqual(seen, ["IN_QUEUE", "IN_PROGRESS", "COMPLETED"])
        self.assertTrue(self.r.download(resp["result"]["urls"][0]).startswith(b"\x89PNG"))

    def test_cancel(self):
        self.fake.statuses = ["IN_QUEUE"]
        h = self.r.submit("krea/krea-3", {"prompt": "x", "resolution": "1k"})
        calls = []
        with self.assertRaises(Cancelled):
            self.r.wait(h, lambda: len(calls.append(1) or calls) > 2)
        self.assertTrue(self.fake.cancelled)
        self.assertEqual(len(self.fake.find("PUT", "/cancel")), 1)

    def test_cancelled_upstream(self):
        self.fake.error_type = "cancelled"
        h = self.r.submit("krea/krea-3", {"prompt": "x", "resolution": "1k"})
        with self.assertRaises(Cancelled):
            self.r.wait(h, lambda: False)

    def test_errors_explained(self):
        with self.assertRaises(RouterError) as ctx:
            Router("comfyui-bad", Log(), base=self.fake.base).submit("krea/krea-3", {})
        self.assertIn("401", str(ctx.exception))
        self.fake.submit_code = 402
        with self.assertRaises(RouterError) as ctx:
            self.r.submit("krea/krea-3", {})
        self.assertIn("credits", str(ctx.exception))
        self.assertEqual(len(self.fake.find("POST", "/requests")), 2)  # submits are never retried

    def test_timeout(self):
        self.fake.statuses = ["IN_PROGRESS"]
        h = self.r.submit("krea/krea-3", {})
        with self.assertRaises(RouterError):
            self.r.wait(h, lambda: False, max_seconds=0.5)
        self.assertTrue(self.fake.cancelled)


if __name__ == "__main__":
    unittest.main()
