#!/usr/bin/env bash
# Build HECTOR Desktop as a standalone macOS .app bundle.
#
# Prerequisites:
#   conda activate sc
#
# Usage:
#   ./macos_app.sh
#
# Output:
#   dist/HECTOR Desktop.app

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "==> Checking conda environment..."
if [[ -z "${CONDA_PREFIX:-}" ]]; then
    echo "ERROR: No conda environment active. Run: conda activate sc"
    exit 1
fi
echo "    Active env: $CONDA_PREFIX"

echo "==> Pre-flight: checking for conflicting Qt packages..."
# pyqt6 / qt6-main ship a separate (often older) Qt and a qt6.conf that
# overrides QLibraryInfo paths, causing PyInstaller to bundle plugins from
# the wrong Qt. The .app then crashes on launch with a Qt version mismatch.
CONFLICTS=$(conda list 2>/dev/null | awk '/^(pyqt6|qt6-main)\s/ {print $1}' || true)
if [[ -n "${CONFLICTS}" ]]; then
    echo "ERROR: Conflicting Qt packages detected in this env:"
    echo "${CONFLICTS}" | sed 's/^/    - /'
    echo ""
    echo "These conflict with PyPI's PySide6 and produce a broken bundle."
    echo "Remove them with:"
    echo "    conda remove pyqt6 pyqt6-sip qt6-main"
    exit 1
fi

echo "==> Installing build dependencies (PyPI)..."
pip install --quiet pyinstaller PySide6 pyqtgraph

echo "==> Installing hector-desktop (editable)..."
pip install --quiet -e .

echo "==> Installing hector-sc from local source..."
if [[ -d "../hector_package" ]]; then
    pip install --quiet -e "../hector_package"
else
    echo "WARNING: ../hector_package not found — assuming hector-sc is already installed"
fi

echo "==> Installing universal MLX metallib (MSL 3.1, macOS 14+ / M1-M5)..."
# The build machine's own mlx-metal wheel carries a metallib compiled for
# its macOS SDK (e.g. MSL 4.0 on macOS 26).  That metallib only loads on
# the same or newer macOS.  We swap it for the macosx_14_0 wheel whose
# metallib uses MSL 3.1 — backward-compatible with every Apple-Silicon
# GPU on macOS 15+.
MLX_METAL_VERSION=$(pip show mlx-metal 2>/dev/null | awk '/^Version:/ {print $2}')
if [[ -z "$MLX_METAL_VERSION" ]]; then
    echo "ERROR: mlx-metal not installed in this env"
    exit 1
fi
MLX_WHEEL_DIR="/tmp/mlx-metal-wheel-$$"
mkdir -p "$MLX_WHEEL_DIR"
pip download --no-deps \
    --platform macosx_14_0_arm64 \
    --python-version 3.12 \
    --only-binary :all: \
    "mlx-metal==${MLX_METAL_VERSION}" \
    -d "$MLX_WHEEL_DIR"
pip install --force-reinstall --no-deps "$MLX_WHEEL_DIR"/mlx_metal-*.whl
rm -rf "$MLX_WHEEL_DIR"
echo "    Installed mlx-metal ${MLX_METAL_VERSION} (macosx_14_0_arm64)"

echo "==> Cleaning previous build..."
rm -rf build dist

# Some FUSE and cloud-sync filesystems do not support symlinks, which
# PyInstaller's macOS BUNDLE step requires. Build in
# a local temp directory, create the DMG there, then copy back.
BUILD_ROOT="/tmp/hector-pyinstaller-$$"
BUILD_DIR="$BUILD_ROOT/build"
DIST_DIR="$BUILD_ROOT/dist"
mkdir -p "$BUILD_DIR" "$DIST_DIR"
trap 'rm -rf "$BUILD_ROOT"' EXIT

echo "==> Running PyInstaller (workpath=$BUILD_DIR, distpath=$DIST_DIR)..."
pyinstaller --clean hector_desktop.spec --noconfirm \
    --workpath "$BUILD_DIR" --distpath "$DIST_DIR"

echo ""
echo "==> Build complete!"
echo "    App bundle: $DIST_DIR/HECTOR Desktop.app"

VERSION=$(python -c "
import tomllib, pathlib
d = tomllib.loads(pathlib.Path('pyproject.toml').read_text())
print(d['project']['version'])
")
DMG_NAME="HECTOR-Desktop-${VERSION}-macOS.dmg"

echo ""
echo "==> Creating DMG installer..."
mkdir -p release
hdiutil create -volname "HECTOR Desktop" \
  -srcfolder "$DIST_DIR/HECTOR Desktop.app" \
  -ov -format UDZO \
  "release/${DMG_NAME}"

echo ""
echo "==> Done!"
echo "    DMG installer: release/${DMG_NAME}"
echo ""
echo "To test locally:"
echo "    open '$DIST_DIR/HECTOR Desktop.app'"
echo "    (The .app lives in /tmp until this terminal closes;"
echo "     install from the DMG for a permanent copy.)"
echo ""
echo "To distribute to another Mac:"
echo "    1. Transfer release/${DMG_NAME}"
echo "    2. Double-click to mount, drag HECTOR Desktop to /Applications"
echo ""
echo "NOTE: On first launch the other user may need to:"
echo "    Right-click > Open (to bypass Gatekeeper)"
echo "    Or: System Settings > Privacy & Security > Open Anyway"
