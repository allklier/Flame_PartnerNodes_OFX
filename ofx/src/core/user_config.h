// Per-user config: ~/.config/partner-models-ofx/config.conf, plain "key=value" lines, mode 600
// (it holds the API key, decision 8): runtime, cache and log settings. Absent keys fall back to
// the built-in defaults. Same format as LTX's; written by the plugin and by Setup.
#pragma once

#include <map>
#include <string>

namespace cpo {

using UserConfig = std::map<std::string, std::string>;

std::string userConfigPath();
UserConfig loadUserConfig();
bool saveUserConfig(const UserConfig& cfg);  // atomic replace

}  // namespace cpo
