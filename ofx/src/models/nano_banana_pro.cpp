// Nano Banana Pro = Google Gemini 3 Pro Image (Router model vertexai/gemini-3-pro-image). Params
// follow ComfyUI's GeminiImage2Node (comfy_api_nodes/nodes_gemini.py): prompt, seed, aspect ratio,
// resolution. Request body: worker/cpo/models/nano_banana_pro.py (gemini family).
#include <cstdio>

#include "model_spec.h"

namespace cpo {

namespace {

// GEMINI_IMAGE_2_PRICE_BADGE (nodes_gemini.py): Pro 1K and 2K $0.1608, 4K $0.288 per image;
// references are not priced separately there.
std::string cost(const ParamValues& v, int) {
  const bool k4 = v.count("resolution") && v.at("resolution") == "4K";
  char b[48];
  std::snprintf(b, sizeof b, "~$%.3f per run", k4 ? 0.288 : 0.1608);
  return b;
}

ModelSpec make() {
  ModelSpec s;
  s.pluginId = "com.janklier.partnermodels.nanobananapro";
  s.label = "Nano Banana Pro";
  s.module = "nano_banana_pro";
  s.version = "nbpro-router-v1";
  s.maxReferences = 5;  // Image 1..5 (decision 15); Gemini accepts up to 14
  s.columns = {"Prompt", "Output"};
  s.params.push_back(modelParam(ParamKind::Text, "prompt", "Prompt",
                                "The image to create, or the edit to make to the source (@Image1).", 0));
  ModelParam seed = modelParam(ParamKind::Int, "seed", "Seed",
                               "Best effort only: the same seed and settings do not guarantee the same image.", 0);
  seed.def = 42;
  seed.max = 2147483647;
  s.params.push_back(seed);
  ModelParam aspect = modelParam(ParamKind::Choice, "aspectRatio", "Aspect Ratio",
                                 "Auto follows the source frame (or 16:9 without a source).", 1);
  aspect.options = {"auto", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"};
  s.params.push_back(aspect);
  ModelParam res = modelParam(ParamKind::Choice, "resolution", "Resolution",
                              "Size generated (2K and 4K use Gemini's own upscaler). The result is scaled to the "
                              "source frame.", 1);
  res.options = {"1K", "2K", "4K"};
  s.params.push_back(res);
  s.costHint = cost;
  // Ours (ComfyUI uploads Gemini references at full size): the output's pixel budget, which keeps
  // the inline base64 request well under Router's 100 MiB.
  s.referencePixels = [](const ParamValues& v) -> long long {
    const std::string r = v.count("resolution") ? v.at("resolution") : "1K";
    return r == "1K" ? 1024LL * 1024 : r == "2K" ? 2048LL * 2048 : 4096LL * 4096;
  };
  return s;
}

}  // namespace

const ModelSpec& nanoBananaProSpec() {
  static const ModelSpec spec = make();
  return spec;
}

}  // namespace cpo
