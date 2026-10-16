"""Comfy Router client (decision 1), standard library only.

Verified 2026-10-16 with a live key (CLAUDE.md "Router API facts") and against
docs.comfy.org/development/comfy-router/queue:
  POST {base}/v2/models/{model}/requests  (X-API-Key, Idempotency-Key, JSON body) -> 201
       {request_id, status_url, response_url, cancel_url}
  GET  status_url   -> {status: IN_QUEUE | IN_PROGRESS | COMPLETED, error_type?}; Retry-After header
                       (a hint). There is no FAILED status: a failed or cancelled request is
                       COMPLETED with error_type (e.g. content_policy_violation, cancelled,
                       queue_timeout).
  GET  response_url -> the model's own response (Krea: {status, result: {urls: [...]}})
  PUT  cancel_url   -> 202 CANCELLATION_REQUESTED or 409 ALREADY_COMPLETED. Best effort: a
                       generation that completes at the provider is charged anyway.
Partner proxy routes (model modules use them for uploads): {base}/proxy/<provider>/...
The key is sent only to the Router's own host; result URLs (e.g. gen.krea.ai) get no key.
$CPO_ROUTER_BASE overrides the base URL (tests run a fake Router).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

DEFAULT_BASE = "https://api.comfy.org"


class RouterError(Exception):
    """A failure with a message meant for the artist."""


class Cancelled(Exception):
    pass


def _explain(code: int, body: str) -> str:
    try:
        j = json.loads(body)
        detail = j.get("detail") or j.get("message") or j.get("error_type") or ""
        if isinstance(j.get("error"), dict):
            detail = j["error"].get("message") or detail
    except (ValueError, AttributeError):
        detail = body[:200]
    if code == 401:
        return f"the Comfy API key was refused (HTTP 401{': ' + detail if detail else ''})"
    if code == 402:
        return "not enough Comfy credits (HTTP 402): top up at platform.comfy.org"
    if code == 403:
        return f"not allowed (HTTP 403{': ' + detail if detail else ''})"
    return f"HTTP {code}{': ' + str(detail) if detail else ''}"


class Router:
    def __init__(self, api_key: str, log, base: str = "", timeout: float = 120.0) -> None:
        self.key, self.log, self.timeout = api_key, log, timeout
        self.base = (base or os.environ.get("CPO_ROUTER_BASE") or DEFAULT_BASE).rstrip("/")
        self.host = urllib.parse.urlsplit(self.base).netloc

    # --- HTTP ---
    def _request(self, method: str, url: str, data: bytes | None = None, headers: dict | None = None,
                 retries: int = 2) -> tuple[int, dict, bytes]:
        hdrs = dict(headers or {})
        if urllib.parse.urlsplit(url).netloc == self.host:
            hdrs["X-API-Key"] = self.key  # never to other hosts
        for attempt in range(retries + 1):
            req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.status, dict(resp.headers), resp.read()
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")
                if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                    wait = _retry_after(exc.headers, 5.0)
                    self.log.warn(f"{method} {_short(url)}: HTTP {exc.code}, retrying in {wait:.0f} s")
                    time.sleep(wait)
                    continue
                self.log.error(f"{method} {_short(url)}: HTTP {exc.code} {body[:500]}")
                raise RouterError(_explain(exc.code, body)) from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt < retries:
                    self.log.warn(f"{method} {_short(url)}: {exc}; retrying in 5 s")
                    time.sleep(5)
                    continue
                raise RouterError(f"network problem talking to {urllib.parse.urlsplit(url).netloc}: {exc}") from exc
        raise RouterError("unreachable")  # pragma: no cover

    def _json(self, method: str, url: str, body: dict | None = None, headers: dict | None = None,
              retries: int = 2) -> tuple[dict, dict]:
        hdrs = dict(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
        _code, rh, raw = self._request(method, url, data, hdrs, retries)
        try:
            return json.loads(raw.decode() or "{}"), rh
        except ValueError as exc:
            raise RouterError(f"unexpected answer from {_short(url)}: {raw[:200]!r}") from exc

    # --- Router queue ---
    def submit(self, model: str, body: dict) -> dict:
        # Fresh Idempotency-Key per submit, no automatic resubmit (a lost answer must not run twice).
        handle, _ = self._json("POST", f"{self.base}/v2/models/{model}/requests", body,
                               {"Idempotency-Key": str(uuid.uuid4())}, retries=0)
        if "request_id" not in handle:
            raise RouterError(f"the Router did not accept the request: {json.dumps(handle)[:300]}")
        self.log.info(f"router: submitted {model}, request {handle['request_id']}")
        return handle

    def wait(self, handle: dict, cancelled, on_status=None, max_seconds: float = 1800.0) -> dict:
        """Polls until COMPLETED; returns the response. cancelled() -> True asks the Router to cancel."""
        t0, last = time.time(), ""
        while True:
            if cancelled():
                self.cancel(handle)
                raise Cancelled()
            status, headers = self._json("GET", handle["status_url"])
            st = status.get("status", "")
            if st != last:
                self.log.info(f"router: {handle['request_id']} {st} after {time.time() - t0:.1f} s"
                              + (f" (queue position {status.get('queue_position')})" if "queue_position" in status else ""))
                last = st
            if on_status:
                on_status(st, status)
            if st == "COMPLETED":
                if status.get("error_type"):
                    if status["error_type"] == "cancelled":
                        raise Cancelled()
                    raise RouterError(f"the model refused or failed: {status['error_type']}")
                result, _ = self._json("GET", handle["response_url"])
                return result
            if time.time() - t0 > max_seconds:
                self.cancel(handle)
                raise RouterError(f"no result after {max_seconds / 60:.0f} minutes; cancelled")
            # Retry-After is a hint; cap it so Cancel stays responsive.
            _sleep_checking(min(_retry_after(headers, 1.0), 5.0), cancelled)

    def cancel(self, handle: dict) -> None:
        try:
            self._request("PUT", handle["cancel_url"], b"", retries=0)
            self.log.info(f"router: cancel requested for {handle['request_id']}")
        except RouterError as exc:  # 409: already completed; never fatal
            self.log.info(f"router: cancel for {handle['request_id']}: {exc}")

    # --- helpers for model modules ---
    def upload_multipart(self, path: str, field: str, filename: str, data: bytes, mime: str) -> dict:
        boundary = uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n"
                f"Content-Type: {mime}\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
        _code, _rh, raw = self._request("POST", f"{self.base}{path}", body,
                                        {"Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            out = json.loads(raw.decode())
        except ValueError as exc:
            raise RouterError(f"unexpected upload answer: {raw[:200]!r}") from exc
        return out

    def download(self, url: str) -> bytes:
        _code, _h, raw = self._request("GET", url)
        return raw


def _retry_after(headers, default: float) -> float:
    try:
        return max(0.2, float((headers or {}).get("Retry-After", default)))
    except (TypeError, ValueError):
        return default


def _sleep_checking(seconds: float, cancelled) -> None:
    end = time.time() + seconds
    while time.time() < end and not cancelled():
        time.sleep(0.1)


def _short(url: str) -> str:
    u = urllib.parse.urlsplit(url)
    return f"{u.netloc}{u.path}"
