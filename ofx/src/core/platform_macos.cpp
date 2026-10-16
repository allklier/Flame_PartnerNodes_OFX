// macOS side of platform.h (LTX decision 64), from LTX Alpha Gen's platform_macos.cpp without the
// GPU and licence-window parts. Verified there against the Command Line Tools MacOSX.sdk: confstr
// (_CS_DARWIN_USER_TEMP_DIR) in unistd.h, proc_name in libproc.h, host_statistics64 in
// mach/mach_host.h; F_PREALLOCATE/fstore_t in sys/fcntl.h (LTX transport.cpp reserve()).
#include <fcntl.h>
#include <libproc.h>
#include <mach/mach.h>
#include <sys/statvfs.h>
#include <sys/sysctl.h>
#include <sys/utsname.h>
#include <unistd.h>

#include <cerrno>
#include <cstdint>
#include <cstdio>

#include "platform.h"

namespace cpo {

namespace {
std::string gb(double bytes) {
  char b[32];
  std::snprintf(b, sizeof b, "%.1f GB", bytes / 1073741824.0);
  return b;
}

std::string sysctlString(const char* name) {
  char buf[256] = {0};
  size_t len = sizeof buf - 1;
  return sysctlbyname(name, buf, &len, nullptr, 0) == 0 ? buf : "unknown";
}

double availableRamBytes() {  // free + inactive pages
  vm_statistics64_data_t vm{};
  mach_msg_type_number_t count = HOST_VM_INFO64_COUNT;
  if (host_statistics64(mach_host_self(), HOST_VM_INFO64, reinterpret_cast<host_info64_t>(&vm), &count) !=
      KERN_SUCCESS)
    return 0.0;
  return (double(vm.free_count) + double(vm.inactive_count)) * double(vm_kernel_page_size);
}
}  // namespace

// Per-user temp folder (/var/folders/.../T). On disk, not RAM-backed like /dev/shm.
std::string stagingDir() {
  char buf[1024] = {0};
  const size_t n = confstr(_CS_DARWIN_USER_TEMP_DIR, buf, sizeof buf);
  std::string dir = (n > 0 && n <= sizeof buf) ? buf : "/tmp";
  while (dir.size() > 1 && dir.back() == '/') dir.pop_back();
  return dir;
}

// macOS has no posix_fallocate: F_PREALLOCATE with F_ALLOCATEALL (all or nothing) from the end of
// file, then ftruncate to the size posix_fallocate would leave.
int reserveFile(int fd, long long total) {
  fstore_t fs{F_ALLOCATEALL, F_PEOFPOSMODE, 0, off_t(total), 0};
  if (fcntl(fd, F_PREALLOCATE, &fs) != 0 || ftruncate(fd, off_t(total)) != 0) return errno;
  return 0;
}

std::string processName(unsigned pid) {
  char buf[256] = {0};
  return proc_name(int(pid), buf, sizeof buf) > 0 ? buf : "";
}

std::vector<std::string> platformSnapshot() {
  std::vector<std::string> out;
  utsname u{};
  uname(&u);
  out.push_back("os: macOS " + sysctlString("kern.osproductversion") + " (" + sysctlString("kern.osversion") +
                "), Darwin " + u.release);
  int ncpu = 0;
  size_t len = sizeof ncpu;
  sysctlbyname("hw.ncpu", &ncpu, &len, nullptr, 0);
  out.push_back("cpu: " + sysctlString("machdep.cpu.brand_string") + ", " + std::to_string(ncpu) + " threads");
  uint64_t mem = 0;
  len = sizeof mem;
  sysctlbyname("hw.memsize", &mem, &len, nullptr, 0);
  out.push_back("ram: " + gb(double(mem)) + " total, " + gb(availableRamBytes()) + " available");
  struct statvfs vs {};
  if (statvfs(stagingDir().c_str(), &vs) == 0)
    out.push_back("staging: " + stagingDir() + ", " + gb(double(vs.f_blocks) * vs.f_frsize) + " total, " +
                  gb(double(vs.f_bavail) * vs.f_frsize) + " free");
  return out;
}

}  // namespace cpo
