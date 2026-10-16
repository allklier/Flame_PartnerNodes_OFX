// Partner Models OFX: the generic effect (CLAUDE.md decisions 2-10, built on LTX Alpha Gen's).
// - Render never calls the network: it serves the generated image from the disk cache, else the
//   source or a marker (Flame runs every OFX action on its UI thread; LTX "Flame host behaviour").
// - Generate stages the source's first frame (decision 3) and launches worker/job.py detached
//   under the runtime's Python (decisions 4-6); the job converts colour, calls Comfy Router,
//   writes the result into the cache and drops a refresh marker for the Flame hook (decision 7).
// - The result is held on every frame: the cache key depends only on the first frame.
// - Layout follows Flame's rules (LTX decision 37): columns of <= 5 rows, 6 columns per tab.

#include "partner_effect.h"

#include <dlfcn.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

#include <algorithm>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <fstream>
#include <memory>
#include <mutex>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <typeinfo>
#include <vector>

#include "cache.h"
#include "half.h"
#include "log.h"
#include "marker.h"
#include "platform.h"
#include "process.h"
#include "user_config.h"

#ifndef CPO_VERSION
#define CPO_VERSION "0.0.0"
#endif
#ifndef CPO_GIT
#define CPO_GIT "unknown"
#endif

namespace cpo {

namespace {

// Input Colour (decision 5, LTX 27): OCIO names in worker/cpo/colour.py. New entries at the end.
const char* const kColourSpaces[] = {"Bypass", "ACEScg", "LogC4", "Log3G10", "LogC3", "BMD Film Gen5"};

// Core params. Model params come from the ModelSpec; Text params get "<name>Caption" above them.
constexpr const char* kPColour = "colourSpace";
constexpr const char* kPGenerate = "generate";
constexpr const char* kPStatus = "status";
constexpr const char* kPUseSource = "useSource";
constexpr const char* kPCacheDir = "cacheDir";
constexpr const char* kPCacheInfo = "cacheInfo";
constexpr const char* kPPurgeNode = "purgeCache";
constexpr const char* kPPurgeAll = "purgeAll";
constexpr const char* kPCost = "costInfo";
constexpr const char* kPKeyCaption = "apiKeyCaption";
constexpr const char* kPApiKey = "apiKey";          // per user: saved to the config, never in setups
constexpr const char* kPSaveKey = "saveApiKey";
constexpr const char* kPKeyStatus = "apiKeyStatus";
constexpr const char* kPRuntimeDir = "runtimeDir";
constexpr const char* kPInstall = "installRuntime";
constexpr const char* kPSetupStatus = "setupStatus";
constexpr const char* kPDebugLog = "debugLogging";
constexpr const char* kPCollectLogs = "collectLogs";
// Hidden, saved with the setup.
constexpr const char* kPNodeId = "nodeId";
constexpr const char* kPResultKey = "resultKey";  // processed record (LTX 71): key of the last Generate

constexpr const char* kKeyCaptionDefault = "Comfy API key (yours):";

std::string resourcesDir() {
  Dl_info info{};
  if (!dladdr(reinterpret_cast<void*>(&resourcesDir), &info) || !info.dli_fname) return "";
  std::string p = info.dli_fname;  // .../Contents/Linux-x86-64/PartnerModels.ofx
  p = p.substr(0, p.rfind('/'));
  p = p.substr(0, p.rfind('/'));
  return p + "/Resources";
}

std::string homeDir() {
  const char* h = std::getenv("HOME");
  return h ? h : "/tmp";
}

std::string timeStr(const char* fmt) {
  std::time_t t = std::time(nullptr);
  std::tm tm{};
  localtime_r(&t, &tm);
  char b[32];
  std::strftime(b, sizeof b, fmt, &tm);
  return b;
}

std::string trimSlashes(std::string p) {
  while (p.size() > 1 && p.back() == '/') p.pop_back();
  return p;
}

std::string randomId() {
  std::random_device rd;
  char b[9];
  std::snprintf(b, sizeof b, "%08x", rd());
  return b;
}

// Value of "key" in a status JSON written by Python's json.dump (flat object).
std::string jsonField(const std::string& j, const std::string& key) {
  const std::string k = "\"" + key + "\": ";
  const auto p = j.find(k);
  if (p == std::string::npos) return "";
  const size_t b = p + k.size();
  if (b < j.size() && j[b] == '"') return j.substr(b + 1, j.find('"', b + 1) - b - 1);
  const auto e = j.find_first_of(",}", b);
  return j.substr(b, e - b);
}

std::string readFile(const std::string& path) {
  std::ifstream in(path);
  std::stringstream ss;
  ss << in.rdbuf();
  return ss.str();
}

// JSON string literal; prompts can hold quotes, backslashes and control characters.
std::string jsonStr(const std::string& s) {
  std::string o = "\"";
  for (unsigned char c : s) {
    if (c == '"' || c == '\\') {
      o += '\\';
      o += char(c);
    } else if (c < 0x20) {
      char b[8];
      std::snprintf(b, sizeof b, "\\u%04x", c);
      o += b;
    } else {
      o += char(c);
    }
  }
  return o + "\"";
}

uint64_t hashImage(const OFX::Image& img) {
  const OfxRectI b = img.getBounds();
  const size_t rowBytes = size_t(b.x2 - b.x1) * 4 * (img.getPixelComponents() == OFX::ePixelComponentRGBA ? 4 : 3);
  uint64_t h = 1469598103934665603ULL;
  for (int y = b.y1; y < b.y2; ++y) {
    const auto* row = static_cast<const unsigned char*>(img.getPixelAddress(b.x1, y));
    size_t i = 0;
    for (; i + 8 <= rowBytes; i += 8) {
      uint64_t w;
      std::memcpy(&w, row + i, 8);
      h = (h ^ w) * 1099511628211ULL;
    }
    for (; i < rowBytes; ++i) h = (h ^ row[i]) * 1099511628211ULL;
  }
  return h;
}

int componentsOf(const OFX::Image& img) {
  switch (img.getPixelComponents()) {
    case OFX::ePixelComponentRGBA: return 4;
    case OFX::ePixelComponentRGB: return 3;
    default: return 1;
  }
}

// Runtime installed by Setup (decision 6): the venv Python with numpy, OpenColorIO, Pillow.
struct RuntimeState {
  bool ready = false;
  std::string python;
};

RuntimeState runtimeState() {
  const UserConfig cfg = loadUserConfig();
  RuntimeState s;
  if (cfg.count("runtime_python")) s.python = cfg.at("runtime_python");
  struct stat st {};
  s.ready = cfg.count("runtime_ready") && !s.python.empty() && stat(s.python.c_str(), &st) == 0;
  return s;
}

std::string defaultRuntimeDir() { return homeDir() + "/.local/share/partner-models-ofx/runtime"; }

std::vector<std::string> environmentSnapshot(const std::string& resources) {
  std::vector<std::string> out;
  out.push_back(std::string("plugin: Partner Models ") + CPO_VERSION + " git " + CPO_GIT + " built " + __DATE__ +
                " " + __TIME__);
  if (const auto* d = OFX::getImageEffectHostDescription())
    out.push_back("host: " + d->hostName + " / " + d->hostLabel + " version " + d->versionLabel);
  for (const auto& line : platformSnapshot()) out.push_back(line);
  out.push_back("resources: " + resources);
  out.push_back("log: " + logPath());
  out.push_back("config: " + userConfigPath());
  const UserConfig cfg = loadUserConfig();
  out.push_back("cache: " + cacheSettings(cfg).root);
  for (const auto& kv : cfg) {  // never secrets (decision 8; LTX 39)
    if (kv.first.find("key") != std::string::npos || kv.first.find("token") != std::string::npos)
      out.push_back("config." + kv.first + ": <" + std::to_string(kv.second.size()) + " characters>");
    else
      out.push_back("config." + kv.first + ": " + kv.second);
  }
  return out;
}

std::atomic<unsigned> gJobSeq{0};

class PartnerEffect : public OFX::ImageEffect {
 public:
  PartnerEffect(OfxImageEffectHandle handle, const ModelSpec& spec) : ImageEffect(handle), spec_(spec) {
    src_ = fetchClip(kOfxImageEffectSimpleSourceClipName);
    dst_ = fetchClip(kOfxImageEffectOutputClipName);
    colour_ = fetchChoiceParam(kPColour);
    status_ = fetchStringParam(kPStatus);
    useSource_ = spec_.maxReferences > 0 ? fetchBooleanParam(kPUseSource) : nullptr;
    cacheDir_ = fetchStringParam(kPCacheDir);
    cacheInfo_ = fetchStringParam(kPCacheInfo);
    cost_ = fetchStringParam(kPCost);
    keyCaption_ = fetchStringParam(kPKeyCaption);
    apiKey_ = fetchStringParam(kPApiKey);
    keyStatus_ = fetchStringParam(kPKeyStatus);
    runtimeDir_ = fetchStringParam(kPRuntimeDir);
    setupStatus_ = fetchStringParam(kPSetupStatus);
    debugLog_ = fetchBooleanParam(kPDebugLog);
    nodeIdParam_ = fetchStringParam(kPNodeId);
    resultKey_ = fetchStringParam(kPResultKey);
    try {
      nodeIdParam_->getValue(nodeId_);
      if (nodeId_.empty()) {
        nodeId_ = randomId();  // saved with the setup; copies of a node share it
        nodeIdParam_->setValue(nodeId_);
      }
      LogScope scope(nodeId_);
      LOGI("createInstance %p (%s)", static_cast<void*>(this), spec_.label.c_str());
      // Per-user values are not stored in setups; mirror them from the user config.
      const UserConfig cfg = loadUserConfig();
      cacheDir_->setValue(cacheSettings(cfg).root);
      runtimeDir_->setValue(cfg.count("runtime_dir") ? cfg.at("runtime_dir") : defaultRuntimeDir());
      debugLog_->setValue(logLevel() == LogLevel::Debug);
      refreshSetupUi();
      refreshCacheInfo();
      refreshCost();
    } catch (const std::exception& e) {
      LOGE("createInstance: setting param values FAILED: %s [%s]", e.what(), typeid(e).name());
    }
  }

  ~PartnerEffect() override {
    LogScope scope(nodeId_);
    stopWatcher();
    stopSetupWatcher();
    LOGI("destroyInstance %p", static_cast<void*>(this));
  }

  void changedParam(const OFX::InstanceChangedArgs& args, const std::string& name) override {
    // Flame reports our own setValue() calls back as changedParam (plugin edit); reacting to those
    // recursed until Flame crashed (LTX Flame test 2). Only user edits, never re-entrantly.
    if (args.reason != OFX::eChangeUserEdit || inChangedParam_) return;
    struct Guard {
      bool& b;
      explicit Guard(bool& b) : b(b) { b = true; }
      ~Guard() { b = false; }
    } guard(inChangedParam_);
    LogScope scope(nodeId_);
    LOGI("changedParam %s (user) time=%g", name.c_str(), args.time);
    try {
      handleParam(name);
    } catch (const std::exception& e) {
      LOGE("changedParam %s FAILED: %s [%s]", name.c_str(), e.what(), typeid(e).name());
      throw;
    }
    refreshCost();
    refreshSetupUi();
  }

  void render(const OFX::RenderArguments& args) override {
    LogScope scope(nodeId_);
    std::unique_ptr<OFX::Image> out(dst_->fetchImage(args.time));
    if (!out) {
      LOGE("render t=%g: host returned no output image", args.time);
      OFX::throwSuiteStatusException(kOfxStatFailed);
    }
    const OfxRectI db = out->getBounds();
    std::unique_ptr<OFX::Image> src, ref;
    std::vector<float> result;  // w*h*3, rows top-down, at the reference frame's size
    std::vector<float> marker;  // w*h grey, rows top-down
    std::string message, caption;
    bool loud = false;          // the marker replaces the image (not a working pass-through)
    bool failRender = false;    // generated before, but no result now (LTX 71)
    OfxRectI rb = db;           // bounds of the reference frame (the result's size)
    const bool setupRequired = !runtimeState().ready;
    if (runtimeWasMissing_ && !setupRequired) {
      LOGI("render: the runtime is now installed; enabling the node's params");
      refreshSetupUi();
    }
    runtimeWasMissing_ = setupRequired;

    src.reset(src_->fetchImage(args.time));
    if (setupRequired) {
      message = "Setup required: install the runtime in the Setup tab.";
      caption = "SETUP REQUIRED";
      loud = true;
    } else if (!src) {
      message = "No source image (is the input connected?).";
      caption = "NOT CONNECTED";
      loud = true;
    } else if (src->getPixelDepth() != OFX::eBitDepthFloat) {
      message = "Only 32-bit float images are supported.";
      caption = "NOT SUPPORTED";
      loud = true;
    } else {
      ref.reset(src_->fetchImage(firstFrame()));  // decision 3: the result belongs to frame 1
      if (!ref) ref.reset(src_->fetchImage(args.time));
      rb = ref->getBounds();
      const int w = rb.x2 - rb.x1, h = rb.y2 - rb.y1;
      const std::string key = currentKey(*ref);
      std::vector<uint16_t> half;
      if (readResult(cacheRoot(), key, uint32_t(w), uint32_t(h), half)) {
        result.resize(half.size());
        halfToFloat(half.data(), result.data(), result.size());
      } else if (isPending(cacheRoot(), key)) {
        message = "Generating: the result is not ready yet.";
        caption = "GENERATING";
      } else if (!generatedBefore()) {
        message = "Not generated: press Generate.";  // source passes through (LTX 71)
      } else {
        failRender = loud = true;
        std::string stored;
        resultKey_->getValue(stored);
        const std::string status = lastJobStatus();
        const std::string state = jsonField(status, "state");
        if (stored == key && state == "failed") {
          message = "Generate failed: " + jsonField(status, "message") + ". Press Generate to try again.";
          caption = "FAILED";
        } else if (stored == key && state == "cancelled") {
          message = "Generate was cancelled. Press Generate to try again.";
          caption = "CANCELLED";
        } else if (stored == key) {
          message = "Result missing: the cached image is gone (cache purged, or another machine). Press Generate.";
          caption = "RESULT MISSING";
        } else {
          message = "Out of date: the source, prompt or settings changed since Generate. Press Generate.";
          caption = "OUT OF DATE";
        }
      }
      LOGD("render t=%g key=%s %s", args.time, key.c_str(), result.empty() ? (caption.empty() ? "pass-through" : caption.c_str()) : "cache hit");
    }

    const int w = rb.x2 - rb.x1, h = rb.y2 - rb.y1;
    if (result.empty() && !caption.empty()) drawMarker(marker, w, h, caption);
    const bool srcOk = src && src->getPixelDepth() == OFX::eBitDepthFloat;
    const int sc = srcOk ? componentsOf(*src) : 0;
    const OfxRectI sb = srcOk ? src->getBounds() : db;
    const OfxRectI& win = args.renderWindow;
    const int comps = dst_->getPixelComponents() == OFX::ePixelComponentRGBA  ? 4
                      : dst_->getPixelComponents() == OFX::ePixelComponentRGB ? 3
                                                                               : 1;
    for (int y = std::max(win.y1, db.y1); y < std::min(win.y2, db.y2); ++y) {
      auto* px = static_cast<float*>(out->getPixelAddress(std::max(win.x1, db.x1), y));
      const int row = (h - 1) - (y - rb.y1);  // OFX is bottom-up, results top-down
      for (int x = std::max(win.x1, db.x1); x < std::min(win.x2, db.x2); ++x) {
        const int col = x - rb.x1;
        const bool inside = row >= 0 && row < h && col >= 0 && col < w;
        const size_t i = inside ? size_t(row) * w + col : 0;
        float rgb[3] = {0.0f, 0.0f, 0.0f}, a = 1.0f;
        if (!result.empty()) {
          if (inside) std::memcpy(rgb, &result[i * 3], sizeof rgb);
        } else if (loud) {
          rgb[0] = rgb[1] = rgb[2] = a = inside && !marker.empty() ? marker[i] : 0.0f;
        } else {  // not generated / generating: the source passes through; matte shows the marker
          const bool inSrc = srcOk && x >= sb.x1 && x < sb.x2 && y >= sb.y1 && y < sb.y2;
          if (inSrc) {
            const auto* sp = static_cast<const float*>(src->getPixelAddress(x, y));
            for (int k = 0; k < 3; ++k) rgb[k] = sp[k];
            a = sc == 4 ? sp[3] : 1.0f;
          }
          if (!marker.empty()) a = inside ? marker[i] : 0.0f;
        }
        if (comps == 1) {
          *px++ = a;
          continue;
        }
        *px++ = rgb[0];
        *px++ = rgb[1];
        *px++ = rgb[2];
        if (comps == 4) *px++ = a;
      }
    }
    try {
      if (message.empty())
        clearPersistentMessage();
      else
        setPersistentMessage(failRender ? OFX::Message::eMessageError : OFX::Message::eMessageWarning, "", message);
    } catch (const std::exception& e) {
      LOGW("render: persistent message FAILED: %s", e.what());
    }
    if (failRender) {  // after filling the output, in case the host shows it anyway
      LOGD("render t=%g: %s, failing the render (LTX decision 71)", args.time, caption.c_str());
      OFX::throwSuiteStatusException(kOfxStatFailed);
    }
  }

 private:
  void handleParam(const std::string& name) {
    if (name == kPGenerate) {
      generate();
    } else if (name == kPPurgeNode) {
      purgeNode();
    } else if (name == kPPurgeAll) {
      const uint64_t freed = purgeAll(cacheRoot());
      LOGI("purgeAll %s: %.1f MB freed", cacheRoot().c_str(), freed / 1048576.0);
      refreshCacheInfo();
    } else if (name == kPSaveKey) {
      saveApiKey();
    } else if (name == kPInstall) {
      installRuntime();
    } else if (name == kPCacheDir || name == kPRuntimeDir) {
      std::string v;
      (name == kPCacheDir ? cacheDir_ : runtimeDir_)->getValue(v);
      v = trimSlashes(v);
      UserConfig cfg = loadUserConfig();
      cfg[name == kPCacheDir ? "cache_dir" : "runtime_dir"] = v;
      saveUserConfig(cfg);
      LOGI("%s set to %s", name.c_str(), v.c_str());
      refreshCacheInfo();
    } else if (name == kPDebugLog) {
      bool v = false;
      debugLog_->getValue(v);
      UserConfig cfg = loadUserConfig();
      cfg["log_level"] = v ? "debug" : "info";
      saveUserConfig(cfg);
      setLogLevel(v ? LogLevel::Debug : LogLevel::Info);
      LOGI("debug logging %s", v ? "on" : "off");
    } else if (name == kPCollectLogs) {
      collectLogs();
    } else {
      for (const auto& p : spec_.params)
        if (p.kind == ParamKind::Text && name == p.name + "Edit") editText(p);
    }
  }

  // The pop-out editor for a text param: zenity's editable text window, run while Flame waits (the
  // same as Flame's own popups). zenity prints the edited text on OK (exit 0); Cancel or closing
  // the window exits 1 and leaves the param unchanged. Its GTK warnings go to /dev/null, so only
  // the text reaches us. The current text travels in a mode-600 file in the staging folder.
  void editText(const ModelParam& p) {
    const char* zenity = "/usr/bin/zenity";
    if (access(zenity, X_OK) != 0) return error("The editor needs zenity (sudo dnf install zenity).");
    OFX::StringParam* param = fetchStringParam(p.name);
    std::string text;
    param->getValue(text);
    const std::string tmp = stagingDir() + "/cpo_edit_" + std::to_string(getpid()) + "_" + randomId() + ".txt";
    {
      const int fd = open(tmp.c_str(), O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);
      if (fd < 0) return error("Could not open the editor: " + std::string(std::strerror(errno)));
      const bool ok = write(fd, text.data(), text.size()) == ssize_t(text.size());
      close(fd);
      if (!ok) {
        unlink(tmp.c_str());
        return error("Could not open the editor: writing " + tmp + " failed.");
      }
    }
    std::string err;
    WorkerProcess z;
    std::vector<std::string> lines;
    const bool started = z.start({"/bin/sh", "-c", "exec \"$0\" \"$@\" 2>/dev/null", zenity, "--text-info",
                                  "--editable", "--title=" + spec_.label + " - " + p.label, "--width=760",
                                  "--height=440", "--filename=" + tmp},
                                 cleanEnvironment(), err);
    if (started)
      while (z.readLines(200, lines)) {
      }
    const int status = started ? z.wait() : -1;
    unlink(tmp.c_str());
    if (!started) return error("Could not open the editor: " + err);
    if (!(WIFEXITED(status) && WEXITSTATUS(status) == 0)) {
      LOGI("editText %s: cancelled (status %d)", p.name.c_str(), status);
      return;
    }
    std::string edited;
    for (size_t i = 0; i < lines.size(); ++i) edited += (i ? "\n" : "") + lines[i];
    LOGI("editText %s: %zu -> %zu characters", p.name.c_str(), text.size(), edited.size());
    if (edited != text) param->setValue(edited);
  }

  double firstFrame() { return std::floor(src_->getFrameRange().min + 0.5); }

  bool useSource() {
    bool v = false;
    if (useSource_) useSource_->getValue(v);
    return v;
  }

  // The model's param values as strings (model_spec.h).
  ParamValues paramValues() {
    ParamValues v;
    for (const auto& p : spec_.params) {
      if (p.kind == ParamKind::Choice) {
        int i = 0;
        fetchChoiceParam(p.name)->getValue(i);
        v[p.name] = i >= 0 && i < int(p.options.size()) ? p.options[size_t(i)] : "";
      } else if (p.kind == ParamKind::Int) {
        int i = 0;
        fetchIntParam(p.name)->getValue(i);
        v[p.name] = std::to_string(i);
      } else if (p.kind == ParamKind::Bool) {
        bool b = false;
        fetchBooleanParam(p.name)->getValue(b);
        v[p.name] = b ? "1" : "0";
      } else {
        std::string s;
        fetchStringParam(p.name)->getValue(s);
        v[p.name] = s;
      }
    }
    return v;
  }

  // Everything besides the reference pixels that changes the result.
  std::string paramSignature() {
    int colour = 0;
    colour_->getValue(colour);
    std::string sig = "v1|model=" + spec_.version + "|cs=" + kColourSpaces[colour] + "|src=" + (useSource() ? "1" : "0");
    for (const auto& kv : paramValues()) sig += "|" + kv.first + "=" + kv.second;
    return sig;
  }

  std::string currentKey(const OFX::Image& ref) {
    return resultKey(useSource() ? hashImage(ref) : 0, paramSignature());
  }

  bool generatedBefore() {
    std::string v;
    resultKey_->getValue(v);
    return !v.empty();
  }

  std::string cacheRoot() { return cacheSettings(loadUserConfig()).root; }

  std::string lastJobStatus() {
    std::string id;
    {
      std::lock_guard<std::mutex> lock(jobMutex_);
      id = lastJobId_;
    }
    return id.empty() ? "" : readFile(cacheRoot() + "/jobs/" + id + ".json");
  }

  // Decision 8: the user's key, from the user config only (never saved in setups).
  std::string apiKey() {
    const UserConfig cfg = loadUserConfig();
    return cfg.count("api_key") ? cfg.at("api_key") : "";
  }

  void setIfChanged(OFX::StringParam* p, const std::string& v) {
    try {
      std::string cur;
      p->getValue(cur);
      if (cur != v) p->setValue(v);
    } catch (const std::exception& e) {
      LOGW("setValue FAILED: %s", e.what());
    }
  }

  void refreshCacheInfo() {
    char b[48];
    std::snprintf(b, sizeof b, "%.2f GB used", cacheBytes(cacheRoot()) / 1073741824.0);
    setIfChanged(cacheInfo_, b);
  }

  void refreshCost() {
    if (!spec_.costHint) return;
    try {
      setIfChanged(cost_, spec_.costHint(paramValues(), useSource() ? 1 : 0));
    } catch (const std::exception& e) {
      LOGW("refreshCost FAILED: %s", e.what());
    }
  }

  // Disable the generating params while the runtime is missing (LTX decision 38).
  void refreshSetupUi() {
    const RuntimeState rt = runtimeState();
    std::vector<std::string> gated = {kPColour, kPGenerate, kPPurgeNode};
    if (useSource_) gated.push_back(kPUseSource);
    for (const auto& p : spec_.params) gated.push_back(p.name);
    for (const auto& p : gated) {
      try {
        getParam(p)->setEnabled(rt.ready);
      } catch (const std::exception& e) {
        LOGW("setEnabled(%s) FAILED: %s", p.c_str(), e.what());
      }
    }
    const std::string key = apiKey();
    // <= 28 characters: Flame cuts text at ~30 (LTX test 2).
    setIfChanged(setupStatus_, std::string("Runtime: ") + (rt.ready ? "OK" : "NOT INSTALLED"));
    setIfChanged(keyStatus_, key.empty() ? "Key: missing" : "Key: saved");
  }

  void error(const std::string& msg) {
    LOGW("error shown to user: %s", msg.c_str());
    sendMessage(OFX::Message::eMessageError, "", msg);
  }

  // Stages the reference frame (float32 RGB, rows top-down) for job.py. Plain write(), no mmap
  // (LTX transport.h: a full tmpfs must fail with ENOSPC, not SIGBUS inside Flame).
  bool stageFrame(const OFX::Image& img, const std::string& path, std::string& err) {
    const OfxRectI b = img.getBounds();
    const int w = b.x2 - b.x1, h = b.y2 - b.y1, sc = componentsOf(img);
    FrameFileHeader hdr{};
    std::memcpy(hdr.magic, "CPOA", 4);
    hdr.version = kFileVersion;
    hdr.width = uint32_t(w);
    hdr.height = uint32_t(h);
    hdr.frames = 1;
    hdr.channels = 3;
    const int fd = open(path.c_str(), O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);
    if (fd < 0) {
      err = "cannot create " + path + ": " + std::strerror(errno);
      return false;
    }
    const size_t rowBytes = size_t(w) * 3 * sizeof(float);
    bool ok = posix_fallocate(fd, 0, off_t(sizeof hdr + rowBytes * size_t(h))) == 0 &&
              write(fd, &hdr, sizeof hdr) == ssize_t(sizeof hdr);
    std::vector<float> row(size_t(w) * 3);
    for (int r = 0; ok && r < h; ++r) {
      const auto* p = static_cast<const float*>(img.getPixelAddress(b.x1, b.y2 - 1 - r));
      for (int x = 0; x < w; ++x)
        for (int k = 0; k < 3; ++k) row[size_t(x) * 3 + k] = p[size_t(x) * sc + k];
      ok = write(fd, row.data(), rowBytes) == ssize_t(rowBytes);
    }
    if (!ok) err = std::string("staging failed (") + std::strerror(errno) + ") in " + stagingDir();
    close(fd);
    if (!ok) unlink(path.c_str());
    return ok;
  }

  void generate() {
    const RuntimeState rt = runtimeState();
    if (!rt.ready) return error("Install the runtime first (Setup tab).");
    const std::string key = apiKey();
    if (key.empty()) return error("No Comfy API key: enter yours in the Setup tab and press Save Key.");
    const double first = firstFrame();
    std::unique_ptr<OFX::Image> ref;
    try {
      ref.reset(src_->fetchImage(first));
    } catch (const std::exception& e) {
      LOGE("generate: fetchImage(%g) threw: %s", first, e.what());
    }
    if (!ref) return error("Flame did not provide the source's first frame.");
    if (ref->getPixelDepth() != OFX::eBitDepthFloat) return error("Only 32-bit float images are supported.");
    const OfxRectI b = ref->getBounds();
    const int w = b.x2 - b.x1, h = b.y2 - b.y1;
    const std::string root = cacheRoot();
    const std::string rkey = currentKey(*ref);
    if (isPending(root, rkey)) return error("This node is already generating these settings.");
    std::vector<uint16_t> existing;
    if (readResult(root, rkey, uint32_t(w), uint32_t(h), existing)) {
      // Every run costs credits: an unanswered question never spends them.
      const auto reply = sendMessage(OFX::Message::eMessageQuestion, "",
                                     "A result for exactly these settings is already cached.\n\nGenerate "
                                     "again? This replaces it and costs credits. (A new Seed gives a "
                                     "variation and keeps this one.)");
      LOGI("generate: result cached; regenerate? reply %d", int(reply));
      if (reply != OFX::Message::eMessageReplyYes) return;
    }
    const std::string jobId = std::to_string(getpid()) + "-" + std::to_string(gJobSeq++) + "-" +
                              std::to_string(std::time(nullptr));
    LogScope scope(nodeId_, jobId);
    const bool withSource = useSource();
    const std::string input = stagingDir() + "/cpo_job_" + jobId + "_in.bin";
    std::string err;
    if (withSource && !stageFrame(*ref, input, err)) return error(err);
    int colour = 0;
    colour_->getValue(colour);
    const ParamValues values = paramValues();
    std::ostringstream js;
    js << "{\"job_id\":" << jsonStr(jobId) << ",\"node_id\":" << jsonStr(nodeId_)
       << ",\"model\":" << jsonStr(spec_.module) << ",\"label\":" << jsonStr(spec_.label)
       << ",\"input\":" << jsonStr(withSource ? input : "") << ",\"width\":" << w << ",\"height\":" << h
       << ",\"colour\":" << jsonStr(kColourSpaces[colour]) << ",\"ocio_config\":\"\",\"params\":{";
    bool firstParam = true;
    for (const auto& kv : values) {
      js << (firstParam ? "" : ",") << jsonStr(kv.first) << ":" << jsonStr(kv.second);
      firstParam = false;
    }
    js << "},\"cache_root\":" << jsonStr(root) << ",\"key\":" << jsonStr(rkey) << ",\"flame_pid\":" << getpid()
       << ",\"title\":" << jsonStr("Partner Models - " + spec_.label) << "}";
    const std::string manifest = stagingDir() + "/cpo_job_" + jobId + ".json";
    {
      std::ofstream mf(manifest);
      mf << js.str();
    }
    chmod(manifest.c_str(), 0600);
    // Before the launch: the render Flame triggers right after this press must see GENERATING.
    setIfChanged(resultKey_, rkey);  // processed record (LTX 71)
    markPending(root, rkey, getpid());
    const std::string level = logLevel() == LogLevel::Debug ? "debug" : "info";
    // The key travels in the environment, never on argv or in a file (LTX decision 13).
    const bool ok = launchDetached({rt.python, "-I", "-B", resourcesDir() + "/worker/job.py", manifest},
                                   cleanEnvironment({"CPO_LOG_LEVEL=" + level, "COMFY_API_KEY=" + key}), err);
    if (!ok) {
      clearPending(root, rkey);
      unlink(input.c_str());
      unlink(manifest.c_str());
      return error("Could not start Generate: " + err);
    }
    {
      std::lock_guard<std::mutex> lock(jobMutex_);
      lastJobId_ = jobId;
    }
    LOGI("generate: job launched: %dx%d first frame %g, source %s, API key (%zu characters), "
         "colour %s, params %s; %s",
         w, h, first, withSource ? "as reference" : "not used", key.size(),
         kColourSpaces[colour], paramSignature().c_str(), spec_.costHint ? spec_.costHint(values, withSource).c_str() : "");
    setIfChanged(status_, "Generating...");
    startWatcher(jobId, root, rkey);
  }

  // Follows the job's status file and mirrors it into the Status label. Param changes from this
  // thread show at the next UI interaction (LTX "Flame host behaviour"); the viewer is refreshed
  // by the Flame hook (decision 7).
  void startWatcher(const std::string& jobId, const std::string& root, const std::string& key) {
    stopWatcher();
    stopFlag_ = false;
    const std::string node = nodeId_;
    watcher_ = std::thread([this, jobId, root, key, node] {
      LogScope scope(node, jobId);
      const auto t0 = std::chrono::steady_clock::now();
      while (!stopFlag_) {
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
        const std::string j = readFile(root + "/jobs/" + jobId + ".json");
        if (j.empty()) {
          if (std::chrono::steady_clock::now() - t0 > std::chrono::seconds(60)) {
            clearPending(root, key);  // job.py never ran: don't show GENERATING forever
            LOGW("watcher: job wrote no status within 60 s; cleared its pending marker");
            return;
          }
          continue;
        }
        const std::string state = jsonField(j, "state");
        if (state == "running") continue;
        const std::string text = state == "done"        ? "Done " + timeStr("%H:%M")
                                 : state == "cancelled" ? std::string("Cancelled")
                                                        : "Failed: " + jsonField(j, "message").substr(0, 20);
        LOGI("watcher: job %s -> status '%s'", state.c_str(), text.c_str());
        setIfChanged(status_, text);
        return;
      }
    });
  }

  void stopWatcher() {
    stopFlag_ = true;
    if (watcher_.joinable()) watcher_.join();
  }

  void purgeNode() {
    std::string stored;
    resultKey_->getValue(stored);
    const bool removed = !stored.empty() && purgeKey(cacheRoot(), stored);
    LOGI("purgeNode: key %s %s", stored.c_str(), removed ? "removed" : "not cached");
    setIfChanged(resultKey_, "");  // back to never generated: pass-through (LTX 71)
    setIfChanged(status_, removed ? "Cache purged" : "Nothing cached");
    refreshCacheInfo();
  }

  void saveApiKey() {
    std::string k;
    apiKey_->getValue(k);
    UserConfig cfg = loadUserConfig();
    if (k.empty())
      cfg.erase("api_key");
    else
      cfg["api_key"] = k;
    const bool ok = saveUserConfig(cfg), had = !k.empty();
    LOGI("saveApiKey: %s (%zu characters)", ok ? (had ? "saved" : "removed") : "FAILED", k.size());
    k.assign(k.size(), '\0');
    apiKey_->setValue("");  // never left in the UI (LTX decision 13)
    setIfChanged(keyCaption_, ok ? std::string(had ? "Key saved " : "Key removed ") + timeStr("%H:%M")
                                 : std::string(kKeyCaptionDefault));
    if (!ok) error("Could not write " + userConfigPath());
  }

  void installRuntime() {
    std::string dir;
    runtimeDir_->getValue(dir);
    dir = trimSlashes(dir.empty() ? defaultRuntimeDir() : dir);
    const std::string helper = resourcesDir() + "/helper/setup_helper.py";
    const std::string level = logLevel() == LogLevel::Debug ? "debug" : "info";
    std::string err;
    const bool ok = launchDetached({"/usr/bin/python3", "-I", "-B", helper, "--runtime-dir", dir},
                                   cleanEnvironment({"CPO_LOG_LEVEL=" + level}), err);
    LOGI("installRuntime: helper %s into %s %s", ok ? "launched" : "FAILED", dir.c_str(), err.c_str());
    if (!ok) return error("Setup failed to start: " + err);
    startSetupWatcher();
  }

  // Setup runs as its own process; this thread notices when it is done (LTX setup watcher).
  void startSetupWatcher() {
    stopSetupWatcher();
    setupStop_ = false;
    const std::string node = nodeId_;
    setupWatcher_ = std::thread([this, node] {
      LogScope scope(node);
      const auto t0 = std::chrono::steady_clock::now();
      while (!setupStop_ && std::chrono::steady_clock::now() - t0 < std::chrono::hours(1)) {
        std::this_thread::sleep_for(std::chrono::seconds(2));
        if (!runtimeState().ready) continue;
        try {
          refreshSetupUi();
          LOGI("setup watcher: runtime ready; Setup UI refreshed from a non-action thread");
        } catch (const std::exception& e) {
          LOGE("setup watcher: refresh FAILED: %s", e.what());
        }
        return;
      }
    });
  }

  void stopSetupWatcher() {
    setupStop_ = true;
    if (setupWatcher_.joinable()) setupWatcher_.join();
  }

  void collectLogs() {
    const std::string dir = logDir();
    {
      std::ofstream envf(dir + "/environment.txt");
      for (const auto& line : environmentSnapshot(resourcesDir())) envf << line << "\n";
    }
    const std::string bundle = homeDir() + "/partner-models-support-" + timeStr("%Y%m%d-%H%M%S") + ".tar.gz";
    std::vector<std::string> argv = {"/usr/bin/tar", "-czf", bundle, "-C", dir.substr(0, dir.rfind('/')), "logs"};
    const std::string root = cacheRoot();
    struct stat st {};
    if (stat((root + "/jobs").c_str(), &st) == 0) argv.insert(argv.end(), {"-C", root, "jobs"});
    std::string err;
    WorkerProcess tar;
    std::vector<std::string> lines;
    const bool started = tar.start(argv, cleanEnvironment(), err);
    if (started)
      while (tar.readLines(200, lines)) {
      }
    const int status = started ? tar.wait() : -1;
    const bool ok = started && WIFEXITED(status) && WEXITSTATUS(status) == 0;
    for (const auto& l : lines) LOGW("collectLogs: tar: %s", l.c_str());
    LOGI("collectLogs: %s -> %s %s", ok ? "ok" : "FAILED", bundle.c_str(), err.c_str());
    sendMessage(ok ? OFX::Message::eMessageMessage : OFX::Message::eMessageError, "",
                ok ? "Support bundle written to " + bundle +
                         ". Please review it before sending: it contains your logs, system details and "
                         "folder paths and prompts, but no images and no API key."
                   : "Could not write the support bundle: " + err);
  }

  const ModelSpec& spec_;
  OFX::Clip* src_;
  OFX::Clip* dst_;
  OFX::ChoiceParam* colour_;
  OFX::StringParam* status_;
  OFX::BooleanParam* useSource_;
  OFX::StringParam* cacheDir_;
  OFX::StringParam* cacheInfo_;
  OFX::StringParam* cost_;
  OFX::StringParam* keyCaption_;
  OFX::StringParam* apiKey_;
  OFX::StringParam* keyStatus_;
  OFX::StringParam* runtimeDir_;
  OFX::StringParam* setupStatus_;
  OFX::BooleanParam* debugLog_;
  OFX::StringParam* nodeIdParam_;
  OFX::StringParam* resultKey_;
  std::string nodeId_;
  std::mutex jobMutex_;
  std::string lastJobId_;
  bool inChangedParam_ = false;
  bool runtimeWasMissing_ = false;
  std::thread watcher_;
  std::atomic<bool> stopFlag_{false};
  std::thread setupWatcher_;
  std::atomic<bool> setupStop_{false};
};

template <class D>
D* labelled(D* p, const std::string& label, const std::string& hint) {
  p->setLabels(label, label, label);
  if (!hint.empty()) p->setHint(hint);
  return p;
}

}  // namespace

void describeEffect(OFX::ImageEffectDescriptor& desc, const ModelSpec& spec) {
  static bool loaded = false;  // once per Flame start, for all models in the bundle
  if (!loaded) {
    loaded = true;
    logConfigure();
    rotateLogs();
    LOGI("==== plugin load (describe) ====");
    for (const auto& line : environmentSnapshot(resourcesDir())) LOGI("env %s", line.c_str());
    const size_t staged = sweepStaleStaging();
    const SweepResult sw = sweepCache(cacheSettings(loadUserConfig()));
    LOGI("sweep: %zu stale staging file(s); cache aged %zu, capped %zu, kept %zu (%.1f MB), freed %.1f MB", staged,
         sw.aged, sw.capped, sw.kept, sw.bytesKept / 1048576.0, sw.bytesFreed / 1048576.0);
  }
  LOGI("describe %s (%s)", spec.label.c_str(), spec.pluginId.c_str());
  desc.setLabels(spec.label, spec.label, spec.label);
  desc.setPluginGrouping("Partner Models");
  desc.addSupportedContext(OFX::eContextFilter);  // LTX 63: Filter only, one source
  desc.addSupportedBitDepth(OFX::eBitDepthFloat);
  desc.setSingleInstance(false);
  desc.setHostFrameThreading(false);
  desc.setSupportsMultiResolution(false);
  desc.setSupportsTiles(false);
  desc.setTemporalClipAccess(true);  // the first frame, from any frame
  desc.setRenderTwiceAlways(false);
  desc.setSupportsMultipleClipPARs(false);
  desc.setRenderThreadSafety(OFX::eRenderInstanceSafe);
}

void describeEffectInContext(OFX::ImageEffectDescriptor& desc, OFX::ContextEnum ctx, const ModelSpec& spec) {
  try {
    OFX::ClipDescriptor* src = desc.defineClip(kOfxImageEffectSimpleSourceClipName);
    src->addSupportedComponent(OFX::ePixelComponentRGBA);
    src->addSupportedComponent(OFX::ePixelComponentRGB);
    src->setTemporalClipAccess(true);
    src->setSupportsTiles(false);
    OFX::ClipDescriptor* dst = desc.defineClip(kOfxImageEffectOutputClipName);
    dst->addSupportedComponent(OFX::ePixelComponentRGBA);
    dst->setSupportsTiles(false);

    // Flame (LTX decisions 37/52): params flow into columns of <= 5 rows, 6 columns per tab, each
    // group starts a column, pages are ignored and a new tab appears only on overflow, named after
    // the next OFX page. So tab 1 is filled to exactly 6 columns and Setup overflows to tab 2.
    OFX::PageParamDescriptor* main = desc.definePageParam(spec.label);
    OFX::PageParamDescriptor* setupPage = desc.definePageParam("Setup");
    int columns = 0;
    auto group = [&](const std::string& name, const std::string& text, OFX::PageParamDescriptor* page) {
      auto* g = desc.defineGroupParam(name);
      g->setLabels(text, text, text);
      g->setOpen(true);
      page->addChild(*g);
      if (page == main) ++columns;
      return g;
    };
    auto place = [](OFX::ParamDescriptor& p, OFX::GroupParamDescriptor* g) { p.setParent(*g); };
    auto label = [&](const std::string& name, const std::string& text, const std::string& def) {
      auto* p = labelled(desc.defineStringParam(name), text, "");
      p->setStringType(OFX::eStringTypeLabel);
      p->setDefault(def);
      p->setIsPersistant(false);
      p->setEvaluateOnChange(false);
      return p;
    };
    auto button = [&](const std::string& name, const std::string& text, const std::string& hint) {
      return labelled(desc.definePushButtonParam(name), text, hint);
    };
    auto perUser = [](OFX::ValueParamDescriptor* p) {
      p->setIsPersistant(false);
      p->setEvaluateOnChange(false);
      p->setAnimates(false);
    };

    // --- Main (5 rows) ---
    auto* gMain = group("grpMain", spec.label, main);
    auto* colour = labelled(desc.defineChoiceParam(kPColour), "Input Colour",
                            "Colour space of the source. It goes to the model through the ACES 2.0 SDR "
                            "100 nits (Rec.709) view and the result comes back through the inverse. "
                            "Bypass: the source is already display-referred. LogC3 is ARRI LogC3 EI800.");
    for (const char* c : kColourSpaces) colour->appendOption(c);
    colour->setDefault(0);
    colour->setEvaluateOnChange(false);
    place(*colour, gMain);
    place(*button(kPGenerate, "Generate",
                  "Send the source's first frame and the prompt to " + spec.label +
                      " (costs credits). The result is held on every frame. Progress and Cancel appear "
                      "in a separate window."),
          gMain);
    place(*label(kPStatus, "Status", "Not generated"), gMain);
    if (spec.maxReferences > 0) {
      auto* use = labelled(desc.defineBooleanParam(kPUseSource), "Use Source",
                           "Send the source's first frame as the reference image (@Image1). Off: "
                           "generate from the prompt alone.");
      use->setDefault(true);
      use->setEvaluateOnChange(false);
      place(*use, gMain);
    }

    // --- Model columns ---
    std::vector<OFX::GroupParamDescriptor*> modelGroups;
    for (size_t c = 0; c < spec.columns.size(); ++c)
      modelGroups.push_back(group("grpModel" + std::to_string(c), spec.columns[c], main));
    for (const auto& p : spec.params) {
      OFX::GroupParamDescriptor* g = modelGroups.at(size_t(p.column));
      OFX::ValueParamDescriptor* d = nullptr;
      if (p.kind == ParamKind::Choice) {
        auto* c = labelled(desc.defineChoiceParam(p.name), p.label, p.hint);
        for (const auto& o : p.options) c->appendOption(o);
        c->setDefault(p.def);
        d = c;
      } else if (p.kind == ParamKind::Int) {
        auto* i = labelled(desc.defineIntParam(p.name), p.label, p.hint);
        i->setRange(p.min, p.max);
        i->setDisplayRange(p.min, std::min(p.max, 1000000));
        i->setDefault(p.def);
        d = i;
      } else if (p.kind == ParamKind::Bool) {
        auto* b = labelled(desc.defineBooleanParam(p.name), p.label, p.hint);
        b->setDefault(p.def != 0);
        d = b;
      } else {
        // LTX decision 41: Flame shows a plain string in one row with no label, so a button above it
        // names it and opens a larger editor (editText).
        place(*button(p.name + "Edit", "Edit " + p.label + "...",
                      "Open a larger, resizable editor for the " + p.label + ". OK writes it back; Flame waits "
                      "while the editor is open."),
              g);
        auto* s = labelled(desc.defineStringParam(p.name), p.label, p.hint);
        s->setDefault(p.defText);
        d = s;
      }
      d->setEvaluateOnChange(false);  // results change only through Generate
      d->setAnimates(false);
      place(*d, g);
    }

    // --- Cache (5 rows, per user except Purge Cache) ---
    auto* gCache = group("grpCache", "Cache", main);
    auto* cdir = labelled(desc.defineStringParam(kPCacheDir), "Cache Folder",
                          "Where generated images are kept (about 12 MB per HD result).");
    cdir->setStringType(OFX::eStringTypeDirectoryPath);
    cdir->setDefault(defaultCacheRoot());
    perUser(cdir);
    place(*cdir, gCache);
    place(*label(kPCacheInfo, "Cache Size", ""), gCache);
    place(*button(kPPurgeNode, "Purge Cache", "Delete this node's cached result."), gCache);
    place(*button(kPPurgeAll, "Purge All", "Delete every cached result of every node and project."), gCache);

    // --- Cost (1 row) and spacers up to 6 columns; the last one holds the version, so a test in
    // Flame shows which build is loaded (LTX decision 52). ---
    place(*label(kPCost, "Cost", ""), group("grpCost", "Cost", main));
    for (int spacer = 0; columns < 5; ++spacer) {
      const std::string n = std::to_string(spacer);
      place(*label("spacer" + n, " ", " "), group("grpSpacer" + n, " ", main));
    }
    place(*label("version", "Version", std::string(CPO_VERSION) + " (" + CPO_GIT + ")"), group("grpVersion", " ", main));

    // --- Setup tab: API key (4 rows, per user) ---
    auto* gKey = group("grpKey", "API Key", setupPage);
    place(*label(kPKeyCaption, "API Key", kKeyCaptionDefault), gKey);
    auto* key = labelled(desc.defineStringParam(kPApiKey), "API Key",
                         "Your Comfy API key (comfyui-...), from platform.comfy.org. Save Key stores it in "
                         "your user config (mode 600), never in setups.");
    key->setDefault("");
    perUser(key);
    place(*key, gKey);
    place(*button(kPSaveKey, "Save Key", "Store the key above for all your nodes (empty: remove it)."), gKey);
    place(*label(kPKeyStatus, "Key", ""), gKey);
    // --- Runtime (4 rows, per user) ---
    auto* gRt = group("grpRuntime", "Runtime", setupPage);
    auto* rdir = labelled(desc.defineStringParam(kPRuntimeDir), "Runtime Folder",
                          "Where Install puts the Python runtime (numpy, OpenColorIO, Pillow; about 250 MB).");
    rdir->setStringType(OFX::eStringTypeDirectoryPath);
    rdir->setDefault(defaultRuntimeDir());
    perUser(rdir);
    place(*rdir, gRt);
    place(*button(kPInstall, "Install", "Install or repair the Python runtime in the Runtime Folder."), gRt);
    place(*label(kPSetupStatus, "Setup", ""), gRt);
    // --- Support (2 rows, per user) ---
    auto* gSupport = group("grpSupport", "Support", setupPage);
    auto* dbg = labelled(desc.defineBooleanParam(kPDebugLog), "Debug Logging", "Verbose logging for troubleshooting (per user).");
    dbg->setDefault(false);
    perUser(dbg);
    place(*dbg, gSupport);
    place(*button(kPCollectLogs, "Collect Logs", "Write a support bundle (logs and system details) to your home folder."),
          gSupport);

    // --- Hidden ---
    for (const char* n : {kPNodeId, kPResultKey}) {
      auto* p = desc.defineStringParam(n);
      p->setDefault("");
      p->setIsSecret(true);
      p->setEvaluateOnChange(false);
    }
    LOGI("describeInContext %s ctx=%d done (%d columns on tab 1)", spec.label.c_str(), int(ctx), columns);
  } catch (const std::exception& e) {
    LOGE("describeInContext %s ctx=%d FAILED: %s [%s]", spec.label.c_str(), int(ctx), e.what(), typeid(e).name());
    throw;
  }
}

OFX::ImageEffect* createEffect(OfxImageEffectHandle handle, const ModelSpec& spec) {
  return new PartnerEffect(handle, spec);
}

}  // namespace cpo
