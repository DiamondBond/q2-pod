# 1.5.1 pre-release review

## Intent

Review `1.5.0..ab7f106` before releasing 1.5.1, preserving the queued features while checking correctness, battery use, playback latency, RAM and I/O.

## Reviewers and judgment

Two independent Codex reviewers used the pstack Interrogate rubric. Haiku 5.5 could not run: Claude returned its weekly usage limit, OpenCode's key had expired, and the configured Vercel route rejected the request. Codex reviewers were authorized as the fallback.

Both reviewers independently identified the same three actionable issues and checked the fixes:

| Act on                                                                                                      | Correction                                                                                                                                                  |
| ----------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Video hold actions bypassed audio queue filtering; video-only loads also kept videos.                       | Exclude video files from collected tracks and song hold menus, and filter video-only loads to an empty audio queue. Direct video playback stays in q2video. |
| Era Shuffle treated a 32-bit path hash as exact membership, admitting unrelated songs when hashes collided. | Match song-table IDs to record IDs, retaining four-byte keys and the existing sorted lookup.                                                                |
| Auto Light Mode left Coverflow's private frame and decoded textures in the previous mode.                   | Refresh the existing RAM buffers when the mode changes, including transparent placeholder pixels. Preserve the disk artwork cache.                          |

The fix review also caught and corrected extension-based classification of directories: a folder named `Album.mp4` retains its folder hold menu. Both reviewers checked stock disassembly: loading an empty queue and subsequently attempting playback return safely, and falling through to stock's long Play/Pause handler does nothing.

Consider/noted: no additional actionable findings. Dismissed: a suspected confirmation-prompt repaint loop. Stock's style setters do invalidate unconditionally, but the existing geometry guard skips the prompt after its first resize; no additional guard was needed.

## Battery and performance scope

The fixes add no timers or wakeups. Coverflow retains its normal frame/texture reuse: a mode change refreshes RAM once, and unchanged subsequent paints perform no extra decoding or rendering. Era's exact IDs remove path hashing without increasing key storage. Video filtering prevents unsupported video files from becoming audio queue successors.

Hardware battery consumption, sustained playback and physical input/display behavior were not measured. Emulator instruction counts and host checks do not establish device latency or battery life. The MP4 RAM estimate still needs real-device calibration, as documented in `patch/chapters.h`.

## Validation

Regression checks cover colliding paths in different decades, stationary Coverflow mode changes and transparent placeholders, unchanged paint reuse, mixed video/audio folder hold actions, video-only queue loads, extension-named directories, and one-time confirmation-prompt styling.

Passed:

- Release firmware builds for iPod and Legacy, plus asset geometry and mismatch rejection checks for both.
- Full MIPS UI suites: 1,976 scenarios for iPod and 1,458 for Legacy.
- Playback suites for both editions, including checkpoint/polling performance and folder speed. Cached successor lookup remains 25 emulated instructions in the reported 128-track cases.
- Coverflow host suite, including mode transitions, transparent placeholders and unchanged-paint reuse.
- Chapter/MP4 parser and process checks, basic build checks, `./tools/format.sh` and `git diff --check`.
- `graphify update .` refreshed the code graph.

The iPod payload is 452,952 bytes, 160 bytes above the pre-review HEAD build. Builds and tests are host/emulator validation; they were not installed on hardware. No release was published.
