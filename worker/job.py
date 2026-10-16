"""Background Generate job (decision 4; LTX decision 35). Launched detached by the Generate button.

  <runtime python> -I -B job.py <manifest.json> [--no-ui]
  COMFY_API_KEY in the environment (never on argv or in a file; LTX decision 13).

The plugin has staged the source's first frame (float32 RGB, worker/cpo/cache.py read_staged) in
its staging folder (the manifest's folder) and computed the result's cache key. This process,
outside Flame:
  - shows a progress window with a Cancel button (cpo/oslayer.py; zenity on Linux),
  - converts the reference to display-referred sRGB (cpo/colour.py, OCIO) and to a PNG,
  - lets the model module build the Router request (uploading the reference), submits it, polls,
  - downloads the image, fills and crops it to the source size (decision 9), converts it back to
    the source colour space, and writes it into the cache,
  - always cleans up its staged files and pending marker, records a final status, and drops a
    refresh marker for the Flame hook (decision 7).
Manifest: job_id node_id model label input width height colour ocio_config params{} cache_root key
flame_pid title. Status file <cache_root>/jobs/<job_id>.json: running -> done | failed | cancelled.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cpo import cache, colour, imageio, models, oslayer  # noqa: E402
from cpo.log import Logger  # noqa: E402
from cpo.router import Cancelled, Router, RouterError  # noqa: E402

log = Logger("job")

# Decision 7: reuse LTX Alpha Gen's Flame hook when it is installed (it watches its own folder and
# steps the frame); otherwise our own copy of the hook watches ours.
LTX_HOOK = "/opt/Autodesk/shared/python/ltx_alphagen_hook.py"
LTX_REFRESH_DIR = os.path.expanduser("~/.cache/ltx-alphagen/run/refresh")
OWN_REFRESH_DIR = os.path.expanduser("~/.cache/partner-models-ofx/run/refresh")


def refresh_dir() -> str:
    return LTX_REFRESH_DIR if os.path.exists(LTX_HOOK) else OWN_REFRESH_DIR


class Progress:
    """The progress window; cancelled() is True once the user pressed Cancel."""

    def __init__(self, title: str, enabled: bool) -> None:
        self.win = oslayer.ProgressWindow(title, 520, enabled)
        self.finished = False
        self.lock = threading.Lock()  # the main thread and the 1 s ticker both write

    def update(self, frac: float, text: str) -> None:
        with self.lock:
            if not self.win.shown or self.win.gone() or self.finished:
                return
            try:
                self.win.show(frac, text)
            except BrokenPipeError:
                pass

    def cancelled(self) -> bool:
        return not self.finished and self.win.gone()

    def close(self) -> None:
        with self.lock:
            self.finished = True
        self.win.close(wait=5)


def mmss(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60}:{seconds % 60:02d}"


class Stage:
    """What the window shows: the current step plus elapsed time, redrawn every second."""

    def __init__(self) -> None:
        self.t0 = time.time()
        self.text, self.frac = "Starting", 0.0
        self.lock = threading.Lock()

    def set(self, frac: float, text: str) -> None:
        with self.lock:
            self.frac, self.text = frac, text

    def render(self) -> tuple[float, str]:
        with self.lock:
            return self.frac, f"{self.text} · {mmss(time.time() - self.t0)} elapsed"


def started_by_flame(pid: int) -> bool:
    """True if pid is a live Flame process (tests and tools must not make the hook step the frame)."""
    return oslayer.process_name(pid) == "flame"


def signal_refresh(folder: str, job_id: str, node_id: str, state: str) -> None:
    """The marker the Flame hook polls for (LTX decision 49, same JSON). Markers older than an hour
    are swept (no hook installed)."""
    try:
        os.makedirs(folder, exist_ok=True)
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            if time.time() - os.path.getmtime(path) > 3600:
                os.unlink(path)
        tmp = os.path.join(folder, f".{job_id}.tmp")
        with open(tmp, "w") as f:
            json.dump({"job_id": job_id, "node_id": node_id, "state": state, "time": time.time()}, f)
        os.replace(tmp, os.path.join(folder, f"{job_id}.json"))
        log.info(f"refresh marker written to {folder}")
    except OSError as exc:
        log.warn(f"could not write the refresh marker: {exc}")


def loggable(value, key: str = ""):
    """The request without image data (LTX decision 39: never log images): inline media and upload
    URLs become a size note; prompts and settings stay."""
    if isinstance(value, dict):
        return {k: loggable(v, k) for k, v in value.items()}
    if isinstance(value, list):
        if key == "image_urls":
            return f"<{len(value)} reference URL(s)>"
        return [loggable(v, key) for v in value]
    if isinstance(value, str) and key == "data" and len(value) > 64:
        return f"<{len(value) * 3 // 4} bytes base64>"
    return value


def generate(m: dict, api_key: str, stage: Stage, progress: Progress) -> str:
    """Runs the whole generation; returns the result path. Raises on failure or Cancel."""
    if not api_key:
        raise RouterError("no Comfy API key (Setup tab)")
    model = models.load(m["model"])
    params = m.get("params", {})
    conv = colour.Converter(m.get("colour", "Bypass"), m.get("ocio_config", ""))
    log.info(conv.describe())
    refs = []
    if m.get("input"):
        stage.set(0.05, "Preparing the reference frame")
        frame = cache.read_staged(m["input"])
        refs.append(imageio.to_png(conv.to_display(frame), model.reference_pixels(params)))
        log.info(f"reference: {frame.shape[1]}x{frame.shape[0]} -> PNG {len(refs[0])} bytes")
    if progress.cancelled():
        raise Cancelled()
    router = Router(api_key, log)
    stage.set(0.10, "Uploading the reference" if refs else "Preparing the request")
    body = model.build_request(router, params, refs, log)
    log.info(f"request {model.MODEL_ID}: {json.dumps(loggable(body))}")
    if progress.cancelled():
        raise Cancelled()
    stage.set(0.20, "Submitting")
    handle = router.submit(model.MODEL_ID, body)
    labels = {"IN_QUEUE": "Waiting in the queue", "IN_PROGRESS": "Generating", "COMPLETED": "Finishing"}

    def on_status(st: str, status: dict) -> None:
        text = labels.get(st, st)
        if st == "IN_QUEUE" and status.get("queue_position") is not None:
            text += f" (position {status['queue_position']})"
        stage.set(0.3 if st == "IN_QUEUE" else 0.5, f"{m.get('label', 'Model')}: {text}")

    response = router.wait(handle, progress.cancelled, on_status)
    stage.set(0.85, "Downloading the result")
    data = model.result_images(router, response)[0]
    stage.set(0.92, "Converting the result")
    img = imageio.fill_crop(data, int(m["width"]), int(m["height"]))
    out = conv.from_display(img)
    path = cache.write_result(m["cache_root"], m["key"], out)
    log.info(f"result: {len(data)} bytes -> {m['width']}x{m['height']} in {path}")
    return path


def main() -> int:
    manifest_path = sys.argv[1]
    ui = "--no-ui" not in sys.argv
    api_key = os.environ.pop("COMFY_API_KEY", "")
    with open(manifest_path) as f:
        m = json.load(f)
    job_id, root, key = m["job_id"], m["cache_root"], m["key"]
    log.node, log.job = m.get("node_id", "-"), job_id
    staging = os.path.dirname(os.path.abspath(manifest_path))  # the plugin's stagingDir()
    pid_file = os.path.join(staging, f"cpo_job_{job_id}.pid")
    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))
    cache.mark_pending(root, key, os.getpid())
    cache.write_status(root, job_id, "running", "")
    t0 = time.time()
    log.info(f"start: {m.get('label')} ({m['model']}) {m['width']}x{m['height']} reference={'yes' if m.get('input') else 'no'} "
             f"colour={m.get('colour')} key={key} python={sys.executable} {sys.version.split()[0]} ui={ui} "
             f"api key {len(api_key)} characters")

    progress = Progress(m.get("title", "Partner Models"), ui)
    stage = Stage()
    ticking = threading.Event()

    def tick() -> None:
        while not ticking.wait(1.0):
            progress.update(*stage.render())

    threading.Thread(target=tick, daemon=True).start()
    state, message = "failed", ""
    try:
        generate(m, api_key, stage, progress)
        state = "done"
    except Cancelled:
        state, message = "cancelled", "cancelled by user"
    except (RouterError, ValueError, OSError) as exc:
        message = str(exc)
    except Exception as exc:  # noqa: BLE001 - becomes the job's failure message
        log.error(f"unexpected {type(exc).__name__}: {exc}")
        message = f"{type(exc).__name__}: {exc}"
    finally:
        ticking.set()
        progress.close()
        cache.clear_pending(root, key)
        cache.write_status(root, job_id, state, message)
        for p in [m.get("input"), manifest_path, pid_file]:
            try:
                if p:
                    os.unlink(p)
            except FileNotFoundError:
                pass
    if started_by_flame(m.get("flame_pid", 0)):
        signal_refresh(refresh_dir(), job_id, m.get("node_id", "-"), state)
    summary = f"end: {state} {message} ({time.time() - t0:.1f} s)"
    (log.info if state == "done" else log.warn if state == "cancelled" else log.error)(summary)
    if state == "failed":
        oslayer.message("error", m.get("title", "Partner Models"), f"Generate failed: {message}", 420, ui)
    return 0 if state == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
