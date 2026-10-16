#!/usr/bin/env bash
# Build the Linux release tarball on a Rocky 9 machine (the .ofx must link against glibc <= 2.34
# and Flame's GCC 11 libstdc++) and copy it back to dist/ (as LTX Alpha Gen's).
#   HOST=<ssh host> REMOTE=<folder> [TEST_PYTHON=<runtime python>] scripts/package_release.sh
#   -> dist/PartnerModels-<version>-rocky9.tar.gz
# Contents: PartnerModels.ofx.bundle (release build), install.sh, README.md, LICENSE, NOTICE.
# Release gate: a clean, committed tree and ctest passing on the build machine (no system test yet).
# Builds in $REMOTE/release (separate from the dev build); never installs anything.
set -euo pipefail
HOST=${HOST:?set HOST to the ssh name of the Rocky 9 build machine}
REMOTE=${REMOTE:?set REMOTE to the build folder on HOST}
TEST_PYTHON=${TEST_PYTHON:-/usr/bin/python3}
SRC="$(cd "$(dirname "$0")/.." && pwd)"
VERSION=$(sed -n 's/^set(CPO_VERSION "\([0-9.]*\)")/\1/p' "$SRC/CMakeLists.txt")
[ -n "$VERSION" ] || { echo "no CPO_VERSION in CMakeLists.txt" >&2; exit 1; }
NAME="PartnerModels-$VERSION"
[ -z "$(git -C "$SRC" status --porcelain)" ] || { echo "uncommitted changes: commit first" >&2; exit 1; }
GIT=$(git -C "$SRC" rev-parse --short HEAD)

ssh "$HOST" "mkdir -p $REMOTE/release-src"
rsync -a --delete --exclude .git --exclude build --exclude dist --exclude __pycache__ --exclude CLAUDE.local.md \
  "$SRC/" "$HOST:$REMOTE/release-src/"
ssh "$HOST" "set -e; cd $REMOTE
  cmake -S release-src -B release -DCMAKE_BUILD_TYPE=Release -DCPO_GIT=$GIT -DWORKER_TEST_PYTHON=$TEST_PYTHON >/dev/null
  cmake --build release -j 8 2>&1 | grep -E 'error|warning' || true
  (cd release && ctest --output-on-failure >/dev/null) || { echo 'ctest failed' >&2; exit 1; }
  echo ctest passed
  rm -rf dist/$NAME && mkdir -p dist/$NAME
  cp -R release/PartnerModels.ofx.bundle dist/$NAME/
  sed 's/^VERSION=dev /VERSION=$VERSION /' release-src/packaging/install.sh > dist/$NAME/install.sh
  chmod 0755 dist/$NAME/install.sh
  cp release-src/README.md release-src/LICENSE release-src/NOTICE dist/$NAME/
  find dist/$NAME -name __pycache__ -prune -exec rm -rf {} +
  tar -C dist -czf dist/$NAME-rocky9.tar.gz $NAME
  echo glibc needed: \$(objdump -T dist/$NAME/PartnerModels.ofx.bundle/Contents/Linux-x86-64/PartnerModels.ofx | grep -o 'GLIBC_[0-9.]*' | sort -V | tail -1)"
mkdir -p "$SRC/dist"
scp -q "$HOST:$REMOTE/dist/$NAME-rocky9.tar.gz" "$SRC/dist/"
ls -la "$SRC/dist/$NAME-rocky9.tar.gz"
