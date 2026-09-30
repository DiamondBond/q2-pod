# Build and validation

Rebuilt firmware uses `assets/logo.jpg` as the boot splash by default. Pass another 320x375 JPEG with `--logo` to use your own; see [boot-logo.md](boot-logo.md).

Requires clang/lld/llvm-objcopy, squashfs-tools 4.6 or later (tested 4.6.1 and 4.7.5), ImageMagick 6 or 7 for the iPod UI's settings icons (`convert` or `magick`; tested 6.9.12), the test harness dependencies in `requirements.txt`, and the original ZIP:

```text
154c17822d09be001be35c03d2d3488424dee195221790bd70864480d55b0f00
```

SHA-256 of the stock Shanling Q2 V1.32 firmware ZIP.

```sh
python3 tools/build.py 'Q2 Firmware V1.32.zip' --out /tmp/q2-build
python3 tools/build.py 'Q2 Firmware V1.32.zip' --out /tmp/q2-ipod --ipod
python3 tools/build.py 'Q2 Firmware V1.32.zip' --out /tmp/q2-dev --ipod --dev  # iPod test build
python3 tools/test_peq.py  # PEQ parser/storage, DSP, editor and player checks (host cc; player needs -m32 libs)
python3 tools/test_coverflow.py  # Coverflow art cache and depth renderer (host cc -m32, pthreads)
python3 tools/test_coverflow.py --captures /tmp/cf  # the same, plus the renderer's frames as PNGs
python3 tools/test_build.py  # JPEG header checks; no emulator required
python3 tools/test_build.py 'Q2 Firmware V1.32.zip'  # optional packaging/reproducibility checks
python3 tools/test_patch.py /tmp/q2-build  # after: pip install -r requirements.txt
```

Both variants replace the stock equalizer page with a ten-band PEQ editor (bands, shelves, preamp, on/off, presets, `/EQ` import) and patch `hciplayer`'s equalizer filter with the matching DSP. Both also clear the 44.1 kHz AAC capability bit in `bluealsa` (see [internals.md](internals.md#bluetooth-aac)).

`--dev` tags a build with the release version in lowercase (`V<version>r`/`V<version>i`), so a test unit is distinguishable from the release and the updater, which only refuses an identical version, installs the release over it. It applies to that build only: the release procedure never passes `--dev`, and the manifest records `dev: true`.

The suite executes the actual patched MIPS payload and stock key/touch filters. Coverflow's depth renderer also runs as MIPS and must draw byte for byte what the host build of the same source draws; the suite prints its instruction count per frame, which is a relative measure only, not a frame time. UI services are mocked; carousel checks execute native animator parameter writes and stock completion, with a deterministic animation scheduler, and audit the stock creation path. Separate scenarios execute the stock canvas clip/color/rectangle code and the stock rounded fill/stroke entry points down to mocked LCD and vgcanvas sinks. The iPod wheel scenarios deliver each tick as the pair stock posts, key-down-before through the hook and the stock callback and then key-up-before, leave the stock latches as stock does, and count Key Tone clicks as the `system()` commands the real `buzzeer_switch` issues, the one mocked boundary; the stock binary runs the same presses for comparison. Case coverage lives in `tools/test_patch.py`.

The CPU-LCD fill path runs end to end down to mocked LCD sinks, including radius clamping, the `radius <= 2` decline and allocation balance. The stock rounded vgcanvas branch could not be executed end to end under Unicorn 2.1.4: the stock binary is built `-mfp64` and Unicorn's MIPS32 FPU only implements `FR=0`, so its 64-bit conversions trap. The test harness runs the branch up to the first such instruction and asserts the vgcanvas color and line-width calls that precede it.

The builder also rejects any `patch/contexts.inc` name that is not a window name in the stock rootfs UI assets, so an allowlist typo cannot silently disable a screen. Widget field offsets and shared ABI constants live in `patch/offsets.inc`; the payload and the test mocks read the same file.

The test runner refuses a `manifest.json` whose `source_sha256` does not match the current patch sources, and verifies the stock executable, patched executable and payload hashes against that manifest, so stale or mixed artifacts cannot pass as the current build.

A MIPS instruction-count regression check verifies that filling the position table does not increase steady paint or wheel work in the current scope. These are mocked-service instruction counts, not hardware latency measurements.

Two fresh builds must produce identical `update.tar` files. Packaging verifies MD5 entries, unchanged kernel and rootfs metadata (normal's Coverflow card icons are the only added inodes, with `menu_music`'s metadata; the stock EQ preset page and the images only the stock EQ pages show are removed, and in iPod also the 14 Home carousel images; iPod's 40-pixel settings icons replace the stock files in place, see [ipod.md](ipod.md#settings-icons)), and a rootfs no larger than stock. The icons are 32-colour palette PNGs and the payload is built with `-Oz` because of that limit: normal has about 12 KB of rootfs space left, iPod about 272 KB (its 40-pixel settings icons are Lanczos-filtered RGBA, about 14 KB more than the stock 52-pixel ones).
