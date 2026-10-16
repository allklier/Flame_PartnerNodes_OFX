"""Flame hook (flame_hook/partner_models_hook.py (a copy of LTX Alpha Gen's)) against a fake `flame` module.

The fake enforces what Flame test 3 showed: schedule_idle_event(function, int delay=0) rejects
a float delay (round 2 passed 0.5 and left the frame moved and the nodes bypassed).
"""

import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "flame_hook", "partner_models_hook.py")


class Attr:
    def __init__(self, value, history):
        self.value, self.history = value, history

    def get_value(self):
        return self.value

    def set_value(self, value):
        self.value = value
        self.history.append(value)


class FakeFlame(types.ModuleType):
    def __init__(self, frame, schedule_ok=True):
        super().__init__("flame")
        self.frames = []
        self.batch = types.SimpleNamespace(current_frame=Attr(frame, self.frames))
        self.queue = []
        self.schedule_ok = schedule_ok

    def schedule_idle_event(self, fn, delay=0):
        if not isinstance(delay, int) or not self.schedule_ok:
            raise TypeError("Python argument types did not match C++ signature")
        self.queue.append((delay, fn))

    def run_idle(self):
        queue, self.queue = self.queue, []
        for _delay, fn in queue:
            fn()


class HookTest(unittest.TestCase):
    def load(self, flame):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        patches = [mock.patch.dict(os.environ, {"HOME": self.home.name}), mock.patch.dict(sys.modules, {"flame": flame})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        spec = importlib.util.spec_from_file_location("cpo_hook_under_test", HOOK)
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        hook.REFRESH_DIR = os.path.join(self.home.name, "refresh")
        os.makedirs(hook.REFRESH_DIR)
        return hook

    def marker(self, hook, job):
        with open(os.path.join(hook.REFRESH_DIR, f"{job}.json"), "w") as f:
            json.dump({"job_id": job, "node_id": "n1", "state": "done"}, f)

    def test_steps_to_a_neighbour_and_back(self):
        flame = FakeFlame(frame=12)
        hook = self.load(flame)
        hook.app_initialized("project")
        self.marker(hook, "j1")
        self.marker(hook, "j2")  # two jobs ending together: one refresh
        flame.run_idle()  # the poll: consumes both markers, steps the frame, schedules the return
        self.assertEqual(flame.frames, [11])
        self.assertEqual(os.listdir(hook.REFRESH_DIR), [])
        flame.run_idle()  # the step back (and the next poll)
        self.assertEqual(flame.frames, [11, 12])
        self.assertEqual(flame.batch.current_frame.value, 12)

    def test_first_frame_steps_forward(self):
        flame = FakeFlame(frame=1)
        hook = self.load(flame)
        hook._refresh({"job_id": "j"})
        flame.run_idle()
        self.assertEqual(flame.frames, [2, 1])

    def test_steps_back_at_once_if_scheduling_fails(self):
        flame = FakeFlame(frame=5, schedule_ok=False)
        hook = self.load(flame)
        hook._refresh({"job_id": "j"})
        self.assertEqual(flame.frames, [4, 5])  # never left on another frame


if __name__ == "__main__":
    unittest.main()


class RefreshTargetTest(unittest.TestCase):
    """Decision 7: job.py feeds the LTX hook when it is installed, else our own."""

    def test_refresh_dir(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
        import job

        with mock.patch.object(job, "LTX_HOOK", "/nonexistent/ltx_alphagen_hook.py"):
            self.assertEqual(job.refresh_dir(), job.OWN_REFRESH_DIR)
        with tempfile.NamedTemporaryFile() as f, mock.patch.object(job, "LTX_HOOK", f.name):
            self.assertEqual(job.refresh_dir(), job.LTX_REFRESH_DIR)
        with tempfile.TemporaryDirectory() as d:
            job.signal_refresh(d, "j1", "n1", "done")
            with open(os.path.join(d, "j1.json")) as f:
                self.assertEqual(json.load(f)["node_id"], "n1")
