// Krea 3 (Router model krea/krea-3). Params follow ComfyUI's Krea3ImageNode
// (comfy_api_nodes/nodes_krea.py): prompt, aspect ratio, resolution, thinking mode, precise edit,
// seed. Request body: worker/cpo/models/krea3.py.
#include <cstdio>
#include <cstdlib>

#include "model_spec.h"

namespace cpo {

namespace {

// Price badge of Krea3ImageNode (nodes_krea.py): base by resolution and thinking mode, plus
// $0.0286 per reference image (2K: up to $0.1001 per reference).
std::string krea3Cost(const ParamValues& v, int refs) {
  const bool k2 = v.count("resolution") && v.at("resolution") == "2K";
  const bool high = v.count("thinkingMode") && v.at("thinkingMode") == "high";
  const double base = k2 ? (high ? 0.1144 : 0.0858) : (high ? 0.0715 : 0.0429);
  const double lo = base + 0.0286 * refs;
  char b[64];
  if (!k2 || refs == 0)
    std::snprintf(b, sizeof b, "~$%.3f per run", lo);
  else
    std::snprintf(b, sizeof b, "~$%.3f-%.3f per run", lo, base + 0.1001 * refs);
  return b;
}

ModelSpec make() {
  ModelSpec s;
  s.pluginId = "com.janklier.partnermodels.krea3";
  s.label = "Krea 3";
  s.module = "krea3";
  s.version = "krea3-router-v1";
  s.maxReferences = 5;  // Image 1..5 (decision 15); Krea accepts up to 8
  s.columns = {"Prompt", "Output"};
  auto add = [&](ModelParam p) { s.params.push_back(p); };

  ModelParam prompt = modelParam(ParamKind::Text, "prompt", "Prompt",
                    "What to change and what to keep. Refer to the source as @Image1.", 0);
  add(prompt);
  ModelParam thinking = modelParam(ParamKind::Choice, "thinkingMode", "Thinking Mode",
                      "fast is recommended. high plans complex edits in more detail and takes longer.", 0);
  thinking.options = {"fast", "high"};
  add(thinking);
  ModelParam seed = modelParam(ParamKind::Int, "seed", "Seed",
                  "Krea rewrites the prompt before generating, so the same seed does not repeat an image.", 0);
  seed.def = 42;
  seed.min = 0;
  seed.max = 2147483647;
  add(seed);

  ModelParam aspect = modelParam(ParamKind::Choice, "aspectRatio", "Aspect Ratio",
                    "Auto follows the source frame (or the prompt without a source).", 1);
  aspect.options = {"auto", "1:1", "4:5", "3:4", "2:3", "9:16", "5:4", "4:3", "3:2", "16:9", "21:9"};
  add(aspect);
  ModelParam res = modelParam(ParamKind::Choice, "resolution", "Resolution",
                 "Size Krea generates at. The result is scaled to the source frame.", 1);
  res.options = {"1K", "2K"};
  res.def = 1;  // the ComfyUI node's default
  add(res);
  ModelParam precise = modelParam(ParamKind::Bool, "preciseEdit", "Precise Edit",
                     "Keep everything outside the edited area unchanged. Needs the source as reference.", 1);
  add(precise);

  s.costHint = krea3Cost;
  // As ComfyUI's Krea3ImageNode: references scaled to the output pixel budget (nodes_krea.py).
  s.referencePixels = [](const ParamValues& v) -> long long {
    return v.count("resolution") && v.at("resolution") == "1K" ? 1024LL * 1024 : 2048LL * 2048;
  };
  return s;
}

}  // namespace

const ModelSpec& krea3Spec() {
  static const ModelSpec spec = make();
  return spec;
}

}  // namespace cpo
