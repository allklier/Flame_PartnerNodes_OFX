// Faint "no media"-style marker (LTX decision 44): diagonal stripes plus a centred caption such as
// GENERATING, drawn as grey values into a w*h buffer. Built-in 5x7 font covering only the letters
// the captions need. Pure, no OFX.
#pragma once

#include <string>
#include <vector>

namespace cpo {

constexpr float kMarkerStripe = 0.08f;  // faint, but clearly not a real matte
constexpr float kMarkerText = 0.30f;

// out: w*h floats, rows top-down, overwritten. Unsupported characters render as spaces.
void drawMarker(std::vector<float>& out, int w, int h, const std::string& caption);

}  // namespace cpo
