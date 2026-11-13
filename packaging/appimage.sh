#!/usr/bin/env bash
# Wraps dist/ios-homescreen (PyInstaller one-folder build) into an AppImage in out/.
# Usage: packaging/appimage.sh VERSION
set -euo pipefail
version="$1"
root="$(cd "$(dirname "$0")/.." && pwd)"
appdir="$root/build/AppDir"
rm -rf "$appdir"
mkdir -p "$appdir/usr/bin" "$root/out"
cp -r "$root/dist/ios-homescreen/." "$appdir/usr/bin/"
cp "$root/build/icons/ios-homescreen.png" "$appdir/ios-homescreen.png"
cat > "$appdir/ios-homescreen.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=ios-homescreen
Comment=Arrange your iPhone Home Screen
Exec=ios-homescreen
Icon=ios-homescreen
Categories=Utility;
DESKTOP
cat > "$appdir/AppRun" <<'APPRUN'
#!/bin/sh
here="$(dirname "$(readlink -f "$0")")"
exec "$here/usr/bin/ios-homescreen" "$@"
APPRUN
chmod +x "$appdir/AppRun"
tool="$root/build/appimagetool"
if [ ! -x "$tool" ]; then
  curl -fsSL -o "$tool" \
    https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
  chmod +x "$tool"
fi
ARCH=x86_64 "$tool" --appimage-extract-and-run "$appdir" \
  "$root/out/ios-homescreen-$version-linux-x86_64.AppImage"
