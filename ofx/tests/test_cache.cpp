// Cache layout and reads (cache.h), including a file written the way worker/cpo/cache.py writes it.
#include <sys/stat.h>
#include <unistd.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "cache.h"

static int failures = 0;
#define CHECK(c)                                                       \
  do {                                                                 \
    if (!(c)) {                                                        \
      std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); \
      ++failures;                                                      \
    }                                                                  \
  } while (0)

static void writeResult(const std::string& root, const std::string& key, uint32_t w, uint32_t h,
                        const char* magic, uint32_t channels) {
  const std::string path = cpo::resultPath(root, key);
  mkdir(path.substr(0, path.rfind('/')).c_str(), 0755);
  FILE* f = std::fopen(path.c_str(), "wb");
  cpo::FrameFileHeader hdr{};
  std::memcpy(hdr.magic, magic, 4);
  hdr.version = cpo::kFileVersion;
  hdr.width = w;
  hdr.height = h;
  hdr.frames = 1;
  hdr.channels = channels;
  std::fwrite(&hdr, sizeof hdr, 1, f);
  std::vector<uint16_t> px(size_t(w) * h * channels);
  for (size_t i = 0; i < px.size(); ++i) px[i] = uint16_t(0x3c00);  // 1.0 in fp16
  std::fwrite(px.data(), 2, px.size(), f);
  std::fclose(f);
}

int main() {
  char tmpl[] = "/tmp/cpo_test_cache_XXXXXX";
  const std::string root = mkdtemp(tmpl);

  // Keys: stable, 16 hex digits, sensitive to the hash and to every signature byte.
  const std::string k1 = cpo::resultKey(42, "v1|model=a|prompt=x");
  CHECK(k1.size() == 16);
  CHECK(k1 == cpo::resultKey(42, "v1|model=a|prompt=x"));
  CHECK(k1 != cpo::resultKey(43, "v1|model=a|prompt=x"));
  CHECK(k1 != cpo::resultKey(42, "v1|model=a|prompt=y"));
  CHECK(cpo::resultPath(root, k1) == root + "/" + k1.substr(0, 2) + "/" + k1 + ".img");

  std::vector<uint16_t> out;
  CHECK(!cpo::readResult(root, k1, 4, 3, out));  // missing
  writeResult(root, k1, 4, 3, "CPOI", 3);
  CHECK(cpo::readResult(root, k1, 4, 3, out));
  CHECK(out.size() == 36 && out[0] == 0x3c00 && out[35] == 0x3c00);
  CHECK(!cpo::readResult(root, k1, 5, 3, out));  // wrong size
  const std::string k2 = cpo::resultKey(1, "x");
  writeResult(root, k2, 4, 3, "CPOA", 3);          // wrong magic
  CHECK(!cpo::readResult(root, k2, 4, 3, out));
  CHECK(cpo::cacheBytes(root) == 2 * (24 + 36 * 2));

  // Pending markers follow the owner's pid.
  CHECK(!cpo::isPending(root, k1));
  cpo::markPending(root, k1, getpid());
  CHECK(cpo::isPending(root, k1));
  cpo::markPending(root, k2, 999999999);  // no such process
  CHECK(!cpo::isPending(root, k2));
  cpo::clearPending(root, k1);
  CHECK(!cpo::isPending(root, k1));

  // Sweep with a 0-day age limit keeps fresh files, then purge.
  cpo::CacheSettings s;
  s.root = root;
  s.maxAgeDays = 30;
  s.capGB = 20.0;
  const cpo::SweepResult sw = cpo::sweepCache(s);
  CHECK(sw.kept == 2 && sw.aged == 0 && sw.capped == 0);
  CHECK(access(cpo::pendingPath(root, k2).c_str(), F_OK) != 0);  // dead job's marker swept
  CHECK(cpo::purgeKey(root, k1));
  CHECK(!cpo::purgeKey(root, k1));
  CHECK(cpo::purgeAll(root) == 24 + 36 * 2);
  CHECK(cpo::cacheBytes(root) == 0);

  // Config: cache_dir wins, empty falls back to the default.
  cpo::UserConfig cfg;
  CHECK(cpo::cacheSettings(cfg).root == cpo::defaultCacheRoot());
  cfg["cache_dir"] = "/x/y";
  cfg["cache_cap_gb"] = "5";
  CHECK(cpo::cacheSettings(cfg).root == "/x/y" && cpo::cacheSettings(cfg).capGB == 5.0);
  cfg["cache_dir"] = "";
  CHECK(cpo::cacheSettings(cfg).root == cpo::defaultCacheRoot());

  std::string cmd = "rm -rf " + root;
  (void)!std::system(cmd.c_str());
  std::printf("test_cache: %s\n", failures ? "FAILED" : "OK");
  return failures ? 1 : 0;
}
