// Everything that differs between operating systems (LTX decision 64). The rest of the plugin is
// portable POSIX/OFX code and calls only these. Linux: platform_linux.cpp; macOS:
// platform_macos.cpp (from LTX's, without the GPU parts); selected in CMakeLists.txt.
#pragma once

#include <string>
#include <vector>

namespace cpo {

// Folder for the frame files handed to the job (RAM-backed on Linux: /dev/shm). No trailing '/'.
// worker/job.py takes it from its manifest's folder.
std::string stagingDir();

// Reserves `total` bytes of an open file so lack of space fails here, not mid-write. 0 or an errno.
// Linux: posix_fallocate. macOS has none: F_PREALLOCATE + ftruncate (LTX transport.cpp).
int reserveFile(int fd, long long total);

// Short process name ("flame"), empty if the process is gone.
std::string processName(unsigned pid);

// OS-specific lines of the environment snapshot (os, cpu, ram, staging space).
std::vector<std::string> platformSnapshot();

}  // namespace cpo
