"""Setup: install the Python runtime the Generate job runs on, then mark the user's setup ready.

Launched detached by the plugin's Install button (Setup tab). Standard library only and Python 3.9
compatible: it runs with the system python3 (Rocky 9: 3.9) before any venv exists.

  python3 -I -B setup_helper.py --runtime-dir D [--no-ui]

Steps (decision 6; LTX decisions 57/60), pinned by runtime_manifest.json next to this file:
  1 uv        <D>/bin/uv at the pinned version, SHA-256 verified (kept if already there)
  2 venv      <D>/venv on uv's own Python (--managed-python, pinned version), never a system one
  3 packages  numpy, OpenColorIO (>= 2.4 for Flame's ACES 2.0 config), Pillow at pinned versions
  4 check     imports, and the OCIO transform the job uses if Flame's config is installed
  5 config    runtime_dir, runtime_python, runtime_ready in ~/.config/partner-models-ofx/config.conf
Progress and Cancel in a window (cpo/oslayer.py). Everything is logged (cpo/log.py). The parts are
adapted from LTX Alpha Gen's setup_helper.py (install_runtime, run, stream_copy, write_config).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "worker"))

from cpo import oslayer  # noqa: E402  (stdlib only)
from cpo.log import Logger  # noqa: E402

CONFIG = os.path.expanduser("~/.config/partner-models-ofx/config.conf")
TITLE = "Partner Models - setup"
CHUNK = 8 << 20
log = Logger("setup")

# The check the job depends on: the packages import, and (when Flame's config is there) the
# ACES 2.0 SDR view builds in both directions, as worker/cpo/colour.py builds it.
CHECK = r"""
import glob, sys, numpy, PIL, PyOpenColorIO as ocio
cfgs = sorted(glob.glob('/opt/Autodesk/colour_mgmt/configs/flame_configs/*/aces2.0_config/config.ocio'))
msg = f"python {sys.version.split()[0]} numpy {numpy.__version__} pillow {PIL.__version__} ocio {ocio.__version__}"
if cfgs:
    c = ocio.Config.CreateFromFile(cfgs[-1])
    t = ocio.DisplayViewTransform()
    t.setSrc('ACEScg'); t.setDisplay('Rec.1886 Rec.709 - Display'); t.setView('ACES 2.0 - SDR 100 nits (Rec.709)')
    c.getProcessor(t, ocio.TRANSFORM_DIR_FORWARD); c.getProcessor(t, ocio.TRANSFORM_DIR_INVERSE)
    msg += f"; Flame config OK: {cfgs[-1]}"
else:
    msg += "; no Flame ACES 2.0 config found (only Bypass will work)"
print(msg)
"""


class Cancelled(Exception):
    pass


class SetupError(Exception):
    pass


class Progress:
    def __init__(self, enabled: bool) -> None:
        self.win = oslayer.ProgressWindow(TITLE, 480, enabled)
        self.done = False

    def update(self, frac: float, text: str) -> None:
        if self.cancelled():
            raise Cancelled()
        if self.win.shown:
            try:
                self.win.show(frac, text)
            except BrokenPipeError as exc:
                raise Cancelled() from exc

    def cancelled(self) -> bool:
        return not self.done and self.win.gone()

    def close(self) -> None:
        self.done = True
        self.win.close()


def download_verified(url: str, dst: str, size: int, sha: str, prog: Progress, frac: float) -> None:
    part = dst + ".part"
    h, done = hashlib.sha256(), 0
    with urllib.request.urlopen(url, timeout=60) as resp, open(part, "wb") as out:
        for buf in iter(lambda: resp.read(CHUNK), b""):
            out.write(buf)
            h.update(buf)
            done += len(buf)
            prog.update(frac, f"downloading uv: {done / 1e6:.0f} of {size / 1e6:.0f} MB")
    if done != size or h.hexdigest() != sha:
        os.unlink(part)
        raise SetupError(f"uv download: size/hash mismatch ({done} bytes, sha256 {h.hexdigest()[:16]}...)")
    os.replace(part, dst)


def run(cmd: list, env: dict, label: str, prog: Progress, frac: float, retries: int = 0) -> str:
    """Runs a step, watching for Cancel; network steps retry (PyPI timed out once in LTX testing)."""
    for attempt in range(retries + 1):
        log.info(f"{label}: {' '.join(cmd)}")
        prog.update(frac, label)
        proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        stop = threading.Event()

        def watcher() -> None:
            while not stop.wait(1.0):
                if prog.cancelled():
                    proc.kill()
                    return

        t = threading.Thread(target=watcher, daemon=True)
        t.start()
        out = proc.stdout.read()
        proc.wait()
        stop.set()
        t.join()
        if prog.cancelled():
            raise Cancelled()
        for line in out.splitlines():
            log.debug(f"{label}: {line}")
        if proc.returncode == 0:
            return out
        tail = out.strip().splitlines()[-20:]
        log.error(f"{label} failed (exit {proc.returncode}):\n" + "\n".join(tail))
        if attempt < retries:
            prog.update(frac, f"{label}: problem, retrying...")
            time.sleep(10)
            continue
        errs = [x.strip() for x in tail if x.strip().startswith(("error:", "Traceback", "ModuleNotFoundError"))]
        raise SetupError(f"{label} failed (exit {proc.returncode}): {(errs or tail or [''])[-1]}")
    raise SetupError(label)  # not reached


def install(man: dict, rt: str, prog: Progress) -> str:
    """Returns the venv's python."""
    env = dict(os.environ, UV_CACHE_DIR=f"{rt}/uv-cache", UV_PYTHON_INSTALL_DIR=f"{rt}/python", UV_NO_PROGRESS="1")
    for k in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "CONDA_PREFIX", "LD_LIBRARY_PATH"):
        env.pop(k, None)
    os.makedirs(f"{rt}/bin", exist_ok=True)
    uv, u = f"{rt}/bin/uv", man["uv"]
    have = ""
    if os.path.exists(uv):
        have = subprocess.run([uv, "--version"], capture_output=True, text=True).stdout.split()[1:2]
        have = have[0] if have else ""
    if have != u["version"]:
        asset = u[sys.platform]
        tgz = f"{rt}/bin/uv.tar.gz"
        download_verified(asset["url"], tgz, asset["size"], asset["sha256"], prog, 0.05)
        with tarfile.open(tgz) as t:
            for member in t.getmembers():
                if os.path.basename(member.name) in ("uv", "uvx") and member.isfile():
                    member.name = os.path.basename(member.name)
                    t.extract(member, f"{rt}/bin")
        os.unlink(tgz)
        log.info(f"uv {u['version']} installed (sha256 verified)")
    venv = f"{rt}/venv"
    py = f"{venv}/bin/python"
    ok = os.path.exists(py) and subprocess.run([py, "-c", "import sys; print(sys.version.split()[0])"],
                                               capture_output=True, text=True).stdout.strip() == man["python"]
    if not ok:  # missing, or on another Python: recreate (LTX decision 60)
        run([uv, "venv", "--clear", "--managed-python", "-p", man["python"], venv], env,
            f"creating the Python {man['python']} environment", prog, 0.2, retries=2)
    run([uv, "pip", "install", "-p", py, *man["packages"]], env, "installing numpy, OpenColorIO, Pillow",
        prog, 0.5, retries=2)
    out = run([py, "-I", "-B", "-c", CHECK], env, "checking the runtime", prog, 0.9)
    log.info(f"runtime check: {out.strip()}")
    return py


def write_config(updates: dict) -> None:
    cfg = {}
    if os.path.exists(CONFIG):
        with open(CONFIG) as f:
            for line in f:
                line = line.rstrip("\n")
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k] = v
    cfg.update(updates)
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    tmp = CONFIG + ".tmp"
    with open(tmp, "w") as f:
        f.write("# Partner Models OFX user settings. Written by the plugin.\n")
        for k in sorted(cfg):
            f.write(f"{k}={cfg[k]}\n")
    os.chmod(tmp, 0o600)  # holds the API key (decision 8)
    os.replace(tmp, CONFIG)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime-dir", required=True)
    ap.add_argument("--no-ui", action="store_true")
    a = ap.parse_args()
    ui = not a.no_ui
    with open(os.path.join(HERE, "runtime_manifest.json")) as f:
        man = json.load(f)
    rt = os.path.abspath(os.path.expanduser(a.runtime_dir))
    log.info(f"setup start: runtime_dir={rt} python={sys.executable} {sys.version.split()[0]}")
    prog = Progress(ui)
    t0 = time.time()
    try:
        if sys.platform not in man["uv"]:
            raise SetupError(f"no runtime for {sys.platform} yet")
        os.makedirs(rt, exist_ok=True)
        py = install(man, rt, prog)
        write_config({"runtime_dir": rt, "runtime_python": py, "runtime_ready": time.strftime("%Y-%m-%d")})
        prog.close()
        msg = f"Setup finished in {time.time() - t0:.0f} s. Runtime: {rt}"
        log.info(msg)
        oslayer.message("info", TITLE, msg, 480, ui)
        return 0
    except Cancelled:
        prog.close()
        log.warn("setup cancelled by the user")
        return 1
    except (SetupError, OSError, subprocess.SubprocessError) as exc:
        prog.close()
        log.error(f"setup failed: {exc}")
        oslayer.message("error", TITLE, f"Setup failed: {exc}", 480, ui)
        return 2


if __name__ == "__main__":
    sys.exit(main())
