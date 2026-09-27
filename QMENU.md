# Play/Pause Hold Queue Menu

Status: implemented in both normal and compact builds. The audited stock paths it
relies on are in [docs/internals.md](docs/internals.md#queue-menu).

## Goal

Hold **Play/Pause** on a highlighted song, album or folder to open a small menu
with **Play next** and **Add to queue**. Build a listening queue using the physical
controls while the current music keeps playing.

## Interaction

| Input                               | Behavior                                        |
| ----------------------------------- | ----------------------------------------------- |
| Short Play/Pause press              | Normal play/pause, exactly once.                |
| Hold Play/Pause on a supported item | Open the two-option queue menu once.            |
| Release after opening the menu      | Consume the release; do not toggle playback.    |
| Wheel while the menu is open        | Move between the two options.                   |
| Centre                              | Confirm the highlighted option once.            |
| Return                              | Dismiss without changing the queue.             |
| Touch an option                     | Perform the same action as centre confirmation. |

Use the native long-press timing, matching the existing button-shortcut pattern.
Keep existing Return shortcuts and centre-button power behavior. Outside supported
local music items, preserve stock button handling and lock rules.

The menu should identify the selected item in its title. After success, close it,
restore the browsing position; success shows no message. A failed operation must report the failure and
leave playback and the existing queue intact.

## Queue behavior

- **Play next:** insert after the currently playing track, ahead of the remaining
  queue. Each new invocation inserts at that position.
- **Add to queue:** append after the last queued track.
- A song adds one track. An album or folder adds its playable tracks in the same
  order and with the same folder traversal rules as stock playback.
- Adding an item never starts, pauses, restarts or seeks the current track.
  A paused player stays paused. With an empty queue, either action fills the queue
  without starting playback.
- Preserve intentional duplicates. Repeated hold events from one physical press
  must not open multiple menus or add multiple copies.
- Check stock shuffle/repeat behavior during the audit. **Play next** must mean
  the next audible track when playback advances, including in shuffle mode.

## Implementation

1. **Audit the native paths.** Trace `on_wm_keylong_fun`, the Play/Pause release
   path and `playpause_quick_click`. `KEY_PLAY` is already defined as 171 in
   `patch/offsets.inc`; the existing tests exercise native long-key handling and
   short Play/Pause. Find the smallest hook that retains stock input gates and
   consumes the release after a handled hold, even if the menu closes first.

2. **Resolve the selected music item.** Reuse the navigation selection and content
   identity in `patch/ringnav.c`. Audit local song, album and folder rows to obtain
   their native track identifiers or paths. Capture a stable item identity when
   the menu opens; never retain a recycled row-widget pointer as the target.
   Cancel safely if the source disappears or becomes invalid.

3. **Reuse the stock queue.** Trace the existing queue screen and mutation paths.
   Investigation leads include `playerqueue_page_init`, `player_refresh_playqueue`,
   `player_start_queue` and `mclLoadPlayList`; their names alone do not establish
   safe insertion APIs. Verify ownership, current-track position, track order,
   shuffle/repeat and failure behavior before selecting the mutation path. Reuse
   stock queue storage and refresh behavior.

4. **Add the two-option menu.** Reuse native dialog/list widgets and wheel
   navigation. Give the menu input ownership so wheel and centre actions cannot
   also reach the underlying list. Cancel pending centre activation when opening
   it. Clean up on dismissal, page destruction, screen-off or a lock transition.

5. **Integrate and document.** Add checked hook bytes and any required imports to
   the existing build machinery. Share the feature across both variants. Update
   the README controls and internals when implemented.

## Verification

Extend the existing MIPS checks in `tools/test_patch.py` for the new input path and
queue operations; use the current harness. Cover:

- Short press calls stock play/pause once; hold opens once; release after hold
  never calls play/pause; the following short press still works.
- Wheel, centre, Return and touch operate only on the menu while it is open.
- Correct song/album/folder target and order, including recycled list rows.
- Insert-next and append behavior, paused/empty queues, duplicates and native
  shuffle/repeat handling.
- Cancellation, unavailable items and queue-operation failure leave existing
  playback intact. Unsupported screens and locked/screen-off states retain their
  stock behavior.

Run the existing build and MIPS checks against fresh normal and compact builds,
following [building.md](building.md). On the Q2, play Album A, hold Play/Pause on
Album B, exercise both actions and inspect the resulting queue. Confirm that the
hold and release never pause A, B's tracks retain their order, and the next
audible track matches the chosen action. Check Return dismissal and the first
short Play/Pause press after closing the menu.

## Scope boundary

This feature adds the hold shortcut and its two queue actions. Queue reordering,
album shuffle, new persistence behavior, touch-and-hold activation and PEQ changes
are outside this plan.

## Final step

After implementing, run a ponytail-review subagent on the full diff, fix its
findings, then re-run all the checks above.
