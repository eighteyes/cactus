#!/usr/bin/env bash
# build-mac-app.sh — build dist/Cactus.app and dist/Cactus-<version>.zip from mac/.
# Responsibilities:
# - swift build -c release, assemble the bundle, render Info.plist from the template
# - build an .icns from assets/icon-1024.png when present, else skip and say so
# - ad-hoc codesign; with CACTUS_SIGN_ID Developer ID + hardened runtime;
#   with CACTUS_NOTARY_PROFILE too, notarize and staple
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
version="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -1)"
[ -n "$version" ] || { echo "build-mac-app: no version in pyproject.toml" >&2; exit 1; }

(cd mac && swift build -c release)
bin="$(cd mac && swift build -c release --show-bin-path)/cactus-mac"

app="dist/Cactus.app"
rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
cp "$bin" "$app/Contents/MacOS/cactus-mac"

icon_xml=""
src="assets/icon-1024.png"
if [ -f "$src" ]; then
  set="$(mktemp -d)/Cactus.iconset"
  mkdir -p "$set"
  for s in 16 32 128 256 512; do
    sips -z $s $s "$src" --out "$set/icon_${s}x${s}.png" >/dev/null
    sips -z $((s*2)) $((s*2)) "$src" --out "$set/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns "$set" -o "$app/Contents/Resources/Cactus.icns"
  icon_xml=$'\t<key>CFBundleIconFile</key><string>Cactus</string>\n'
else
  echo "build-mac-app: $src missing, building without an icon"
fi

tpl="$(cat mac/Resources/Info.plist.in)"
tpl="${tpl//@VERSION@/$version}"
printf '%s\n' "${tpl//@ICON@/$icon_xml}" > "$app/Contents/Info.plist"

if [ -n "${CACTUS_SIGN_ID:-}" ]; then
  codesign --force --options runtime --timestamp -s "$CACTUS_SIGN_ID" "$app"
else
  echo "build-mac-app: CACTUS_SIGN_ID unset, ad-hoc signing only (not distributable)"
  codesign --force -s - "$app"
fi

zip="dist/Cactus-$version.zip"
rm -f "$zip"
ditto -c -k --keepParent "$app" "$zip"

if [ -n "${CACTUS_SIGN_ID:-}" ] && [ -n "${CACTUS_NOTARY_PROFILE:-}" ]; then
  xcrun notarytool submit "$zip" --keychain-profile "$CACTUS_NOTARY_PROFILE" --wait
  xcrun stapler staple "$app"
  rm -f "$zip"
  ditto -c -k --keepParent "$app" "$zip"
elif [ -n "${CACTUS_SIGN_ID:-}" ]; then
  echo "build-mac-app: CACTUS_NOTARY_PROFILE unset, signed but not notarized"
fi
echo "built $app and $zip"
