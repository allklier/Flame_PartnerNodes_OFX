// Diagnostic logging (decision 39). One rotating per-user log shared by every
// component (ofx, job, worker, helper):  ~/.cache/partner-models-ofx/logs/partner-models.log
// Line format (must match worker/cpo/log.py):
//   2026-10-10 16:35:53.383 INFO  ofx[166761/166761] node=ab12cd34 job=- | message
// Logging never throws and never blocks rendering; a failed write is dropped.
#pragma once

#include <string>

namespace cpo {

enum class LogLevel { Debug = 0, Info = 1, Warn = 2, Error = 3 };

std::string logDir();
std::string logPath();

// Level from $CPO_LOG_LEVEL, else the user config key log_level, else info.
void logConfigure();
void setLogLevel(LogLevel level);
LogLevel logLevel();
bool logEnabled(LogLevel level);

// Keeps at most `keep` rotated files of about `maxBytes` each. Called at plugin load.
void rotateLogs(size_t maxBytes = 10u << 20, int keep = 5);

void logAt(LogLevel level, const char* fmt, ...) __attribute__((format(printf, 2, 3)));

#define LOGD(...) ::cpo::logAt(::cpo::LogLevel::Debug, __VA_ARGS__)
#define LOGI(...) ::cpo::logAt(::cpo::LogLevel::Info, __VA_ARGS__)
#define LOGW(...) ::cpo::logAt(::cpo::LogLevel::Warn, __VA_ARGS__)
#define LOGE(...) ::cpo::logAt(::cpo::LogLevel::Error, __VA_ARGS__)

// Correlation ids for every line logged on this thread while the scope lives.
class LogScope {
 public:
  LogScope(const std::string& node, const std::string& job = "");
  ~LogScope();
  LogScope(const LogScope&) = delete;
  LogScope& operator=(const LogScope&) = delete;

 private:
  std::string prevNode_, prevJob_;
};

}  // namespace cpo
