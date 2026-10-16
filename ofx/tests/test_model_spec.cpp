// Model tables obey the core's rules: unique names, Flame's 5-row columns, sane defaults, cost.
#include <sys/stat.h>

#include <cstdio>
#include <set>
#include <string>

#include "inputs.h"
#include "model_spec.h"

static int failures = 0;
#define CHECK(c)                                                       \
  do {                                                                 \
    if (!(c)) {                                                        \
      std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); \
      ++failures;                                                      \
    }                                                                  \
  } while (0)

// Rows per control in Flame (LTX ofx/CLAUDE.md): choice 2, boolean 1, int 1 (as double), text 2
// (the Edit button above it + the field, LTX decision 41).
static int rows(cpo::ParamKind k) {
  return k == cpo::ParamKind::Choice || k == cpo::ParamKind::Text ? 2 : 1;
}

static void checkSpec(const cpo::ModelSpec& s) {
  CHECK(!s.pluginId.empty() && !s.label.empty() && !s.module.empty() && !s.version.empty());
  CHECK(!s.columns.empty() && s.columns.size() <= 3);  // main + model + cache + cost + version <= 6
  CHECK(s.maxReferences >= 0 && s.maxReferences <= cpo::kMaxInputs);
  std::set<std::string> names = {"colourSpace", "generate", "status", "cacheDir", "cacheInfo",
                                 "purgeCache", "purgeAll", "costInfo", "version", "nodeId", "resultKey",
                                 "outputColour"};
  std::vector<int> used(s.columns.size(), 0);
  for (const auto& p : s.params) {
    CHECK(names.insert(p.name).second);  // unique, and no clash with the core's params
    if (p.kind == cpo::ParamKind::Text) CHECK(names.insert(p.name + "Edit").second);  // its editor button
    CHECK(p.column >= 0 && p.column < int(s.columns.size()));
    if (p.column >= 0 && p.column < int(s.columns.size())) used[size_t(p.column)] += rows(p.kind);
    if (p.kind == cpo::ParamKind::Choice) CHECK(p.def >= 0 && p.def < int(p.options.size()));
    if (p.kind == cpo::ParamKind::Int) CHECK(p.min <= p.def && p.def <= p.max);
  }
  for (size_t c = 0; c < used.size(); ++c) {
    if (used[c] > 5) std::fprintf(stderr, "%s column %s has %d rows\n", s.label.c_str(), s.columns[c].c_str(), used[c]);
    CHECK(used[c] <= 5);
  }
}

int main(int argc, char** argv) {
  // argv[1]: the source tree, to check every model has its Python module.
  std::set<std::string> ids, modules, labels;
  for (const cpo::ModelSpec* s : cpo::allModels()) {
    checkSpec(*s);
    CHECK(ids.insert(s->pluginId).second && modules.insert(s->module).second && labels.insert(s->label).second);
    CHECK(s->pluginId.rfind("com.janklier.partnermodels.", 0) == 0);
    if (argc > 1) {
      struct stat st {};
      const std::string py = std::string(argv[1]) + "/worker/cpo/models/" + s->module + ".py";
      if (stat(py.c_str(), &st) != 0) std::fprintf(stderr, "missing %s\n", py.c_str());
      CHECK(stat(py.c_str(), &st) == 0);
    }
  }
  // Decision 15: inputs fill in order from Image 1.
  CHECK(cpo::inputOrderError({false, false, false, false, false}) == -1);
  CHECK(cpo::inputOrderError({true, true, false, false, false}) == -1);
  CHECK(cpo::inputOrderError({false, true, false, false, false}) == 1);  // Image 2 without Image 1
  CHECK(cpo::inputOrderError({true, false, true, false, false}) == 2);
  CHECK(cpo::connectedInputs({true, true, true, false, false}) == 3);
  CHECK(cpo::connectedInputs({false, false, false, false, false}) == 0);
  CHECK(cpo::inputClipName(0) == "Source" && cpo::inputClipName(4) == "Image5");

  const cpo::ModelSpec& k = cpo::krea3Spec();
  CHECK(k.module == "krea3" && k.maxReferences == 5);
  // Cost from ComfyUI's Krea3ImageNode price badge.
  CHECK(k.costHint({{"resolution", "1K"}, {"thinkingMode", "fast"}}, 0) == "~$0.043 per run");
  CHECK(k.costHint({{"resolution", "1K"}, {"thinkingMode", "high"}}, 1) == "~$0.100 per run");
  CHECK(k.costHint({{"resolution", "2K"}, {"thinkingMode", "fast"}}, 0) == "~$0.086 per run");
  CHECK(k.costHint({{"resolution", "2K"}, {"thinkingMode", "fast"}}, 1) == "~$0.114-0.186 per run");
  // Nano Banana Pro: GEMINI_IMAGE_2_PRICE_BADGE.
  const cpo::ModelSpec& n = cpo::nanoBananaProSpec();
  CHECK(n.costHint({{"resolution", "2K"}}, 1) == "~$0.161 per run");
  CHECK(n.costHint({{"resolution", "4K"}}, 0) == "~$0.288 per run");
  // Decision 17: the input limits (Krea as ComfyUI's node; Nano Banana Pro ours).
  CHECK(k.referencePixels({{"resolution", "1K"}}) == 1024LL * 1024 && k.referencePixels({{"resolution", "2K"}}) == 2048LL * 2048);
  CHECK(n.referencePixels({{"resolution", "4K"}}) == 4096LL * 4096);
  std::printf("test_model_spec: %zu model(s) %s\n", cpo::allModels().size(), failures ? "FAILED" : "OK");
  return failures ? 1 : 0;
}
