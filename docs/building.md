# Build and validation

Rebuilt firmware uses `assets/logo.jpg` as the boot splash by default. Pass another 320x375 JPEG with `--logo` to use your own; see [boot-logo.md](boot-logo.md).

Requires clang/lld/llvm-objcopy, squashfs-tools 4.7 (tested 4.7.5), the test harness dependencies in `requirements.txt`, and the original ZIP:

```text
154c17822d09be001be35c03d2d3488424dee195221790bd70864480d55b0f00
```

SHA-256 of the stock Shanling Q2 V1.32 firmware ZIP.

```sh
python3 tools/build.py 'Q2 Firmware V1.32.zip' --out /tmp/q2-build
python3 tools/build.py 'Q2 Firmware V1.32.zip' --out /tmp/q2-compact --compact
python3 tools/build.py 'Q2 Firmware V1.32.zip' --out /tmp/q2-dev --compact --dev  # compact test build
python3 tools/test_peq.py  # PEQ parser/storage, DSP, editor and player checks (host cc; player needs -m32 libs)
python3 tools/test_coverflow.py  # Coverflow art cache: order, locks, markers, cancel, Refresh (host cc -m32, pthreads)
python3 tools/test_build.py  # JPEG header checks; no emulator required
python3 tools/test_build.py 'Q2 Firmware V1.32.zip'  # optional packaging/reproducibility checks
python3 tools/test_patch.py /tmp/q2-build  # after: pip install -r requirements.txt
```

Both variants replace the stock equalizer page with a ten-band PEQ editor (bands, shelves, preamp, on/off, presets, `/EQ` import) and patch `hciplayer`'s equalizer filter with the matching DSP.

`--dev` tags a build with the release version in lowercase (`V<version>r`/`V<version>c`), so a test unit is distinguishable from the release and the updater, which only refuses an identical version, installs the release over it. It applies to that build only: the release procedure never passes `--dev`, and the manifest records `dev: true`.

The suite executes the actual patched MIPS payload and stock key/touch filters. UI services are mocked; carousel checks execute native animator parameter writes and stock completion, with a deterministic animation scheduler, and audit the stock creation path. Separate scenarios execute the stock canvas clip/color/rectangle code and the stock rounded fill/stroke entry points down to mocked LCD and vgcanvas sinks. Case coverage lives in `tools/test_patch.py`; the device checklist is in [compact.md](compact.md).

The CPU-LCD fill path runs end to end down to mocked LCD sinks, including radius clamping, the `radius <= 2` decline and allocation balance. The stock rounded vgcanvas branch could not be executed end to end under Unicorn 2.1.4: the stock binary is built `-mfp64` and Unicorn's MIPS32 FPU only implements `FR=0`, so its 64-bit conversions trap. The test harness runs the branch up to the first such instruction and asserts the vgcanvas color and line-width calls that precede it.

The builder also rejects any `patch/contexts.inc` name that is not a window name in the stock rootfs UI assets, so an allowlist typo cannot silently disable a screen. Widget field offsets and shared ABI constants live in `patch/offsets.inc`; the payload and the test mocks read the same file.

The test runner refuses a `manifest.json` whose `source_sha256` does not match the current patch sources, and verifies the stock executable, patched executable and payload hashes against that manifest, so stale or mixed artifacts cannot pass as the current build.

A MIPS instruction-count regression check verifies that filling the position table does not increase steady paint or wheel work in the current scope. These are mocked-service instruction counts, not hardware latency measurements.

Two fresh builds must produce identical `update.tar` files. Packaging verifies MD5 entries, unchanged kernel and rootfs metadata, and a rootfs no larger than stock.

For on-device acceptance, browse a long list and confirm immediate response, a smooth pull up to eight rows per tick and precise reversal. Confirm that wheel turns make the player's own scrollbar appear and fade on the lists that have one, and that no other list changes. Tap and swipe across panes and pages and confirm no outline lingers or returns until wheel/centre input; also keep turning past a list end and confirm it stops while you keep turning, then pause and turn again to wrap, and hold Return both from browsing and on Now Playing in the compact build. Tune `WHEEL_RUN_MS`, `WHEEL_RAMP_MS` and `WHEEL_MAX_STEP` if needed. Check the selected-row margin in ordinary and music lists, including their ends and tall rows; spin the home wheel and confirm rapid turns visibly advance through multiple icons, reverse midway through both slow and fast slides, and check that no unwanted movement remains after the final slide settles. Tap a row as soon as a list appears, and again while a long list is still settling, and confirm the touched row opens. Also browse parent → child → grandchild folders, return to each selected folder, and check quick turns on short menus. In the compact build, confirm ordinary row titles use the space up to visible artwork and trailing controls without overlap. Also revisit albums/queries and confirm their selections remain separate. Emulator checks do not replace this hardware check.
