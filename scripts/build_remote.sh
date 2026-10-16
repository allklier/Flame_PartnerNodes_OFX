#!/usr/bin/env bash
# Sync the source to a Rocky 9 build machine, build and test there (as LTX's build_remote.sh).
#   HOST=<ssh host> [REMOTE=<folder>] [TEST_PYTHON=<runtime python>] scripts/build_remote.sh
# Never touches /usr/OFX/Plugins. The one-time install symlink is done by hand with sudo:
#   sudo ln -s <REMOTE>/build/PartnerModels.ofx.bundle /usr/OFX/Plugins/
set -euo pipefail
HOST=${HOST:?set HOST to the ssh name of the Rocky 9 build machine}
REMOTE=${REMOTE:?set REMOTE to the build folder on HOST}
TEST_PYTHON=${TEST_PYTHON:-/usr/bin/python3}
SRC="$(cd "$(dirname "$0")/.." && pwd)"

ssh "$HOST" "mkdir -p $REMOTE/src"
rsync -a --delete --exclude .git --exclude build --exclude __pycache__ --exclude 'CLAUDE.local.md' \
  "$SRC/" "$HOST:$REMOTE/src/"
GIT=$(git -C "$SRC" rev-parse --short HEAD 2>/dev/null || echo nogit)
[ -n "$(git -C "$SRC" status --porcelain 2>/dev/null)" ] && GIT="$GIT-dirty"
ssh "$HOST" "set -e; cd $REMOTE && cmake -S src -B build -DCMAKE_BUILD_TYPE=Release -DCPO_GIT=$GIT \
  -DWORKER_TEST_PYTHON=$TEST_PYTHON >/dev/null && cmake --build build -j 8 2>&1 | grep -E 'error|warning' || true; \
  cd build && ctest --output-on-failure"
