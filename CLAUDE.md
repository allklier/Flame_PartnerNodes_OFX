# CLAUDE.md — Partner Models OFX for Flame (unofficial client of Comfy Router)

Design knowledge for this plugin family. It is built on the decisions of the sister project
**LTX Alpha Gen OFX** (`~/ClaudeCode/LTX_OFX`, its `CLAUDE.md` + module files): its Flame host
facts, rules and dead ends apply here unless a decision below says otherwise. "LTX n" = that
project's decision n. Tags as there: **DECIDED** (user approved), **PROPOSED**, **OPEN**,
**UNVERIFIED**. Machine-specific notes: `CLAUDE.local.md` (git-ignored).

## Goal

OFX plugins for Autodesk Flame (Rocky Linux 9 first) that send a source frame and a prompt to a
Comfy partner image model through **Comfy Router** and show the result. First model: **Krea 3**.
More models will follow around the same concept, so model-specific logic is separate from the
generic Comfy integration.

## Decisions (all DECIDED by the user, 2026-10-16, unless tagged)

- **1. Comfy Router** (`api.comfy.org`, credits only). The Cloud API v2 (workflow-based) needs a
  paid Cloud plan: submit answered 403 "API key authentication is not available for free tier
  accounts" on the user's account. Reconsider if the user subscribes (Standard $20/mo incl.
  4,200 credits/mo; 1 concurrent API workflow; same v2 contract on `*.run.comfy.app`).
- **2. Core / model split.** One bundle `PartnerModels.ofx.bundle`, one OFX effect per model,
  grouping "Partner Models". A model = a `ModelSpec` param table (`ofx/src/models/<m>.cpp`) + a
  request module (`worker/cpo/models/<m>.py`) + one line in `ofx/src/plugin.cpp`. Everything else is
  core. Each model needs its own factory *type* (`PartnerFactory<&spec>`): OFX Support keys the
  entry point on a static of the factory type (`ofxsImageEffect.h:215`).
- **3. Image models run once and hold.** The reference is the source's **first frame**
  (`getFrameRange().min`); the cache key depends only on it, so every frame shows one result.
- **4. LTX architecture** (LTX 1/35): light C++ shim + detached Python job. `render()` only
  serves from the disk cache; **Generate** stages the first frame and launches `job.py` (progress
  window with Cancel, LTX oslayer/zenity). Never auto-generates: every call costs credits. A cached
  result for the same key asks Yes/No before regenerating; no answer = no spend.
- **5. Colour as LTX 27/28/54**: Input Colour dropdown (Bypass, ACEScg, LogC4, Log3G10, LogC3,
  BMD Film Gen5; new entries at the end), PyOpenColorIO 2.6.0 in the job, `DisplayViewTransform`
  to `ACES 2.0 - SDR 100 nits (Rec.709)` / `Rec.1886 Rec.709 - Display`; the result comes back
  through the **inverse** transform (SDR-clipped by nature). Flame's config is profile 2.4: needs
  OCIO ≥ 2.4 (EPEL has 2.1.2, hence Python).
- **6. Runtime as LTX 57/60**: no bundled packages; **Install** (Setup tab) runs
  `helper/setup_helper.py` (stdlib, system python3 3.9): uv 0.12.18 (sha256) → venv on uv's
  Python 3.14.7 → numpy 2.5.3, opencolorio 2.6.0, pillow 12.3.0 (`runtime_manifest.json`) →
  import + OCIO check → config `runtime_dir/runtime_python/runtime_ready`. ~30 s, 255 MB. The job
  runs under that Python. Missing runtime = SETUP REQUIRED (LTX 38 gate).
- **7. Refresh = the LTX hook** (LTX 49): if `/opt/Autodesk/shared/python/ltx_alphagen_hook.py`
  exists, job.py writes its marker into `~/.cache/ltx-alphagen/run/refresh/` (same JSON, only for a
  live `flame` pid); else into `~/.cache/partner-models-ofx/run/refresh/`, watched by our copy
  `flame_hook/partner_models_hook.py`. Install only one of the two hooks.
- **8. API key per user only** (revised 2026-10-16 after a licensing review: the per-node key that
  was saved in setups is removed). Setup tab: "API Key" field + Save Key → user config `api_key`
  (file mode 600), field cleared, caption "Key saved HH:MM". The key reaches the job only in the environment
  (`COMFY_API_KEY`, LTX 13); logs record its length only; the Router client sends it only to the
  Router host (never to result URLs).
- **9. Output fit:** the model's image is scaled to cover the source frame and centre-cropped.
- **11. Name and terms** (user, 2026-10-16, after a licensing review). No "Comfy" in our product
  name: family **Partner Models** (group, bundle `PartnerModels.ofx.bundle`, ids
  `com.janklier.partnermodels.<model>`, folders `partner-models-ofx`, log `partner-models.log`);
  "Comfy" only where it names Comfy's products (Comfy API key, Comfy Router, credits). Never ship or
  proxy a key of ours (bring your own key). `LICENSE` stays the verbatim MPL 2.0; the terms live in
  `README.md` ("Licensing and terms": unofficial, own account, Comfy ToS, billed to the user) and
  `NOTICE` (disclaimer, service terms, OpenFX BSD notice); both ship in the bundle's Resources.
  OPEN: ask Comfy (legal@comfy.org or Discord) for a written OK before a public release.
- **12. Scaling to ~20 models** (user, 2026-10-16): keep compile-checked C++ param tables (no
  JSON-driven models: OFX would need a fixed pool of factory types); share request code per
  provider format in Python **family modules** (`cpo/models/common.py`, `gemini.py`); one
  **registry** (`ofx/src/models/registry.cpp` `allModels()`) drives the tests; a **contract test**
  (`worker/tests/test_models_contract.py`) runs every model in the C++ tables end to end against the
  fake Router, checks the module reads only params its table defines, and that no image data
  reaches the log. Every provider's body differs (Krea flat, Vertex native Gemini, Runware
  `positivePrompt`+w/h, Pika no image input), so the request mapping stays code.
  **Adding a model:** `ofx/src/models/<m>.cpp` (+ declaration in `model_spec.h`, entry in
  `registry.cpp`, CMake `cpo_models`), a factory line in `ofx/src/plugin.cpp` (same order),
  `worker/cpo/models/<m>.py` (MODEL_ID, reference_pixels, build_request, result_images), a fixture
  in `worker/tests/model_fixtures.py`; then ctest, then one live run.
- **13. Edit button for text params** (user, 2026-10-16): Flame shows a plain string in one row, so
  each Text param gets an "Edit <label>..." button (in place of the caption row) that opens
  zenity `--text-info --editable` (zenity 3.32 on Rocky 9.7) pre-filled from a mode-600 staging
  file, run while Flame waits; OK (exit 0) writes the text back, Cancel leaves it. UNVERIFIED in
  Flame: the window over Flame, multi-line prompts in Flame's one-row field.
- **10. As LTX:** logging + Collect Logs (39; `~/.cache/partner-models-ofx/logs/partner-models.log`),
  processed record (71: hidden `resultKey`; never generated → source passes through, "Not
  generated"; generated but no result → FAILED / CANCELLED / RESULT MISSING / OUT OF DATE marker
  on both outputs + failed render), Flame layout (37/52), only `eChangeUserEdit` + re-entrancy
  guard, platform layer (64, Linux only so far), MPL 2.0 (53), vendored OpenFX 1.4 (BSD), C++14,
  build on Rocky 9 GCC 11.

## Layout (Flame: columns of ≤ 5 rows, 6 columns per tab, then overflow)

Tab 1 (named after the model): [Krea 3] Input Colour, Generate, Status, Use Source ·
[Prompt] Edit Prompt... button + Prompt, Thinking Mode, Seed · [Output] Aspect Ratio, Resolution, Precise Edit ·
[Cache] Cache Folder, Cache Size, Purge Cache, Purge All · [Cost] estimate · [ ] Version.
Spacers fill models with fewer columns. Tab 2 "Setup": [API Key] caption, key, Save Key, Key status ·
[Runtime] Runtime Folder, Install, status · [Support] Debug Logging,
Collect Logs. `test_model_spec` checks every model column fits 5 rows.

## Files

- `ofx/src/core/`: `partner_effect.*` (the effect, describe, factory template), `model_spec.h`,
  `cache.*` (keys, `.img` reads, pending, sweep, staging sweep), and from LTX with renames:
  `log.*`, `user_config.*` (now mode 600), `process.*`, `platform*`, `marker.*`, `half.h`.
- `ofx/src/models/`: one table per model (params as the ComfyUI node, cost hint from its price
  badge) + `registry.cpp`. `ofx/src/plugin.cpp`: the factories, same order as the registry.
- `worker/job.py`; `worker/cpo/`: `router.py` (Router client, stdlib), `colour.py`, `imageio.py`
  (PNG, fill/crop), `cache.py` (must match `cache.h`), `log.py`, `oslayer.py` (LTX copies),
  `models/` (loader, families `common.py`, `gemini.py`; `krea3.py`, `nano_banana_pro.py`). `helper/` (Setup). `flame_hook/`. `scripts/build_remote.sh`.
- `tools/cloud_smoke_test.py`: the Cloud API v2 probe of decision 1 (kept for a later plan).
- Files: staged frame `cpo_job_<id>_in.bin` = `CPOA` header + float32 RGB; result
  `<cache>/<k[0:2]>/<key>.img` = `CPOI` header + float16 RGB at the source size, source colour space.

## Router API facts (verified 2026-10-16 with a live key and the queue docs)

- Catalog `GET /v2/models` (paginated, needs key): `krea/krea-3` listed though docs list Krea 2 only.
  Schema: `GET /v2/models/krea/krea-3/openapi.json`.
- `POST /v2/models/{m}/requests` (`X-API-Key`, `Idempotency-Key`) → 201 `{request_id,
  status_url, response_url, cancel_url}`; poll `status_url`: IN_QUEUE / IN_PROGRESS / COMPLETED
  only — **failure = COMPLETED + `error_type`** (content_policy_violation, cancelled,
  queue_timeout); `Retry-After` is a hint. `GET response_url` → model response. **Cancel = PUT
  `cancel_url`** (202 / 409), best effort: completed generations are charged. Results kept 24 h.
- Krea 3 body: `prompt`, `resolution` ("1k"/"2k") required; `aspect_ratio` (omit = auto),
  `image_urls` (≤ 8, from `POST /proxy/krea/assets` multipart `file` → `image_url`), `model`
  (berry / jam), `negative_prompt`, `regional_edit` (needs an image), `seed`, `thinking_mode`
  (fast / high / ultra). The plugin exposes the ComfyUI node's set; `@ImageN` → "image N" as the
  node does. Timing: upload ~7 s (HD PNG), generation ~10 s at 1K fast.
- **Nano Banana Pro** = `vertexai/gemini-3-pro-image` (user's choice over fal/runware/pika/wavespeed;
  the ComfyUI GeminiImage2Node backend). Native Gemini body: `contents[{role:user, parts:[{text},
  {inlineData:{mimeType,data(base64)}}]}]`, `generationConfig{responseModalities:[TEXT,IMAGE],
  imageConfig{imageSize 1K/2K/4K, aspectRatio}, seed}`, `systemInstruction`; response
  `candidates[].content.parts[].inlineData` (or fileData), refusals via `promptFeedback.blockReason`,
  `finishReason`, or text only. The Router **queue works for it** (live 2026-10-16: submit ~20 s
  with a 1.5 MB inline reference, generation 22 s, 44 s total, result correct). Price (node badge):
  1K/2K $0.1608, 4K $0.288.
- Prices (node badge): 1K fast $0.0429, high $0.0715; 2K fast $0.0858, high $0.1144; + $0.0286 per
  reference (2K: up to $0.1001).

## Tests

- ctest (4): `cache`, `model_spec` (all registry models), `load_bundle` (plugin table = registry),
  `worker_python` (dumps the C++ tables for the contract test; 37 Python tests: Krea module,
  imageio/cache layout, Router client incl. cancel/timeout/402/401, **job.py end to end against a
  fake Router** (`worker/tests/fake_router.py`: the key never reaches the image host, never in the
  log), the hook against a fake `flame`, the refresh target, OCIO round trip (needs the runtime;
  skips elsewhere)). Run with `WORKER_TEST_PYTHON=<runtime python>`.
- Live (2026-10-16, Rocky 9.7 test machine): real job.py, HD plate: Krea 3 1K fast precise edit, 22 s; Nano
  Banana Pro 1K edit, 44 s; both correct by eye. Krea 3 also tested in Flame by the user (worked).
- **UNVERIFIED in Flame** (first Flame test): fetching the first frame inside render; the layout and
  the Setup tab overflow; captions; the LTX hook refreshing our nodes; the failed-render display;
  the regenerate Yes/No; zenity window from our job.

## Conventions (as LTX)

Verify every API before use and cite it; ask when a request has two readings; two-layer testing
(unit tests + demonstration, in Flame for host behaviour); commit or push only when asked; keep
this file current and under ~250 lines; machine-specific notes go in `CLAUDE.local.md`.
Hostnames and machine paths stay out of committed files (LTX convention). `.gitignore` came from
LTX: its weights rule `models/` hid our model code until anchored to `/models/`; check
`git add --dry-run` before committing.

## Roadmap

macOS (LTX 64/65 layer), packaging + installer (LTX install.sh: bundle + hook only if no LTX hook),
system test host (LTX 67), more models (Nano Banana 2 / 2.1:
`vertexai/gemini-3.1-flash-image`, `vertexai/gemini-nano-banana-2.1`, reuse the gemini family), the Router-only Krea options (negative prompt, jam, ultra) if wanted.
