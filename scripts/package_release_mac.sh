#!/usr/bin/env bash
# Build the macOS release tarball on an Apple Silicon Mac (Command Line Tools) and copy it back
# to dist/ (as LTX Alpha Gen's).
#   HOST=<ssh host> REMOTE=<folder on the Mac> [CMAKE=<cmake on the Mac>] [CMAKE_ARGS=...] \
#     scripts/package_release_mac.sh  ->  dist/PartnerModels-<version>-macos-arm64.tar.gz
# Contents: PartnerModels.ofx.bundle (release build), install.sh, README.md, LICENSE, NOTICE.
# CMAKE_ARGS as for build_mac.sh. Release gate: a clean, committed tree and ctest passing on the Mac.
# Builds in $REMOTE/release; never installs anything. Signed ad hoc only (no notarisation).
set -euo pipefail
HOST=${HOST:?set HOST to the ssh name of the Mac}
REMOTE=${REMOTE:?set REMOTE to the build folder on the Mac}
CMAKE=${CMAKE:-cmake}
if [[ $CMAKE == */* ]]; then CTEST=${CTEST:-${CMAKE%/*}/ctest}; else CTEST=${CTEST:-ctest}; fi
CMAKE_ARGS=${CMAKE_ARGS:-}
SRC="$(cd "$(dirname "$0")/.." && pwd)"
VERSION=$(sed -n 's/^set(CPO_VERSION "\([0-9.]*\)")/\1/p' "$SRC/CMakeLists.txt")
[ -n "$VERSION" ] || { echo "no CPO_VERSION in CMakeLists.txt" >&2; exit 1; }
NAME="PartnerModels-$VERSION"
[ -z "$(git -C "$SRC" status --porcelain)" ] || { echo "uncommitted changes: commit first" >&2; exit 1; }
GIT=$(git -C "$SRC" rev-parse --short HEAD)

ssh "$HOST" "mkdir -p '$REMOTE/release-src'"
rsync -a --delete --exclude .git --exclude build --exclude dist --exclude __pycache__ --exclude CLAUDE.local.md \
  "$SRC/" "$HOST:$REMOTE/release-src/"
ssh "$HOST" "set -e; cd '$REMOTE'
  '$CMAKE' -S release-src -B release -DCMAKE_BUILD_TYPE=Release -DCPO_GIT=$GIT $CMAKE_ARGS >/dev/null
  '$CMAKE' --build release -j 8 2>&1 | grep -E 'error|warning' || true
  (cd release && '$CTEST' --output-on-failure >/dev/null) || { echo 'ctest failed' >&2; exit 1; }
  echo ctest passed
  rm -rf dist/$NAME && mkdir -p dist/$NAME
  cp -R release/PartnerModels.ofx.bundle dist/$NAME/
  sed 's/^VERSION=dev /VERSION=$VERSION /' release-src/packaging/install.sh > dist/$NAME/install.sh
  chmod 0755 dist/$NAME/install.sh
  cp release-src/README.md release-src/LICENSE release-src/NOTICE dist/$NAME/
  find dist/$NAME -name __pycache__ -prune -exec rm -rf {} +
  COPYFILE_DISABLE=1 tar -C dist -czf dist/$NAME-macos-arm64.tar.gz $NAME
  echo binary: \$(file dist/$NAME/PartnerModels.ofx.bundle/Contents/MacOS/PartnerModels.ofx | cut -d: -f2)"
mkdir -p "$SRC/dist"
scp -q "$HOST:$REMOTE/dist/$NAME-macos-arm64.tar.gz" "$SRC/dist/"
ls -la "$SRC/dist/$NAME-macos-arm64.tar.gz"
