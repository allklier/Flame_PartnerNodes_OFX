# Partner Models OFX for Autodesk Flame

OFX nodes that send a frame and a prompt to a hosted image model through
[Comfy Router](https://docs.comfy.org/development/comfy-router/quickstart) and bring the result
back into Batch. Nodes so far: **Krea 3** and **Nano Banana Pro** (Google Gemini 3 Pro Image), both
for image editing and text-to-image.

> **Unofficial.** This is an independent project, not affiliated with or endorsed by Comfy
> Organization, Inc., Krea or Autodesk. You need your own Comfy account and API key, and every
> generation is billed to that account. See [Licensing and terms](#licensing-and-terms).

Status: early development (0.2). Linux (Rocky 9) only so far.

## How it works

- The node takes the **first frame** of its source, plus your prompt and settings, and shows one
  generated image on every frame of the clip. Image models don't make video.
- Nothing is sent until you press **Generate**. Each press costs Comfy credits (the **Cost**
  field shows an estimate, e.g. Krea 3 at 1K: about $0.04 without a reference, $0.07 with one;
  Nano Banana Pro: about $0.16 at 1K/2K, $0.29 at 4K).
- The request runs in the background with its own progress window and Cancel button; Flame stays
  responsive. When it finishes, the viewer refreshes and the result is cached on disk, so it
  survives reloading the Batch.
- Colour: set **Input Colour** to your source's colour space. The frame goes to the model through
  the ACES 2.0 SDR (Rec.709) view of Flame's colour config, and the result comes back through the
  inverse. Results are limited to SDR range.

## Setup

1. Install the bundle in `/usr/OFX/Plugins` and restart Flame. The node appears under
   **Partner Models**.
2. On the node's **Setup** tab, press **Install** once. It installs a small Python runtime
   (numpy, OpenColorIO, Pillow; about 250 MB, ~30 s) into the Runtime Folder.
3. Create an API key at [platform.comfy.org](https://platform.comfy.org) (it starts with
   `comfyui-`), paste it into **API Key** on the Setup tab and press **Save Key**. The key is
   stored in your own settings file (`~/.config/partner-models-ofx/config.conf`, readable only by
   you), never in Flame setups, and is sent only to Comfy.
4. Write a prompt and press **Generate**. Refer to the source frame as `@Image1`. For longer
   prompts, **Edit Prompt...** opens a larger editor window (Flame waits until you close it).

## Licensing and terms

- **This plugin** is licensed under the **Mozilla Public License 2.0** (see [LICENSE](LICENSE)).
  The vendored OpenFX code in `third_party/openfx` keeps its own BSD licence (see [NOTICE](NOTICE)).
- **Comfy's service.** The plugin is only a client. It ships no API key, runs no service and takes
  no fee. You use Comfy Router under **your own Comfy account**, you accept
  [Comfy's Terms of Service](https://www.comfy.org/terms-of-service), and all usage is billed to
  you by Comfy. Your frames and prompts are processed by Comfy and the model provider (e.g. Krea)
  under their terms.
- **Names.** Comfy, ComfyUI, Comfy Router, Krea and Flame are trademarks of their owners, named
  here only to say what the plugin works with.
- **No guarantee.** Comfy can change or stop its API at any time, which may break the plugin.
- Generated images are AI-generated content; check the model provider's terms for any disclosure
  requirements.

This is not legal advice.
