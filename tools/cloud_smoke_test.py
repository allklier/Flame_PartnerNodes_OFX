#!/usr/bin/env python3
"""Smoke test: run a partner image node (Krea 3 or Nano Banana 2) on Comfy Cloud
through the Comfy API v2, using the same raw HTTP calls the OFX plugin will make.

  export COMFY_API_KEY=comfyui-...
  python3 tools/cloud_smoke_test.py --check                      # is the node on Cloud?
  python3 tools/cloud_smoke_test.py --prompt "a red fox in snow" # text-to-image
  python3 tools/cloud_smoke_test.py --image plate.png --prompt "remove person"
  python3 tools/cloud_smoke_test.py --model nanobanana2 ...      # fallback model
  python3 tools/cloud_smoke_test.py --dry-run ...                # print workflow, send nothing
"""
import argparse
import json
import os
import sys
import time
import uuid
from urllib.parse import urljoin, urlparse

import requests

BASE = os.environ.get("COMFY_BASE_URL", "https://cloud.comfy.org")
NODE_CLASS = {"krea3": "Krea3ImageNode", "nanobanana2": "GeminiNanoBanana2"}


def model_node(model, prompt, resolution, seed, image_link):
    """Partner node in API format, keys as recorded from a working ComfyUI run."""
    if model == "krea3":
        inputs = {
            "model": "Krea 3",
            "model.prompt": prompt,
            "model.aspect_ratio": "auto",
            "model.resolution": resolution,
            "model.thinking_mode": "fast",
            "model.precise_edit": image_link is not None,
            "model.seed": seed,
        }
        if image_link:
            inputs["model.images.image_0"] = image_link
    else:
        inputs = {
            "prompt": prompt,
            "model": "Nano Banana 2 (Gemini 3.1 Flash Image)",
            "seed": seed,
            "aspect_ratio": "auto",
            "resolution": resolution,
            "response_modalities": "IMAGE",
            "thinking_level": "MINIMAL",
        }
        if image_link:
            inputs["images"] = image_link
    return {"inputs": inputs, "class_type": NODE_CLASS[model]}


def build_workflow(model, prompt, resolution, seed, asset):
    wf = {}
    image_link = None
    if asset:
        ref = {"__type": "core/ASSET", "info": {"id": asset["id"], "file_path": asset.get("file_path")}}
        wf["2"] = {"inputs": {"image": ref}, "class_type": "LoadImage"}
        image_link = ["2", 0]
    wf["1"] = model_node(model, prompt, resolution, seed, image_link)
    wf["3"] = {"inputs": {"filename_prefix": "ofx_smoke", "images": ["1", 0]}, "class_type": "SaveImage"}
    return wf


def check_or_die(r, what):
    if r.status_code >= 400:
        sys.exit(f"{what} failed: HTTP {r.status_code}\n{r.text[:2000]}")
    return r.json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=NODE_CLASS, default="krea3")
    ap.add_argument("--prompt", default="A red fox trotting through a snowy pine forest at dusk")
    ap.add_argument("--image", help="optional reference image (PNG)")
    ap.add_argument("--resolution", choices=["1K", "2K"], default="1K")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="smoke_out.png")
    ap.add_argument("--check", action="store_true", help="only check the node exists on Cloud")
    ap.add_argument("--dry-run", action="store_true", help="print the workflow and exit")
    a = ap.parse_args()

    if a.dry_run:
        fake = {"id": "00000000-0000-0000-0000-000000000000", "file_path": "ref.png"} if a.image else None
        print(json.dumps(build_workflow(a.model, a.prompt, a.resolution, a.seed, fake), indent=1))
        return

    key = os.environ.get("COMFY_API_KEY") or sys.exit("Set COMFY_API_KEY")
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {key}"

    # Preflight: is the node class deployed on this Cloud? (v1 endpoint, X-API-Key auth)
    info = check_or_die(requests.get(f"{BASE}/api/object_info", headers={"X-API-Key": key}, timeout=60), "object_info")
    cls = NODE_CLASS[a.model]
    print(f"{cls} on {BASE}: {'YES' if cls in info else 'NO'}")
    if a.check or cls not in info:
        return

    asset = None
    if a.image:
        with open(a.image, "rb") as f:
            r = s.post(f"{BASE}/api/v2/assets",
                       files={"file": (os.path.basename(a.image), f, "image/png")},
                       data={"content_type": "image/png", "file_path": os.path.basename(a.image), "tags": "input"},
                       headers={"Idempotency-Key": str(uuid.uuid4())}, timeout=300)
        asset = check_or_die(r, "asset upload")
        print("uploaded asset", asset["id"])

    body = {"workflow": build_workflow(a.model, a.prompt, a.resolution, a.seed, asset),
            "extra_data": {"api_key_comfy_org": key}}  # partner nodes bill against this key
    job = check_or_die(s.post(f"{BASE}/api/v2/jobs", json=body,
                              headers={"Idempotency-Key": str(uuid.uuid4())}, timeout=60), "submit")
    print("job", job["id"], job["status"])

    t0 = time.time()
    while job["status"] not in ("succeeded", "failed", "canceled", "expired"):
        time.sleep(2)
        job = check_or_die(s.get(urljoin(BASE, job["urls"]["self"]), timeout=60), "poll")
        print(f"  {time.time() - t0:5.1f}s {job['status']} queue={job.get('queue_position')}")
    if job["status"] != "succeeded":
        sys.exit(f"job {job['status']}: {json.dumps(job.get('error'), indent=1)}")

    images = [o for o in job["outputs"] if o["type"] == "image"]
    if not images:
        sys.exit(f"no image output: {json.dumps(job['outputs'], indent=1)}")
    url = urljoin(BASE, images[0]["url"])
    # Send the key only to our own host; signed storage URLs reject extra auth.
    same_host = urlparse(url).netloc == urlparse(BASE).netloc
    r = (s if same_host else requests).get(url, timeout=300)
    r.raise_for_status()
    with open(a.out, "wb") as f:
        f.write(r.content)
    print(f"wrote {a.out} ({len(r.content)} bytes) in {time.time() - t0:.1f}s; metrics={job.get('metrics')}")


if __name__ == "__main__":
    main()
