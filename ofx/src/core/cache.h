// Content-addressed result cache on disk (LTX decision 36). One generated image per key.
// Layout under the cache root (must match worker/cpo/cache.py):
//   <root>/<k[0:2]>/<key>.img    "CPOI" header (FrameFileHeader, n=1, c=3), then h*w*3 fp16,
//                                rows top-down, already in the source colour space and size
//   <root>/pending/<key>         exists while a job is generating that key; holds the job pid
//   <root>/jobs/<job id>.json    final job status (done / failed / cancelled + message)
#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "user_config.h"

namespace cpo {

#pragma pack(push, 1)
struct FrameFileHeader {
  char magic[4];  // "CPOA" staged input frame, "CPOI" result image
  uint32_t version;
  uint32_t width;
  uint32_t height;
  uint32_t frames;
  uint32_t channels;
};
#pragma pack(pop)
static_assert(sizeof(FrameFileHeader) == 24, "header must be 24 bytes");
constexpr uint32_t kFileVersion = 1;

struct CacheSettings {
  std::string root;
  int maxAgeDays = 30;
  double capGB = 20.0;
};

CacheSettings cacheSettings(const UserConfig& cfg);
std::string defaultCacheRoot();

// Everything that changes the result besides the reference pixels.
std::string resultKey(uint64_t sourceFrameHash, const std::string& paramSignature);

std::string resultPath(const std::string& root, const std::string& key);
std::string pendingPath(const std::string& root, const std::string& key);

// Reads one result (w*h*3 halves, rows top-down) and refreshes its mtime for the LRU sweep.
bool readResult(const std::string& root, const std::string& key, uint32_t w, uint32_t h,
                std::vector<uint16_t>& out);

// True while a live job holds the key's pending marker.
bool isPending(const std::string& root, const std::string& key);

// Written by the plugin just before it launches a job (with Flame's pid), so the render Flame
// triggers right after the button press already shows GENERATING (LTX test 2 race); job.py
// rewrites it with its own pid and removes it at the end. clearPending undoes a failed launch.
void markPending(const std::string& root, const std::string& key, int pid);
void clearPending(const std::string& root, const std::string& key);

bool purgeKey(const std::string& root, const std::string& key);
uint64_t cacheBytes(const std::string& root);
uint64_t purgeAll(const std::string& root);  // returns bytes freed

struct SweepResult {
  size_t aged = 0, capped = 0, kept = 0;
  uint64_t bytesFreed = 0, bytesKept = 0;
};
// Deletes results unused for maxAgeDays, then least-recently-used until under capGB.
// Also clears pending markers of dead jobs.
SweepResult sweepCache(const CacheSettings& s);

// Removes stagingDir()/cpo_job_* files whose job is gone.
size_t sweepStaleStaging();

bool pidAlive(int pid);

}  // namespace cpo
