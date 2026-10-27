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

## Follow-up review through 3e2f850

Two independent Codex reviewers repeated the pstack Interrogate review of the full `1.5.0..3e2f850` range, including the earlier fixes, with battery and performance regressions in scope.

Act on (Reviewer B): rejecting an oversized MP4 preload left `MCL_PRELOAD` at zero. Stock's `mclAutoChange` retries while it is zero during the last five seconds, repeatedly scanning the next MP4 and reading `/proc/meminfo`. The hook now records stock's failed-attempt state, -1, for both RAM and speed-boundary refusals. Stock disassembly confirms successful starts and track transitions reset it; queue and speed edits also clear it through `close_preload`.

Act on (Reviewer A): playback admission lacked direct integration coverage. The playback suite now checks start refusal and recovery, nonlocal bypass, a one-shot toast and gapless refusal/delegation, including ten actual stock `mclAutoChange` ticks that scan a refused successor only once. The host suite continues to check the actual MP4 estimator.

Act on (Reviewer B): update stale descriptions of video-only audio queues, Era's exact ID membership and the Auto label. No other confirmed runtime regression was found. Consider/noted: the existing MP4 RAM calibration remains a hardware validation limit. Dismissed: an early playback refusal bypassing a required decoder stop; stock itself has early error returns before decoder setup.

The regression reproduces nine MP4 scans in ten stock player ticks before the fix and one afterward. Cached 128-track successor lookup remains 25 emulated instructions.

The battery review found no new periodic timer. Auto checks the clock during existing UI passes, and touch-release repaint remains one-shot. The preload correction removes repeated file and memory checks near the track boundary; hardware battery impact was not measured.

Final checks passed: release builds and asset geometry/mismatch checks for both editions; 1,976 iPod and 1,458 Legacy MIPS UI scenarios; both playback suites including the new admission and stock retry regression; Coverflow host checks; chapter/MP4 parser and process checks; basic build checks; `./tools/format.sh`; `git diff --check`; and `graphify update .`. Payloads are 452,968 bytes (iPod) and 365,304 bytes (Legacy), each 16 bytes above the reviewed HEAD. No hardware installation or release publication was performed.
