// Image inputs (decision 15): up to kMaxInputs optional clips, Image 1 = the OFX "Source" clip,
// Image 2..5 = "Image2".."Image5". They must be filled in order from Image 1 (user, 2026-10-16:
// Image 2 without Image 1 is an error); none at all = generate from the prompt at kDefaultW x kDefaultH.
#pragma once

#include <string>
#include <vector>

namespace cpo {

constexpr int kMaxInputs = 5;
constexpr int kDefaultW = 1920, kDefaultH = 1080;  // HD when Image 1 is not connected

inline std::string inputClipName(int slot) {  // slot 0..kMaxInputs-1
  return slot == 0 ? std::string("Source") : "Image" + std::to_string(slot + 1);
}

// Index of the first connected input that follows an unconnected one (a gap), or -1 if the
// connected inputs are 1..n without gaps.
inline int inputOrderError(const std::vector<bool>& connected) {
  bool gap = false;
  for (size_t i = 0; i < connected.size(); ++i) {
    if (!connected[i]) gap = true;
    else if (gap) return int(i);
  }
  return -1;
}

// Number of connected inputs, valid only when inputOrderError() is -1.
inline int connectedInputs(const std::vector<bool>& connected) {
  int n = 0;
  while (n < int(connected.size()) && connected[size_t(n)]) ++n;
  return n;
}

}  // namespace cpo
