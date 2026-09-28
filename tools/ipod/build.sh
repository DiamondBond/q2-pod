#!/bin/zsh
# Build the "iPod 2026" variant from the stock Shanling Q2 V1.32 ZIP.
# Usage: tools/ipod/build.sh "/path/to/Q2 Firmware V1.32.zip" [VERSION] [--dump]
#   VERSION: 5 characters containing a 'V' (the updater rejects others), default V2.6R.
#   --dump:  debug build (widget dumps and Bluetooth/AirPods/theme logs on the microSD card).
# Needs: llvm + lld + squashfs (brew install llvm lld squashfs), python3 with pillow and
# unicorn==2.1.4. Optional: IPOD_APPLE_LOGO=1 draws Apple's logo on the boot splash from the macOS
# system font (not shipped); IPOD_HOME_TITLE sets the Home header.
set -euo pipefail
here=${0:A:h}; root=${here:h:h}; zip=${1:?stock V1.32 zip}; ver=${2:-V2.6R}; dump=${3:-}
work=$(mktemp -d); trap 'rm -rf $work' EXIT
mkdir -p "$work/shim"; ln -sf "$(command -v llvm-readelf || echo /opt/homebrew/opt/llvm/bin/llvm-readelf)" "$work/shim/readelf"
export PATH="$work/shim:/opt/homebrew/opt/llvm/bin:/opt/homebrew/opt/lld/bin:$PATH"
# Stock UI assets -> theme overlay (Apple Music dark look, iPod lists/Home/Now Playing).
unzip -p "$zip" '*/update.tar' | tar -xOf - recovery-update/rootfs.squashfs > "$work/rootfs.sq"
unsquashfs -q -d "$work/raw" "$work/rootfs.sq" release/assets/default/raw
python3 "$here/ipod_theme.py" "$work/raw/release/assets/default/raw" "$work/overlay"
cd "$root"
python3 tools/build.py "$zip" --out "$work/build" --overlay "$work/overlay" --version "$ver" \
    --ipod --row-inset 6 --accel --aac48 ${dump:+--dump}
python3 tools/test_patch.py "$work/build"
mkdir -p dist && cp "$work/build/update.tar" "dist/update-$ver.tar"
echo "Built dist/update-$ver.tar (copy it to the microSD card root as update.tar, then TF card update)"
