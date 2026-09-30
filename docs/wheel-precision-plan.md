# Fine wheel sensitivity, gentler acceleration and aligned Key Tone

Status: implementation plan.

Source baseline: commit `81d979f`.

## Objective and scope

Make single-row selection dependable on the iPod Home screen and other menus,
while retaining fast navigation through long music lists. Implement this first
change set only: finer menu sensitivity, a gentler list acceleration curve,
Key Tone aligned with selection changes, one persistent sensitivity setting,
and validation. Key Tone alignment is required in this first pass, not deferred.

Apply the new behavior to the **iPod variant's logical list and dialog selection**:
Home, ordinary menus, virtual music tables, and wheel-enabled button dialogs.
Coverflow's track lists participate through the shared list path. Coverflow's
cover carousel, the Normal firmware variant, volume, and Now Playing scrubbing
retain their existing behavior. The pixel-scroll fallback without logical rows
also stays unchanged.

Page titles, transitions, alphabet jumping and new playback controls are covered
by the separate [iPod roadmap](ipod-roadmap.md). Reuse the stock click sound and
Key Tone on/off setting; no new sound
asset, audio engine or clicker preference is needed. Do not add dependencies,
replace the stock input driver, or introduce delayed event replay for this change.

## Evidence and diagnosis

Small wheel corrections can overshoot the intended Home row and require repeated
correction in the opposite direction. Duplicate input events or hardware bounce
have not been established as the cause.

- Home has seven rows. `ringnav()` already disables acceleration for lists of
  at most `SHORT_LIST_MAX` (16); every accepted directional event advances one
  row. Reducing acceleration alone cannot fix single-row selection on Home.
- `ramp()` treats same-direction events at most `WHEEL_RUN_MS` (140 ms) apart as
  a continuous run. Every 100 ms adds a row to the step, up to eight at roughly
  700 ms. A slower cadence still inside that window keeps building the run.
- The stock rotation handler converts wheel motion to key releases 172/173
  before our hook receives them. Inspection of stock V1.32's `get_direction`
  (`0x62587c`) and its caller (`0x6258e0`) shows differing movement thresholds
  during a gesture. These events are not fixed physical detents; a divider is a
  practical sensitivity adjustment that needs device calibration.
- V2.9 removed V2.8's 25 ms event-holding/replay approach. See
  [the changelog](changelog.md) and commit `46f9047`. Do not restore that machinery.
- Stock `on_wm_keydown_before_fun` (`0x4e8424`) calls `buzzeer_switch(1)` before
  selection is handled on key-up. The spelling `buzzeer_switch` is the actual
  exported symbol (`0x4f3cc8`). It checks the byte `g_keytone_flag` (`0xa38c31`)
  and invokes the stock `system("cmd_mcu write_str buzzer")` path. Merely adding a
  click on selection would leave the original raw-event clicks audible as well.

Read [navigation internals](internals.md), [iPod UI notes](ipod.md), and
[build and validation instructions](building.md) before implementation.

## Behavior to implement

### 1. Fine menu sensitivity

Add `Wheel: Fine / Normal` after the existing Accent and Home rows in
**System settings → Display**, using the existing row builder and config storage.

| Setting | Incoming events per selection step | Stored `IPOD/WHEEL` value |
| --- | --- | --- |
| Fine (initial proposed default) | 2 in the same direction | 0 |
| Normal | 1, as today | 1 |

Missing or invalid config values select Fine. Preserve the existing Accent and
Home values. The setting changes event density; **both settings use the gentler
iPod list ramp below**. “Normal” here does not refer to the Normal firmware build.

Use a small accumulator at the shared navigation decision point, after the stock
filter and navigation gates. At low speed, starting on row 0, four forward events
in Fine mode should leave the selection at `0, 1, 1, 2`. An emitted selection step
moves immediately; there is no timer that later delivers unfinished movement.

Requirements:

- Key movement state by window, surface, context, scope, row count, and direction.
  Short lists must maintain this identity even though they never accelerate.
- On reversal, discard the previous direction's remainder and acceleration;
  count the current event as the first event in the new direction. Fine mode
  therefore needs two fresh events for a one-row correction.
- Clear partial movement on touch, native click, centre or other button input,
  setting changes, unavailable/rejected navigation, and window/pane/scope/count
  changes. Handle page recreation and reused widget addresses using the existing
  ownership/invalidation patterns; retain no row pointer.
- A pause resets acceleration, but **does not discard partial movement** if the
  same live list and direction still own it. Two deliberately slow events must
  still produce one row. Explicit interaction/context changes clear that credit.
- A sub-threshold event still cancels pending centre confirmation, stops touch
  momentum/recall glide as appropriate, unhides the selection, wakes the native
  scrollbar, and repaints. Consume it with `STOP`; it must not reach volume.
- Preserve existing selection initialization/restoration. Revealing an initial
  selection is not an extra navigation step, and centre must still activate the
  row actually highlighted.

Two events is the initial calibration proposal, not a claim about an ideal
physical angle. Keep the divisor and timings as named constants. If device
testing shows excessive pickup travel, report that result and tune this bounded
approach before considering a lower-level input hook.

### 2. Gentler long-list acceleration

For eligible iPod lists with more than 16 logical rows, start with:

| Parameter | Proposed value |
| --- | --- |
| Maximum interval between events in a continuous run | 140 ms (existing value) |
| Initial period at one row per emitted step | 300 ms |
| Additional time for each subsequent speed increase | 200 ms |
| Maximum rows per emitted step | 8 |

With `elapsed` measured from the first event in the current continuous run:

```text
elapsed < 300 ms:  gain = 1
otherwise:        gain = min(8, 2 + floor((elapsed - 300) / 200))
```

Thus gain becomes 2 at 300 ms, 3 at 500 ms, and 8 at 1500 ms. The first event
starts at elapsed zero. Use unsigned elapsed-time arithmetic, as the current
code does, including clock wraparound.

Update run timing from **every accepted incoming navigation event, before the
sensitivity divider**. Otherwise two 100 ms events become an apparent 200 ms gap
and incorrectly break the 140 ms run window. Each completed pair in Fine mode
emits one step at the gain of that pair's final event. Normal emits on every event.

Lists of 16 or fewer rows always have gain 1. A gap over 140 ms, reversal, a list
boundary, or an interaction/context reset drops acceleration to 1. This remains
a duration-based ramp; do not describe it as measuring physical angular velocity.

`ramp()` is also used by Now Playing scrubbing. Separate the iPod list curve from
that caller and the existing Normal-variant/fallback behavior explicitly, using
the smallest change to the existing helper/call sites. Do not globally replace
constants and inadvertently change seek increments.

The fast-scroll letter must follow the new list gain. `paint_letter()` currently
compares `wheel_run` directly with `WHEEL_RAMP_MS`; update that assumption along
with the timer trigger. Show/rearm the letter on an emitted accelerated step,
and clear it on return to fine speed or another existing reset condition.

### 3. Preserve list-end behavior

Keep Home/settings hard ends and the audited local lists' existing bump and
pause-to-wrap behavior.

- Reaching an end discards accumulated movement and acceleration.
- Already at an end, process outward events through the existing edge handling
  before the divider: each event bumps/rearms the stop; the first outward event
  after the existing 300 ms pause wraps once. Clear movement credit on wrap.
- Measure the pause between **incoming events**, not emitted selection steps.
  Otherwise Fine mode could accidentally turn a continuous turn into a wrap.
- Inward movement starts a fresh, unaccelerated sensitivity sequence.

Keep the current 200 ms centre confirmation/double-press behavior and its guards.

### 4. Align Key Tone with navigation

On the scoped iPod list/dialog paths, use the same sound behavior in both Fine
and Normal sensitivity modes. With the existing Key Tone setting enabled:

| Navigation outcome | Audible wheel clicks |
| --- | --- |
| Partial movement below the sensitivity threshold | 0 |
| One emitted step that changes the selected row | 1 |
| An accelerated step that changes selection by several rows | 1 total, not one per skipped row |
| A successful pause-to-wrap | 1 |
| Hard end or end bump without a selection change | 0 |
| Merely revealing/restoring selection, rejected input or abandoned input | 0 |

Thus the four low-speed Fine events producing rows `0, 1, 1, 2` produce clicks
`0, 1, 0, 1`. Stopping with half a step pending produces no later sound. With
Key Tone off, all of these events remain silent. Non-wheel button feedback and
the excluded wheel paths retain the stock behavior and setting.

Implement sound ownership at the existing key-down/key-up boundary:

1. Add an **iPod-only** wrapper for `on_wm_keydown_before_fun` using the existing
   checked hook/trampoline mechanism. Determine whether the input belongs to the
   scoped logical-list navigation path without selecting a row, restoring a
   position, advancing the accumulator or mutating the shared live menu. This
   eligibility must agree with the key-up path and preserve stock gates/latches.
2. For an owned directional input, suppress only the raw key-down click while
   still executing the stock callback and returning its result. The minimal
   candidate is to save `g_keytone_flag`, set it to zero for that synchronous
   stock call, then restore the saved byte on every exit. Verify callback/reentry
   behavior before using this approach. Never persist a muted setting or leave
   the flag changed between callbacks. Non-wheel and excluded inputs run stock
   unchanged. Do not skip the stock body or clear its debounce/lock latches.
3. At key-up, after all gates and the divider, request `buzzeer_switch(1)` once
   when wheel navigation actually changes the logical selection, including wrap.
   The routine already honors Key Tone; use the current setting at emission.
   Keep this call in the wheel action path, not generic `select()` or paint code,
   which also run for restoration, touch, and repeated repaints.
4. Track only the minimal ownership needed for the corresponding down/up input,
   using the audited input lifecycle. Do not add a second click if stock already
   sounded on key-down. Clear ownership on a completed/abandoned input and prevent
   it leaking through a dropped release, a new press, or page recreation. If the
   page or input role changes between down and up, revalidate: no stale navigation
   click, duplicate stock click, or permanently silenced volume/button path.
   Cover these transitions explicitly in tests rather than using one sticky
   global mute flag or predicting the final row at key-down.

This relocates a click to the selection decision; it does not hold, replay or
synthesize key events. Keep the original buzzer duration and sound. The stock
buzzer command is synchronous, so measure its effect on responsiveness on-device;
do not add per-skipped-row calls, shell processes of our own, or queued click
bursts. Selection and sound should feel like one action.

## Repository implementation map

Line numbers are intentionally omitted here; find these symbols in the current
checkout rather than assuming the baseline has not moved.

| File | Relevant code and intended work |
| --- | --- |
| [patch/ringnav.c](../patch/ringnav.c) | `scratch_t`, `ramp()`, `drop_spin()`, `load()`, `ringnav()`: scoped movement credit, reset coverage, iPod list curve, and edge integration. Audit every direct `wheel_run = 0` assignment and every `ramp()` caller. |
| [patch/ringnav.c](../patch/ringnav.c) | `config_digit()`, lazy settings initialization in `accent()`, `setting_text()`, `setting_click()`, `ringnav_display()`: one persisted setting and its row. Existing `if (i)` branches assume only two settings; replace those assumptions explicitly without a settings framework. |
| [patch/ringnav.c](../patch/ringnav.c) | `paint_letter()`, `ringnav_touch()`, `ringnav_dispatch()`, centre/queue handling: overlay and reset integration. `np_key()` must retain current scrub behavior. `is_home()` identifies slide-menu carousels, not the iPod Home list. |
| [patch/ringnav.c](../patch/ringnav.c) | Add the scoped key-down sound wrapper and minimal down/up ownership. Emit the existing buzzer only for actual wheel-driven selection changes. Audit all click and reset paths. |
| [tools/build.py](../tools/build.py), [patch/trampoline.S](../patch/trampoline.S) | Add the key-down entry to `IPOD_HOOKS` and its stock resume trampoline (audited body starts at `0x4e8430`); import `buzzeer_switch` and size-check `g_keytone_flag` through the existing mechanisms. Retain SHA, address, PIC/GOT and manifest verification. Normal must not acquire this executable hook. |
| [tools/test_patch.py](../tools/test_patch.py) | Extend existing short/long-list, Home, config, letter, boundary, touch, centre and scrub scenarios, plus paired key-down/key-up sound checks. Use the current MIPS harness, not a parallel simulation of the proposed algorithm. |
| [tools/test_build.py](../tools/test_build.py) | Adjust existing build/layout expectations only if affected; verify both variants and packaging using the established checks. |
| [README.md](../README.md), [docs/internals.md](internals.md), [docs/ipod.md](ipod.md), [docs/building.md](building.md) | Update controls, timing, setting behavior and hardware checklist after implementation. Distinguish physical input events from emitted navigation steps and distinguish firmware variants. |

The iPod key-down sound hook is part of this first pass; no new asset or context
entry should be necessary. Reuse existing widgets, configuration APIs, scrollbar
handling and selection ownership. If that proves insufficient, explain the
concrete limitation before expanding the implementation.

## Validation

### Automated checks

Extend the existing scenarios with focused assertions for:

1. Fine and Normal event density on the real generated Home layout, ordinary
   lists, virtual tables and button dialogs. Include 0, 1, 16 and 17 logical rows;
   virtual-table behavior must depend on total rows rather than visible pool size.
2. Slow pairs separated by more than 140 ms still move one row in Fine mode, with
   no acceleration. Reversal clears credit; no movement happens after input stops.
3. Gain boundaries at 299/300, 499/500 and 1499/1500 ms; continuity at 140/141 ms;
   clock wraparound; both directions; the eight-row ceiling. Ensure the input
   sequence actually keeps the run continuous while testing elapsed boundaries.
4. Credit isolation across all reset conditions above, including scope/count
   changes without a new window and destroyed/recreated surfaces. A short-menu
   remainder cannot leak into another page or a volume/seek action.
5. A sub-threshold event cancels a pending centre action, interrupts momentum,
   reveals selection and is consumed. Centre subsequently selects the displayed
   row; double-press screen-off, power and lock gates still work.
6. Hard ends, bumps and pause-to-wrap measured from raw accepted events. Include
   a cadence where pairs are more than 300 ms apart but individual events are
   less than 300 ms apart: it must not accidentally wrap.
7. Letter overlay activation/expiry against the new curve; unchanged scrub,
   volume, carousel, fallback and Normal firmware behavior.
8. Missing, malformed and valid `IPOD/WHEEL` settings; persistence across a fresh
   machine/config reload; switching modes clears movement state; Accent and Home
   still cycle correctly; the new row is reachable with wheel, centre and touch.
9. Execute paired key-down/key-up events through the actual stock sound callback
   and new hook. Count audible buzzer commands at the mocked hardware/process
   boundary, not just calls to `buzzeer_switch` (it also runs when Key Tone is off).
   Prove Fine click counts `0, 1, 0, 1`, one click for each accelerated selection
   change and wrap, zero for partial steps/ends/bumps/rejected input/restoration,
   and no extra click on repaint or delayed centre confirmation. Existing
   `Machine.call()` defaults to key-up only and clears a stock debounce latch:
   release-only tests do not prove sound correctness. Preserve the actual latch
   lifecycle in the paired-event checks.
10. Verify Key Tone off, toggling it between events, and restoration of its byte
    after every suppressed stock call, including errors/rejections. Compare stock
    sound behavior for volume, scrub, carousel, centre, Return, Play/Pause,
    long/double presses, lock/wake and Normal firmware. Exercise a window/role
    change between down/up, dropped release, new press and reused widgets; require
    no doubled click, delayed click, stuck mute or altered button/volume action.

Build into fresh directories after source changes. With the prerequisites in
[building.md](building.md) installed, run:

```sh
python3 tools/build.py 'Q2 Firmware V1.32.zip' --out /tmp/q2-wheel-normal
python3 tools/build.py 'Q2 Firmware V1.32.zip' --out /tmp/q2-wheel-ipod --ipod --dev
python3 tools/test_patch.py /tmp/q2-wheel-normal
python3 tools/test_patch.py /tmp/q2-wheel-ipod
python3 tools/test_build.py
python3 tools/test_build.py 'Q2 Firmware V1.32.zip'
```

Use new output paths if these already exist. The harness rejects stale source
hashes. Run required packaging/reproducibility checks according to the existing
build instructions; do not publish a release as part of this change set.

### Hardware acceptance

These checks require a Q2 and are not satisfied by emulator success:

- Repeat the reference task on Home: twenty deliberate single-row selections
  in each direction using Fine, then compare Normal. Record overshoots and
  whether pickup travel feels excessive. Press centre after settling on each
  target and check that it opens the intended row.
- Try very slow movement and repeated reversals. Confirm that partial movement
  does not accumulate across pages or button actions and that stopping never
  causes a later row change.
- Browse a long music list: verify the deliberate initial phase, useful sustained
  speed, immediate loss of acceleration after a pause/reversal, and correct
  letter display. Record the chosen calibration constants and observed results.
- Exercise touch-to-wheel handoff, list ends, pause-to-wrap, dialogs, Coverflow
  tracks, screen lock/wake and centre double-press. Compare volume, scrubbing and
  cover-carousel behavior with the baseline.
- With Key Tone on, confirm one click per actual wheel selection update in both
  sensitivity modes. Partial movements, repeated outward turns at an end and
  end bumps must be silent; wrapping clicks once. Accelerated jumps must give
  one click without a burst or trailing audio. Compare sound timing with the
  visible highlight and check that the synchronous buzzer does not harm response.
- Turn Key Tone off and verify silence, then back on and verify correct recovery.
  Confirm original button/volume/scrub/carousel feedback, including lock/wake and
  moving between those roles and a list. Record device results alongside the
  sensitivity calibration; sound alignment is not a deferred acceptance item.

If hardware is unavailable, deliver the tested implementation with hardware
acceptance explicitly pending. Do not claim the proposed constants feel correct
from emulator tests alone.

## Completion criteria

- The scoped implementation and persistent setting work with no new dependency
  or event-replay mechanism.
- Both firmware variants pass the relevant existing and extended checks.
- Key Tone is aligned with actual selection changes in Fine and Normal
  sensitivity modes, respects the existing on/off setting, and preserves stock
  feedback on excluded paths. Both paired-event tests and device sound checks
  are reported; any unavailable hardware checks remain explicitly pending.
- Documentation describes the actual chosen divisor, curve and variant behavior.
- The implementation report lists changed files, validation results, calibration
  values and hardware results (or the outstanding device checks).
- This change set adds no unrelated iPod features and performs no release or
  device flashing without the applicable user authorization.
