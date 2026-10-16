#!/usr/bin/env bash
# Sync the source to a Mac (Apple Silicon, Command Line Tools), build and test there (as LTX's).
#   HOST=<ssh host> REMOTE=<folder on the Mac> [CMAKE=<cmake on the Mac>] [CMAKE_ARGS=...] scripts/build_mac.sh
# CMAKE_ARGS passes extra configure options, e.g. -DWORKER_TEST_PYTHON=<runtime python> (the
# Command Line Tools' python3 has no numpy/Pillow) and, on a CLT install with stale libc++ headers,
# '-DCMAKE_CXX_FLAGS=-stdlib++-isystem <SDK>/usr/include/c++/v1' (LTX CLAUDE.md).
# Writes only under $REMOTE (src/ and build/); never installs into /Library/OFX.
set -euo pipefail
HOST=${HOST:?set HOST to the ssh name of the Mac}
REMOTE=${REMOTE:?set REMOTE to the build folder on the Mac}
CMAKE=${CMAKE:-cmake}
if [[ $CMAKE == */* ]]; then CTEST=${CTEST:-${CMAKE%/*}/ctest}; else CTEST=${CTEST:-ctest}; fi
CMAKE_ARGS=${CMAKE_ARGS:-}
SRC="$(cd "$(dirname "$0")/.." && pwd)"

ssh "$HOST" "mkdir -p '$REMOTE/src'"
rsync -a --delete --exclude .git --exclude build --exclude __pycache__ --exclude CLAUDE.local.md \
  "$SRC/" "$HOST:$REMOTE/src/"
GIT=$(git -C "$SRC" rev-parse --short HEAD 2>/dev/null || echo nogit)
[ -n "$(git -C "$SRC" status --porcelain 2>/dev/null)" ] && GIT="$GIT-dirty"
ssh "$HOST" "set -e; cd '$REMOTE' && '$CMAKE' -S src -B build -DCMAKE_BUILD_TYPE=Release -DCPO_GIT=$GIT $CMAKE_ARGS >/dev/null \
  && '$CMAKE' --build build -j 8 2>&1 | grep -E 'error|warning' || true; \
  cd build && '$CTEST' --output-on-failure"
