# Partner Models OFX for Autodesk Flame

OFX nodes that send a frame and a prompt to a hosted image model through
[Comfy Router](https://docs.comfy.org/development/comfy-router/quickstart) and bring the result
back into Batch. Nodes so far: **Krea 3** and **Nano Banana Pro** (Google Gemini 3 Pro Image), both
for image editing and text-to-image.

> **Unofficial.** This is an independent project, not affiliated with or endorsed by Comfy
> Organization, Inc., Krea or Autodesk. You need your own Comfy account and API key, and every
> generation is billed to that account. See [Licensing and terms](#licensing-and-terms).
>
> **Provided as is.** These nodes are built on Comfy Router's API as it works today. If Comfy
> changes that API or access to its endpoints, the nodes may stop working without warning.

Status: first release (0.1). Linux (Rocky 9, Flame 2027) and macOS (Apple Silicon).

## How it works

- The node takes the **first frame** of its source, plus your prompt and settings, and shows one
  generated image on every frame of the clip. Image models don't make video.
- Nothing is sent until you press **Generate**. Each press costs Comfy credits (the **Cost**
  field shows an estimate, e.g. Krea 3 at 1K: about $0.04 without a reference, $0.07 with one;
  Nano Banana Pro: about $0.16 at 1K/2K, $0.29 at 4K).
- The request runs in the background with its own progress window and Cancel button; Flame stays
  responsive. When it finishes, the viewer refreshes and the result is cached on disk, so it
  survives reloading the Batch.
- Inputs: **Image 1** to **Image 5**, connected in order from Image 1. The first frame of each is
  sent; refer to them in the prompt as `@Image1`, `@Image2`, ... With nothing connected the node
  generates from the prompt alone at 1920x1080. Inputs larger than the model takes are scaled down
  before upload; Generate tells you first, so you can scale them yourself instead.
- Colour: set **Input Colour** to your inputs' colour space. They go to the model through the
  ACES 2.0 SDR (Rec.709) view of Flame's colour config. **Output** then chooses what you get:
  **BT.1886 Display** (the model's image, tagged Rec.1886 so Flame converts it downstream),
  **Source Colour Space** (converted back to the Input Colour, limited to SDR range) or **Bypass**
  (the model's image untouched). Switching Output doesn't run the model again.

## Setup

1. Quit Flame, unpack the release for your platform and run `sudo ./install.sh` in its folder
   (`sudo ./install.sh --uninstall` removes it). It installs the bundle in `/usr/OFX/Plugins`
   (macOS: `/Library/OFX/Plugins`) and, unless LTX Alpha Gen's is already there, a small Flame
   Python hook that refreshes the viewer when a result arrives. Start Flame: the nodes are under
   **Partner Models**.
2. On the node's **Setup** tab, press **Install** once (macOS needs the Command Line Tools:
   `xcode-select --install`). It installs a small Python runtime
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
- **Provided as is, without warranty.** The nodes are built against the current Comfy Router API
  and the model endpoints it offers. Comfy can change, restrict or discontinue that API, or access
  to any endpoint or model, at any time; the nodes may then stop working without warning, and there
  is no promise of a fix. (The MPL 2.0 disclaimer of warranty and limitation of liability, sections
  6 and 7 of [LICENSE](LICENSE), apply.)
- Generated images are AI-generated content; check the model provider's terms for any disclosure
  requirements.

This is not legal advice.
