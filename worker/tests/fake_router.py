"""A local stand-in for Comfy Router and Krea's proxy/asset hosts (no credits spent).

Router host: http://127.0.0.1:<port>; image host: http://localhost:<port> (another netloc, so the
tests can check the API key never goes there). Behaviour per test via FakeRouter attributes.
"""

from __future__ import annotations

import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image

KEY = "comfyui-test-key"


def png(w: int, h: int) -> bytes:
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (x * 255 // max(1, w - 1), y * 255 // max(1, h - 1), 128)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


class FakeRouter:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict, bytes]] = []  # method, path, headers, body
        self.statuses = ["IN_QUEUE", "IN_PROGRESS", "COMPLETED"]
        self.error_type = ""      # set: COMPLETED with this error_type
        self.submit_code = 201    # e.g. 402 for no credits
        self.result_size = (64, 36)
        self.cancelled = False
        # The model's response document (tests/model_fixtures.py); default: Krea's shape.
        self.response = lambda: {"status": "completed", "job_id": "k1",
                                 "result": {"urls": [f"http://localhost:{self.port}/images/out.png"]}}
        router = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # quiet
                pass

            def _send(self, code: int, obj=None, raw: bytes | None = None, ctype="application/json", hdrs=None):
                data = raw if raw is not None else json.dumps(obj or {}).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                for k, v in (hdrs or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def _record(self) -> bytes:
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                router.requests.append((self.command, self.path, dict(self.headers), body))
                return body

            def _authed(self) -> bool:
                if self.headers.get("X-API-Key") != KEY:
                    self._send(401, {"detail": "Authentication is required.", "error_type": "unauthorized"})
                    return False
                return True

            def do_POST(self):
                self._record()
                if not self._authed():
                    return
                base = f"http://127.0.0.1:{router.port}"
                if self.path == "/proxy/krea/assets":
                    return self._send(200, {"id": "a1", "image_url": f"http://localhost:{router.port}/uploads/ref.png",
                                            "width": 64, "height": 36})
                if self.path.startswith("/v2/models/") and self.path.endswith("/requests"):
                    if router.submit_code != 201:
                        return self._send(router.submit_code, {"detail": "Insufficient credits", "error_type": "insufficient_credits"})
                    r = f"{base}{self.path}/r1"
                    return self._send(201, {"request_id": "r1", "status": "IN_QUEUE", "queue_position": 0,
                                            "status_url": r + "/status", "response_url": r, "cancel_url": r + "/cancel"})
                self._send(404, {"detail": "not found"})

            def do_PUT(self):
                self._record()
                if self.path.endswith("/cancel") and self._authed():
                    router.cancelled = True
                    return self._send(202, {"status": "CANCELLATION_REQUESTED"})
                self._send(404)

            def do_GET(self):
                self._record()
                if self.path.startswith("/images/"):
                    return self._send(200, raw=png(*router.result_size), ctype="image/png")
                if not self._authed():
                    return
                if self.path.endswith("/status"):
                    st = router.statuses.pop(0) if len(router.statuses) > 1 else router.statuses[0]
                    body = {"request_id": "r1", "status": st}
                    if st == "COMPLETED" and router.error_type:
                        body["error_type"] = router.error_type
                    return self._send(200, body, hdrs={"Retry-After": "0.2"})
                if self.path.startswith("/v2/models/") and self.path.endswith("/requests/r1"):
                    return self._send(200, router.response())
                self._send(404)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def find(self, method: str, path_part: str):
        return [r for r in self.requests if r[0] == method and path_part in r[1]]
