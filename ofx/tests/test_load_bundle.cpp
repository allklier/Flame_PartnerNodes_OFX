// Loads the built .ofx the way a host does (dlopen + the two OFX entry points)
// and checks its plugin table against the model registry. Catches unresolved symbols before Flame does.
// Usage: test_load_bundle <path to PartnerModels.ofx>
#include <dlfcn.h>

#include <cstdio>
#include <cstring>

#include "ofxCore.h"
#include "ofxImageEffect.h"
#include "model_spec.h"

int main(int argc, char** argv) {
  if (argc != 2) return 2;
  void* lib = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
  if (!lib) {
    std::fprintf(stderr, "dlopen failed: %s\n", dlerror());
    return 1;
  }
  auto count = reinterpret_cast<int (*)()>(dlsym(lib, "OfxGetNumberOfPlugins"));
  auto get = reinterpret_cast<OfxPlugin* (*)(int)>(dlsym(lib, "OfxGetPlugin"));
  if (!count || !get) {
    std::fprintf(stderr, "entry points missing\n");
    return 1;
  }
  // The bundle's plugin table must match cpo::allModels() (ofx/src/plugin.cpp vs models/registry.cpp).
  const auto& models = cpo::allModels();
  const int n = count();
  if (n != int(models.size())) {
    std::fprintf(stderr, "bundle has %d plugins, registry %zu\n", n, models.size());
    return 1;
  }
  for (int i = 0; i < n; ++i) {
    OfxPlugin* p = get(i);
    if (!p || models[size_t(i)]->pluginId != p->pluginIdentifier ||
        std::strcmp(p->pluginApi, kOfxImageEffectPluginApi) != 0) {
      std::fprintf(stderr, "plugin %d: expected %s\n", i, models[size_t(i)]->pluginId.c_str());
      return 1;
    }
    std::printf("test_load_bundle: %s api=%s v%u.%u loaded OK\n", p->pluginIdentifier, p->pluginApi,
                p->pluginVersionMajor, p->pluginVersionMinor);
  }
  return 0;
}
