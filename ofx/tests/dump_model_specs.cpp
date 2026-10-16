// Writes every ModelSpec (models/registry.cpp) as JSON on stdout, for the Python contract test
// (worker/tests/test_models_contract.py). Not shipped.
#include <cstdio>
#include <string>

#include "model_spec.h"

static std::string str(const std::string& s) {
  std::string o = "\"";
  for (unsigned char c : s) {
    if (c == '"' || c == '\\') o += '\\';
    if (c < 0x20) continue;
    o += char(c);
  }
  return o + "\"";
}

int main() {
  const char* kinds[] = {"choice", "text", "int", "bool"};  // ParamKind order
  std::string out = "[";
  bool firstModel = true;
  for (const cpo::ModelSpec* s : cpo::allModels()) {
    out += std::string(firstModel ? "" : ",") + "{\"pluginId\":" + str(s->pluginId) + ",\"label\":" + str(s->label) +
           ",\"module\":" + str(s->module) + ",\"version\":" + str(s->version) +
           ",\"maxReferences\":" + std::to_string(s->maxReferences) + ",\"params\":[";
    firstModel = false;
    bool firstParam = true;
    for (const auto& p : s->params) {
      out += std::string(firstParam ? "" : ",") + "{\"name\":" + str(p.name) + ",\"kind\":\"" +
             kinds[int(p.kind)] + "\",\"def\":" + std::to_string(p.def) + ",\"defText\":" + str(p.defText) +
             ",\"options\":[";
      firstParam = false;
      for (size_t i = 0; i < p.options.size(); ++i) out += (i ? "," : "") + str(p.options[i]);
      out += "]}";
    }
    out += "]}";
  }
  std::printf("%s]\n", out.c_str());
  return 0;
}
