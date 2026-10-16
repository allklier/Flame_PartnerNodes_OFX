#!/usr/bin/env bash
# Partner Models for Flame: install or uninstall the plugin (and, if needed, its Flame Python hook).
#   sudo ./install.sh              install (replaces an earlier Partner Models)
#   sudo ./install.sh --uninstall  remove it
# Installs:
#   /usr/OFX/Plugins/PartnerModels.ofx.bundle          (macOS: /Library/OFX/Plugins)
#   /opt/Autodesk/shared/python/partner_models_hook.py  (refreshes the viewer when a job ends),
#     only if LTX Alpha Gen's hook isn't installed: the plugin uses that one when it is there.
# The runtime, settings (API key) and cache are per user and are not touched (see README).
# Adapted from LTX Alpha Gen's install.sh.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PLUGINS=/usr/OFX/Plugins
[ "$(uname -s)" = Darwin ] && PLUGINS=/Library/OFX/Plugins
BUNDLE=PartnerModels.ofx.bundle
HOOK_DIR=/opt/Autodesk/shared/python
HOOK=partner_models_hook.py
LTX_HOOK=ltx_alphagen_hook.py
HOOK_SIGNATURE="Partner Models OFX: Flame Python hook"  # first line of our hook's docstring
VERSION=dev  # set by scripts/package_release*.sh

die() { echo "error: $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run with sudo (it writes to $PLUGINS)"
if pgrep -x flame >/dev/null 2>&1; then
  [ "${1:-}" = "--uninstall" ] && what="NOT UNINSTALLED" || what="NOT INSTALLED"
  echo "$what: Flame is running. Quit Flame, then run this again. Nothing was changed." >&2
  exit 1
fi

# Our hook (any version), or nothing there: safe to replace or remove.
hook_is_ours() {
  local p="$HOOK_DIR/$HOOK"
  [ ! -e "$p" ] && [ ! -L "$p" ] && return 0
  [ -L "$p" ] && [ ! -e "$p" ] && return 0  # dangling link (e.g. a removed dev build)
  grep -q "$HOOK_SIGNATURE" "$p"
}

if [ "${1:-}" = "--uninstall" ]; then
  if [ -e "$PLUGINS/$BUNDLE" ] || [ -L "$PLUGINS/$BUNDLE" ]; then
    rm -rf "${PLUGINS:?}/$BUNDLE"
    echo "removed $PLUGINS/$BUNDLE"
  fi
  if [ -e "$HOOK_DIR/$HOOK" ] || [ -L "$HOOK_DIR/$HOOK" ]; then
    if hook_is_ours; then
      rm -f "$HOOK_DIR/$HOOK" && echo "removed $HOOK_DIR/$HOOK"
    else
      echo "left $HOOK_DIR/$HOOK alone: it is not the Partner Models hook"
    fi
  fi
  echo "Done. Your settings (~/.config/partner-models-ofx), runtime and cache are kept."
  exit 0
fi

[ -d "$HERE/$BUNDLE" ] || die "$BUNDLE not found next to this script"
[ -f "$HERE/$BUNDLE/Contents/Resources/flame_hook/$HOOK" ] || die "the bundle has no flame_hook/$HOOK"

mkdir -p "$PLUGINS"
if [ -e "$PLUGINS/$BUNDLE" ] || [ -L "$PLUGINS/$BUNDLE" ]; then
  if [ -L "$PLUGINS/$BUNDLE" ]; then
    echo "replacing the link $PLUGINS/$BUNDLE -> $(readlink "$PLUGINS/$BUNDLE")"
  else
    echo "replacing $PLUGINS/$BUNDLE"
  fi
  rm -rf "${PLUGINS:?}/$BUNDLE"
fi
cp -R "$HERE/$BUNDLE" "$PLUGINS/"
chmod -R a+rX "$PLUGINS/$BUNDLE"
# macOS: a downloaded tarball marks every file as quarantined; the bundle is not notarised.
[ "$(uname -s)" = Darwin ] && xattr -dr com.apple.quarantine "$PLUGINS/$BUNDLE" 2>/dev/null || true
echo "installed $PLUGINS/$BUNDLE"

if [ ! -d "$HOOK_DIR" ]; then
  echo "warning: $HOOK_DIR does not exist (is Flame installed?). The plugin works without the hook," >&2
  echo "         but the viewer will not refresh by itself when a job finishes." >&2
elif [ -e "$HOOK_DIR/$LTX_HOOK" ]; then
  echo "LTX Alpha Gen's hook is installed: the plugin uses it, so its own hook is not needed."
  if [ -e "$HOOK_DIR/$HOOK" ] && hook_is_ours; then rm -f "$HOOK_DIR/$HOOK"; echo "removed the now unneeded $HOOK_DIR/$HOOK"; fi
else
  hook_is_ours || die "$HOOK_DIR/$HOOK exists and is not the Partner Models hook; the plugin was installed, the hook was not"
  rm -f "$HOOK_DIR/$HOOK"  # also a link left by a dev install
  install -m 0644 "$HERE/$BUNDLE/Contents/Resources/flame_hook/$HOOK" "$HOOK_DIR/$HOOK"
  echo "installed $HOOK_DIR/$HOOK"
fi
echo "Done: Partner Models $VERSION installed. Start Flame; the nodes are under Partner Models. On a node's Setup tab press Install, then save your Comfy API key."
