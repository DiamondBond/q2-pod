# iPod interaction roadmap

Status: planned. Source baseline: commit `81d979f`.

This roadmap covers four independent improvements, in recommended implementation
order. Fine wheel sensitivity, acceleration and Key Tone alignment belong to the
separate [wheel precision plan](wheel-precision-plan.md).

The existing iPod build already has a split/full Home menu, selection bars and
chevrons, position memory, Coverflow, a status-bar clock, playback metadata and
wheel scrubbing. Extend those features using the stock widgets and navigation
paths. Keep these additions specific to the iPod variant.

## 1. Page titles in the status bar

### Intended behavior

Add **Header: Clock / Page title** under **System Setting → Display**, retaining
Clock as the default. Page title shows the current browsing page's translated
heading in the centre of the status bar, giving context after its original
navbar has been hidden. Use the clock on pages without a suitable title or where
the existing heading remains visible. Home and Coverflow need explicit headings.

Dialogs retain the underlying page's heading; they must not expose internal
window names. Long titles must stay within the existing space between the status
icons, using the stock label's overflow behavior.

### Repository implementation

- Reuse `label_clock`, created by `status_bar()` in
  [tools/compact.py](../tools/compact.py). Its narrowest available width is
  109 pixels. Preserve the icon geometry and rounded-glass margins.
- Extend `clock_sync()` and its call from `ringnav_paint_bg()` in
  [patch/ringnav.c](../patch/ringnav.c). The existing minute-only cache must also
  respond to page, title, language and label-instance changes. Switching back to
  Clock must refresh immediately, even within the same minute.
- Obtain titles from the stock translated heading in `view_navbar`, which
  remains allocated when hidden. Audit the native title constructors first:
  some headings are unnamed `hscroll_label` widgets, so a universal named-widget
  lookup is insufficient. Read the heading from the live page; do not retain a
  pointer after its window is destroyed.
- Use the existing Display row builder, `setting_text()`, `setting_click()` and
  `config_digit()`, with one persisted `IPOD/HEADER` value. Missing or invalid
  values select Clock. Extend the current row indices and setting storage
  explicitly; account for the Wheel row from the wheel precision work.
- Keep fallback handling local to this feature. There is no need for a new
  navigation stack or a second copy of the stock translation catalogue.

### Acceptance

Browse Home → Local Songs → Artists → Albums → tracks, nested folders and
settings, then Return through each level. Each title must match the current page
immediately, including when a stock window is reused. Check dialogs, quick
settings, language changes, long/non-Latin titles, sleep/wake and destroyed/reopened
pages. All status icons must remain visible. Confirm setting persistence and that
Clock still fits `12:59 PM` and updates across a minute boundary.

## 2. Short directional page transitions

### Intended behavior

Opening a child browsing page slides it in from the right; Return reverses that
movement. Start with a proposed duration of **150 ms**, then tune on hardware
while music is playing. The transition should communicate hierarchy without
making a button press feel delayed.

Apply this to ordinary parent/child browsing. Keep dialogs, quick settings,
Coverflow's cover motion and Home's layout switching on their existing paths.

### Repository implementation

- The stock binary contains `window_animator_htranslate_create` at `0x683a08`.
  Audit its supported arguments and the native open/close animation path before
  adding imports or hooks. Upstream AWTK uses the `anim_hint="htranslate"`
  property; confirm the firmware's version supports the same contract and the
  desired duration control.
- Prototype one parent/child pair through the existing asset transformation in
  [tools/compact.py](../tools/compact.py), with stock asset hashes pinned in
  [patch/compact.json](../patch/compact.json). Prefer a native animation hint over
  a custom timer, screenshot cache or page renderer.
- Let the native window stack manage open/close order and selection restoration.
  Audit paths that reuse a window, especially folder browsing: an asset hint may
  not animate an in-place content change. Keep those paths immediate initially
  if the native animator cannot represent them safely.
- `ringnav()` already gates input while the window manager is animating, and
  centre activation already waits for the double-press interval. Measure the
  combined press-to-interaction delay. Do not queue wheel events for replay or
  alter the screen-off double press to hide transition latency.
- If the native path cannot meet responsiveness and audio checks, leave that
  page immediate. A custom transition framework is outside this feature.

### Acceptance

Verify forward and reverse direction, parent selection restoration, rapid
centre/Return input, wheel input during animation, touch immediately after
arrival, nested folders and repeated open/close cycles. Check clipping, rounded
corners, status-bar stability and artwork flashes on the actual LCD. Play local
music throughout; animations must not cause audible stutter or delayed actions
after they finish. Normal-variant navigation must remain unchanged.

## 3. Real alphabet navigation for long sorted lists

### Intended behavior

A sustained fast wheel gesture on a long alphabetically sorted list enters a
letter-navigation mode. Each accepted navigation step moves to the first row of
the next or previous initial group, and the existing large letter overlay shows
that group. Reversing direction moves to the previous group. Pausing exits the
mode so ordinary movement can select a nearby row precisely.

Centre opens the currently selected row and exits the mode. Touch, leaving the
page, sorting or reloading the list also exits it. Use the list's existing end
and wrap rules. This changes how a sorted list is traversed; wheel event density
and acceleration remain owned by the wheel precision implementation.

### Repository implementation

- `paint_letter()` in [patch/ringnav.c](../patch/ringnav.c) currently displays
  the selected visible row's first non-space character during acceleration. It
  does not build groups or jump between initials. Reuse its drawing and
  `LETTER_*` constants for feedback.
- Begin with one audited alphabetically sorted local list, then expand to
  Songs, Artists and Albums only where their actual sort mode and record order
  support it. Do not infer alphabetical order from the page name.
- Use the logical record collection, such as `p_deque_showlist`, after verifying
  its one-to-one mapping to logical rows on each supported page. The recycled
  visible widget pool cannot locate offscreen group boundaries. Existing local
  record access and row-count guards are documented in
  [navigation internals](internals.md).
- Derive the initial from the field displayed and sorted on that page: track
  title, artist or album. Respect stock ordering and translations for unknown
  metadata. Define behavior for leading spaces, case, digits and symbols against
  that ordering. Start with simple supported initials; retain ordinary navigation
  for unsupported scripts or sort modes instead of inventing a collation system.
- Derive mode entry from the accepted wheel run established by the wheel work.
  Keep one tunable entry threshold and an idle exit interval. Calibrate both on
  hardware; do not introduce a competing acceleration detector.
- Scan for the next group boundary in the current logical list. Measure the
  cost on a large library before adding a cache. If caching is necessary, tie it
  to the list's lifetime and invalidate it on sort, reload and scope changes;
  a persistent library-wide index is unnecessary.
- Exclude playback queues, track-number-ordered album lists, mixed file/folder
  lists, grids, short menus and online lists until their ordering is explicitly
  supported. Their existing movement remains available.

### Acceptance

Use a library with repeated initials, missing letters, mixed case, leading
spaces, digits, symbols, empty metadata and non-Latin names. Verify the first row
of each group, reverse movement, both ends, idle exit and centre activation.
Exercise offscreen groups, virtual-row recycling, sort changes, Refresh, touch
and leaving/re-entering a list. Unsupported sorts must use ordinary navigation.
Confirm responsive movement and uninterrupted playback on a large library.

## 4. Button access to Now Playing lyrics and information

### Intended behavior

Keep the current single-centre entry to scrubbing and double-centre screen-off
gesture. Extend single presses to reach the existing lyrics and information
pages without requiring a swipe:

| Current state       | Single centre press                   |
| ------------------- | ------------------------------------- |
| Artwork             | Enter scrub mode, as today            |
| Scrub, target moved | Commit the seek and return to artwork |
| Scrub, no movement  | Exit without seeking and show lyrics  |
| Lyrics              | Show track information                |
| Track information   | Return to artwork                     |

The wheel controls volume outside scrub mode. Return retains its existing
behavior. Touch swipes still work, and the next centre press follows the page
actually displayed. Missing lyrics use the stock empty-state message.

### Repository implementation

- `playing_page()` in [tools/compact.py](../tools/compact.py) already preserves
  the native `slide_view`, artwork, lyrics, information and page indicator.
  Reuse those pages; no new layouts or metadata engine are needed.
- Extend `np_key()` and `np_toggle()` in
  [patch/ringnav.c](../patch/ringnav.c). The existing `scrub_moved` flag provides
  the distinction between confirming a seek and continuing to lyrics. Capture
  that distinction before `scrub_end()` clears the flag.
- Audit the stock slide-view active-page getter/setter and notifications before
  importing them. Use the same path as touch so the indicator and callbacks stay
  synchronized. The current payload has no verified page-switch helper to assume.
- Keep the delayed single-press handling and cancellation of a pending single
  press on a double press. A double press must not accidentally advance a page
  or enter a new scrub session.
- Preserve the existing seek guards: one seek only after movement, no seek to a
  previous track, CUE-relative positions, timer restoration, and cancellation on
  page destruction through `np_gone()`. Read the live slide-view state instead of
  maintaining an independent page counter that can diverge after a swipe.
- Scrub timeout and Return retain their current commit/exit behavior; only an
  explicit single centre press with no scrub movement advances to lyrics.

### Acceptance

Cycle through every state using physical buttons. Mix swipes and button presses,
including absent lyrics, paused playback, track changes and CUE tracks. Verify
the page indicator, normal wheel volume, scrub preview, timeout, Return and page
destruction. Count seeks: unchanged targets produce none, moved targets commit
once. Double-centre screen-off must work from every displayed page without a
delayed page change on wake.

## Delivery and validation

Implement each feature as a separate change. Page titles are the smallest first
step; alphabet navigation should follow completion of the wheel precision work.
The source baseline identifies the researched behavior, so check the current
branch before extending shared settings or input handling.

For each implemented feature:

- Add focused coverage to the existing `tools/test_patch.py` MIPS harness for
  changed runtime behavior and `tools/test_build.py` for changed asset contracts.
  Audit and pin any new native call or patched instruction.
- Build and validate both firmware variants using [building.md](building.md).
  Keep Normal unaffected and preserve packaging/reproducibility checks.
- Run the feature's hardware acceptance checks with music playing. Update the
  behavior descriptions and regression checklist in [ipod.md](ipod.md) once the
  feature is implemented and verified.

The existing device checklist is validated, including boot/resume. Numerical
Coverflow frame-rate measurement remains pending and is separate from these
planned features. None of these additions is required to close that measurement.

## Reference behavior

The [Apple iPod classic user guide](https://cdsassets.apple.com/live/6GJYWVAV/user/ma1195_ipod_classic_160gb_user_guide.pdf)
describes menu context and alphabet navigation on pages 8–9 and the centre-button
playback views on page 25. These are interaction references; the Q2 control
mapping above preserves its existing buttons and screen-off gesture.

The [upstream AWTK UI example](https://github.com/zlgopen/awtk/blob/master/design/default/ui/basic_fscript.xml)
demonstrates a horizontal translation animation hint. The bundled Q2 runtime
still requires its own compatibility audit before that hint is used.
