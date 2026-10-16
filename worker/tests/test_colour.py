"""OCIO round trip. Runs where the runtime is (PyOpenColorIO + Flame's ACES 2.0 config), else skips."""

import unittest

import numpy as np

from cpo import colour

try:
    import PyOpenColorIO  # noqa: F401
    HAVE_OCIO = bool(colour.default_config())
except ImportError:
    HAVE_OCIO = False


class ColourTest(unittest.TestCase):
    def test_bypass(self):
        c = colour.Converter("Bypass")
        a = np.random.default_rng(0).random((4, 5, 3)).astype(np.float32)
        np.testing.assert_array_equal(c.to_display(a), a)
        np.testing.assert_array_equal(c.from_display(a), a)
        with self.assertRaises(ValueError):
            colour.Converter("sRGB-ish")

    @unittest.skipUnless(HAVE_OCIO, "needs PyOpenColorIO and Flame's ACES 2.0 config")
    def test_round_trip_through_sdr_view(self):
        for label in ("ACEScg", "LogC4", "LogC3"):
            c = colour.Converter(label)
            # Mid-range display values survive display -> source -> display.
            disp = np.linspace(0.05, 0.9, 30, dtype=np.float32).reshape(1, 10, 3)
            back = c.to_display(c.from_display(disp))
            np.testing.assert_allclose(back, disp, atol=2e-3, err_msg=label)
            # Forward of an ACES highlight stays in display range (the tone mapping, LTX colour.py).
            if label == "ACEScg":
                out = c.to_display(np.array([[[2.0, 0.05, 0.05]]], np.float32))
                self.assertTrue(np.all(out <= 1.001) and np.all(out >= -0.001), out)


if __name__ == "__main__":
    unittest.main()
