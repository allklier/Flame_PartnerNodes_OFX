"""Partner Models OFX: Flame Python hook that refreshes the viewer when a Generate job finishes.

A copy of LTX Alpha Gen's hook (flame_hook/ltx_alphagen_hook.py there, LTX decision 49), watching
this plugin's own folder. Decision 7: when the LTX hook is installed, job.py writes its marker into
the LTX folder instead and this hook is not needed (install only one of the two).

Installed by copying (or linking) this file into /opt/Autodesk/shared/python/; Flame loads it at
start-up. It runs inside Flame's Python, so it must never raise. It polls the folder once a second
from Flame's idle loop (flame.schedule_idle_event, int delay: a float raises ArgumentError) and
steps flame.batch.current_frame to a neighbour and back one second later: Flame re-renders on each
frame change, and the return renders the original frame from the fresh cache. Logs go to the
plugin's log, component "hook".
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys

# The OFX plugin folder: /usr/OFX/Plugins on Linux, /Library/OFX/Plugins on macOS.
BUNDLE_WORKER = ("/Library/OFX/Plugins" if sys.platform == "darwin" else "/usr/OFX/Plugins") + \
    "/PartnerModels.ofx.bundle/Contents/Resources/worker"
REFRESH_DIR = os.path.expanduser("~/.cache/partner-models-ofx/run/refresh")
POLL_SECONDS = 1
STEP_BACK = 1  # seconds before stepping back: schedule_idle_event takes an int delay


def _load_logger():
    """The plugin's own logger (same file and format), loaded by path: no sys.path change in Flame."""
    try:
        spec = importlib.util.spec_from_file_location("cpo_hook_log", os.path.join(BUNDLE_WORKER, "cpo", "log.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.Logger("hook")
    except Exception:  # noqa: BLE001

        class _Null:
            def __getattr__(self, _name):
                return lambda _msg: None

        return _Null()


log = _load_logger()
_started = False


def _schedule(fn, delay: int) -> None:
    import flame

    flame.schedule_idle_event(fn, delay=delay)


def _frame_step() -> str:
    import flame

    attr = flame.batch.current_frame
    v = int(attr.get_value())
    other = v - 1 if v > 1 else v + 1
    attr.set_value(other)

    def back():
        try:
            attr.set_value(v)
            log.info(f"refresh 'frame_step': back to frame {v}")
        except Exception as exc:  # noqa: BLE001
            log.info(f"refresh 'frame_step': could not go back to frame {v}: {type(exc).__name__}: {exc}")

    try:
        _schedule(back, STEP_BACK)
    except Exception as exc:  # noqa: BLE001 - never leave the user on another frame
        log.info(f"refresh 'frame_step': could not schedule the step back ({type(exc).__name__}); stepping back now")
        back()
    return f"current_frame {v} -> {other}, back in {STEP_BACK} s"


def _refresh(marker: dict) -> None:
    try:
        result = _frame_step()
        log.info(f"refresh after job {marker.get('job_id')} ({marker.get('state')}): {result}")
    except Exception as exc:  # noqa: BLE001
        log.info(f"refresh failed: {type(exc).__name__}: {exc}")


def _poll() -> None:
    try:
        names = sorted(n for n in os.listdir(REFRESH_DIR) if n.endswith(".json"))
    except OSError:
        names = []
    latest = None
    for name in names:  # several jobs ending together need one refresh
        path = os.path.join(REFRESH_DIR, name)
        try:
            with open(path) as f:
                latest = json.load(f)
            os.unlink(path)
        except (OSError, ValueError):
            continue
        log.info(f"job {latest.get('job_id')} ended ({latest.get('state')}), node {latest.get('node_id')}")
    if latest is not None:
        _refresh(latest)
    try:
        _schedule(_poll, POLL_SECONDS)
    except Exception as exc:  # noqa: BLE001
        log.info(f"could not reschedule the poll; refresh stops: {exc}")


def app_initialized(project_name):  # noqa: ARG001 - Flame hook signature
    global _started
    if _started:
        return
    _started = True
    try:
        _schedule(_poll, POLL_SECONDS)
        log.info("hook started: watching for finished jobs")
    except Exception as exc:  # noqa: BLE001
        log.info(f"hook could not start: {type(exc).__name__}: {exc}")


log.info("hook module loaded")
