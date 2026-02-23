#!/usr/bin/env bash
# =============================================================================
# build_deb.sh — Build a Debian/Ubuntu .deb package for LocalDiscord
# =============================================================================
#
# USAGE
#   bash build_deb.sh [--version X.Y.Z]
#
# REQUIREMENTS (install once on Ubuntu):
#   sudo apt install dpkg-dev fakeroot dos2unix
#
# OUTPUT
#   dist/localdiscord_1.0.0_all.deb
#
# INSTALL the resulting package:
#   sudo apt install ./dist/localdiscord_1.0.0_all.deb
#
# UNINSTALL:
#   sudo apt remove localdiscord
#   sudo apt purge  localdiscord   # also removes /usr/lib/localdiscord
# =============================================================================

set -euo pipefail

# ── Configurable variables ──────────────────────────────────────────────────
PKG_NAME="localdiscord"
PKG_VERSION="1.0.0"
PKG_ARCH="all"
MAINTAINER="Your Name <you@example.com>"

# ── Derived paths ───────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$SCRIPT_DIR/dist/deb"
STAGING="$BUILD_DIR/${PKG_NAME}_${PKG_VERSION}_${PKG_ARCH}"

# Filesystem locations inside the staging tree (mirrors the real /)
APP_LIB="$STAGING/usr/lib/$PKG_NAME"
APP_BIN="$STAGING/usr/bin"
APP_SHARE="$STAGING/usr/share"
APP_DOC="$APP_SHARE/doc/$PKG_NAME"
APP_APPS="$APP_SHARE/applications"
APP_ICONS="$APP_SHARE/icons/hicolor"
DEBIAN_DIR="$STAGING/DEBIAN"

# ── Parse arguments ─────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --version) PKG_VERSION="$2"; shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

# ── Preflight checks ────────────────────────────────────────────────────────
echo "==> Checking build dependencies..."

for cmd in dpkg-deb fakeroot python3; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "ERROR: '$cmd' not found."
        echo "Install build tools with:"
        echo "  sudo apt install dpkg-dev fakeroot"
        exit 1
    fi
done

# Convert Windows line endings if needed (safe to run on Linux too)
if command -v dos2unix &>/dev/null; then
    echo "==> Normalising line endings..."
    find "$SCRIPT_DIR/debian" -type f -exec dos2unix --quiet {} \;
    dos2unix --quiet "$SCRIPT_DIR/build_deb.sh" 2>/dev/null || true
fi

# ── Clean previous build ────────────────────────────────────────────────────
echo "==> Cleaning previous build..."
rm -rf "$STAGING"

# ── Create directory tree ───────────────────────────────────────────────────
echo "==> Creating staging directory tree..."
mkdir -p \
    "$DEBIAN_DIR" \
    "$APP_LIB" \
    "$APP_BIN" \
    "$APP_DOC" \
    "$APP_APPS" \
    "$APP_ICONS/48x48/apps" \
    "$APP_ICONS/scalable/apps"

# ── Copy application source files ───────────────────────────────────────────
echo "==> Copying application files..."

cp -r "$SCRIPT_DIR/src"          "$APP_LIB/"
cp -r "$SCRIPT_DIR/config"       "$APP_LIB/"
cp    "$SCRIPT_DIR/run.py"        "$APP_LIB/"
cp    "$SCRIPT_DIR/requirements.txt" "$APP_LIB/"

# Copy assets if they exist and are non-empty
if [ -d "$SCRIPT_DIR/assets" ] && [ -n "$(ls -A "$SCRIPT_DIR/assets" 2>/dev/null)" ]; then
    cp -r "$SCRIPT_DIR/assets" "$APP_LIB/"
fi

# ── Install launcher script at /usr/bin/localdiscord ───────────────────────
echo "==> Installing launcher script..."
cp "$SCRIPT_DIR/debian/launcher.sh" "$APP_BIN/$PKG_NAME"
chmod 755 "$APP_BIN/$PKG_NAME"

# ── Desktop entry ───────────────────────────────────────────────────────────
echo "==> Installing desktop entry..."
cp "$SCRIPT_DIR/debian/localdiscord.desktop" "$APP_APPS/"

# ── Icon (placeholder — replace with a real icon if you have one) ───────────
# If you have assets/icons/localdiscord.png, copy it:
ICON_SRC="$SCRIPT_DIR/assets/icons/localdiscord.png"
if [ -f "$ICON_SRC" ]; then
    cp "$ICON_SRC" "$APP_ICONS/48x48/apps/localdiscord.png"
fi

ICON_SVG="$SCRIPT_DIR/assets/icons/localdiscord.svg"
if [ -f "$ICON_SVG" ]; then
    cp "$ICON_SVG" "$APP_ICONS/scalable/apps/localdiscord.svg"
fi

# ── Documentation ───────────────────────────────────────────────────────────
echo "==> Installing documentation..."
cp "$SCRIPT_DIR/debian/copyright" "$APP_DOC/"
cp "$SCRIPT_DIR/README.md"        "$APP_DOC/" 2>/dev/null || true

# Compress changelog (Debian policy requires gzip)
gzip -9 -c "$SCRIPT_DIR/debian/changelog" > "$APP_DOC/changelog.Debian.gz"

# ── Calculate installed size (in KB) ────────────────────────────────────────
INSTALLED_SIZE=$(du -sk "$APP_LIB" | awk '{print $1}')

# ── Write DEBIAN/control ────────────────────────────────────────────────────
echo "==> Writing DEBIAN/control (Installed-Size: ${INSTALLED_SIZE} kB)..."
sed "s/Installed-Size: PLACEHOLDER/Installed-Size: ${INSTALLED_SIZE}/" \
    "$SCRIPT_DIR/debian/control" > "$DEBIAN_DIR/control"

# ── Copy maintainer scripts ─────────────────────────────────────────────────
echo "==> Copying maintainer scripts..."
for script in postinst prerm postrm; do
    if [ -f "$SCRIPT_DIR/debian/$script" ]; then
        cp "$SCRIPT_DIR/debian/$script" "$DEBIAN_DIR/$script"
        chmod 755 "$DEBIAN_DIR/$script"
        # Normalise line endings — shell scripts must have Unix LF
        command -v dos2unix &>/dev/null && dos2unix --quiet "$DEBIAN_DIR/$script"
    fi
done

# ── Set correct permissions on all staged files ─────────────────────────────
echo "==> Setting file permissions..."
find "$STAGING"  -type d -exec chmod 755 {} \;
find "$STAGING"  -type f -exec chmod 644 {} \;

# Restore executable bits
chmod 755 "$APP_BIN/$PKG_NAME"
chmod 755 "$DEBIAN_DIR/postinst" 2>/dev/null || true
chmod 755 "$DEBIAN_DIR/prerm"    2>/dev/null || true
chmod 755 "$DEBIAN_DIR/postrm"   2>/dev/null || true

# ── Build the .deb ──────────────────────────────────────────────────────────
DEB_FILE="$BUILD_DIR/${PKG_NAME}_${PKG_VERSION}_${PKG_ARCH}.deb"

echo "==> Building $DEB_FILE ..."
fakeroot dpkg-deb --build "$STAGING" "$DEB_FILE"

# ── Verify the package ──────────────────────────────────────────────────────
echo ""
echo "==> Package contents:"
dpkg-deb --contents "$DEB_FILE"

echo ""
echo "==> Package information:"
dpkg-deb --info "$DEB_FILE"

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Build complete!                                             ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  Package: $DEB_FILE"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  Install on Ubuntu / Debian:                                 ║"
echo "║    sudo apt install ./$DEB_FILE                              ║"
echo "║  Or:                                                         ║"
echo "║    sudo dpkg -i $DEB_FILE                                    ║"
echo "║    sudo apt-get install -f   # fix any missing deps          ║"
echo "║                                                              ║"
echo "║  Uninstall:                                                  ║"
echo "║    sudo apt remove localdiscord                              ║"
echo "╚══════════════════════════════════════════════════════════════╝"
