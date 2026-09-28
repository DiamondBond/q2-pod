# Changelog

- **V5.2R / V5.2C**: **PEQ: ON/OFF** now stays as you left it after a restart. Editing a band sets the preamp to just enough cut to keep boosts from clipping. Fast wheel spins on Coverflow no longer keep scrolling after the wheel stops or come to rest between two albums. The unused stock EQ preset images are removed, freeing rootfs space.
- **V5.1R / V5.1C**: Coverflow no longer keeps scrolling after you lift your finger: a swipe now settles on the album nearest to where you let go, instead of being thrown one or two albums further.
- **V5.0R / V5.0C**: Coverflow covers now reliably snap to the nearest album whenever they come to rest between two, including swipes the previous fix missed.
- **V4.9R / V4.9C**: Coverflow covers always snap into place when you let go of a swipe, instead of sometimes stopping between two albums.
- **V4.8R / V4.8C**: Coverflow tracks accept the Play/Pause hold queue menu (Play next / Add to queue), Coverflow remembers the last album and each album's highlighted track, and long album, artist and track names scroll. The payload is now built with `-Oz` so compact keeps room in the rootfs.
- **V4.7R / V4.7C**: Coverflow caches artwork in `.coverflow` on the microSD card and checks free space there, so low internal storage no longer prevents artwork preparation.

- **V4.6R / V4.6C**: New **Coverflow** card on Home, after Local Music: flip through your Local Music albums by cover with the wheel, open one to see its tracks, and play from there. The first open prepares the artwork once (from `cover.jpg`, `folder.jpg` or the embedded picture) with progress and Cancel; later opens only add new albums, and the last card, **Refresh library**, rebuilds it. The queue menu no longer shows a message after a successful add; it still shows **Queue unchanged** when it can't add.

- **V4.5R / V4.5C**: Hold **Play/Pause** on a highlighted song, album or folder in the local lists to open **Play next** / **Add to queue**. Tracks are added without pausing, restarting or seeking what is playing; a paused player stays paused, and with shuffle on, Play next is still the next track. Return closes the menu and the release after the hold never toggles playback.

- **V4.4R / V4.4C**: After a restart the PEQ editor now shows **PEQ: OFF**, matching the status-bar EQ icon and what you hear; the PEQ stays off after a reboot until you switch it back on, and your applied bands are kept.

- **V4.3R / V4.3C**: Saved PEQ presets can be deleted from **Presets → Delete a preset**, after a confirmation; the active EQ is unchanged.

- **V4.2R / V4.2C**: PEQ editor messages (Applied, Loaded, errors) now appear in the title bar instead of cutting the list down to two rows while they show. The title names the preset you loaded ("PEQ: HD650") and keeps the applied preset's name when you reopen the editor, until the next reboot.

- **V4.1R / V4.1C**: Artist pages now show their albums straight away; V3.8 highlighted the Album tab but opened an empty page until you switched tabs. PEQ editor lists no longer show a white strip below the last row.

- **V4.0R / V4.0C**: PEQ audio and import fixes. Band and preamp changes no longer click: filters keep their state across updates and the preamp is applied after them as a smooth ramp. Near-silent audio no longer drives the filters into slow denormal math. On low sample-rate files, a band above the file's frequency range is skipped instead of switching the whole EQ off. Imports match Equalizer APO more closely: LS/HS with a Q use APO's corner frequency, shelves without a Q use APO's default slope, comma decimals such as `-3,5` are accepted, empty `None` filter slots are skipped, and a shelf whose APO corner shift leaves 20–20000 Hz is clamped to the range instead of failing the import.

- **V3.9R / V3.9C**: The PEQ editor rows use white text instead of grey. The preamp is shown on one read-only row; set it in the preset (`Preamp:` in AutoEQ / Equalizer APO files) instead of the removed lower/raise controls. The editor drops its Back rows (Return steps back), shows only whole rows, shows the status line only when there is a message, and reads "Nothing to apply" until there are edits or a loaded preset to apply.

- **V3.8R / V3.8C**: Artist pages open on Albums; All Songs stays one tap away. The artist page tabs are now translated: stock firmware showed Chinese 单曲/专辑 there in every language.

- **V3.7R / V3.7C**: The stock equalizer is replaced by a ten-band parametric EQ with peaking and shelf bands, preamp, an immediate on/off switch that also drives the status-bar EQ icon, saved presets and AutoEQ / Equalizer APO `.txt` import from `/EQ` on the microSD card. Return steps back through the editor's screens. At the ends of the local folder and music lists the wheel now hard-stops while you keep turning; pause briefly, then turn again to wrap around.

- **V3.6R / V3.6C**: Compact Local Songs opens search with a pull-down. Start inside the list while it is at the top; the overlay reads "Pull to search" after an 8-pixel downward drag and "Release to search" at 48 pixels. Releasing opens the stock search dialog, and moving back below the threshold cancels. The gesture clears on wheel or button input, navigation, screen-off or interruption and never activates a row. Empty lists work; Folder view and other lists are unchanged, and the normal build keeps its stock search toolbar.

- **V3.5R / V3.5C**: In compact mode, ordinary list-row titles use the full row width on every native relayout, reserving space only for visible artwork and trailing controls. Widths follow scrolling, row reuse and artwork/control visibility changes; short titles stay at their left position and overflowing titles still scroll or ellipsize. Other layouts and the normal build are unchanged.

- **V3.4R / V3.4C**: The local folder and music lists carry over at their ends: the first turn past an end nudges the selection outline against the end, and the next turn in the same direction wraps to the other end of the same list. Wheel navigation now wakes the player's own scrollbar, which fades on its normal timer, instead of drawing a separate position bar. The local and online search result lists navigate with the wheel and the centre button; the on-screen keyboard dialogs keep the wheel on volume control. Compact Return now opens Now Playing on hold and stays there after release; the next short Return goes back to where you were, and holding Return while already on Now Playing uses the stock Home shortcut. This replaces the V3.3 single-press latch behavior.

- **V3.3R / V3.3C**: Compact returns from Now Playing with a single Return press again; the stock hold-release latch is cleared on that page instead of swallowing the release and forcing a second press.

- **V3.2R / V3.2C**: Compact rows now fill the client area with 72-pixel rows, so the stock artwork keeps its natural size with an even eight-pixel inset instead of being scaled down. Navigation and all other behavior are unchanged.

- **V3.1R / V3.1C**: Shared normal and compact builds, compact local lists and long Return to Now Playing, and a reproducible dual-variant release procedure.

- **V3.0R**: Long lists accelerate smoothly again: each 100 ms of sustained same-direction spin adds a row to the step, up to eight rows per tick, replacing the V2.7R/V2.8R three-speed ladder. Stopping, reversing or easing off still drops back to one row immediately. The selected-row outline is now a softer translucent white line, so it sits better against the dark theme while the dark separator still keeps it readable over bright album art. The shipped `config.ini` is no longer modified, so a fresh install keeps the stock key tone default; a device that already ran V2.9R keeps its saved setting and can change it in the system settings.
- **V2.9R**: Restores the stock wheel and button input path, removing the V2.8R 25 ms detent hold. The key tone now ships disabled, so wheel and button feedback is silent by default; enable **Key Tone** in the system settings to bring the clicks back. The three-speed wheel acceleration from V2.8R is unchanged.
- **V2.8R**: Wheel acceleration adds a third speed: longer lists step two rows after 300 ms and three rows after 600 ms of continuous same-direction turns. A wheel button press no longer plays a second tick from the capacitive touch, drops the phantom step with it, and the wheel is ready again as soon as the button is released.
- **V2.7R**: Wheel turns move the list immediately instead of animating, and lists longer than 16 rows step two rows after 450 ms of continuous same-direction turns. Touching the screen hides the selection outline until the next accepted wheel or centre action, including across page changes. Centre confirmation and the double-press screen toggle now use a 200 ms window.
- **V2.6R**: Wheel input replaces an unfinished scroll-view animation so reversing a glide toward a list boundary takes effect immediately. Native clicks also reset wheel acceleration and the home wheel interval when no touch-down event was delivered.
- **V2.5R**: Native clicks cancel pending centre confirmation even without a touch-down event. Rejected confirmations leave changed lists and their remembered positions untouched. Double-press still turns the screen off after interrupting a recalled list with touch. Custom boot logos must use the stock renderer's supported JPEG frame format; packaging uses a snapshot of the validated image.
- **V2.4R**: Taps and centre presses stay bound to the row they started on, so a rebuilt or still-settling list cannot move the row under your finger or open a different one. Page-snapping views no longer capture the wheel, and a failed rounded outline stroke falls back to the square outline.
- **V2.3R**: Wheel selection and restored positions keep a small margin from the screen edge, and reversing the home wheel responds immediately to correct an overshoot.
- **V2.2R**: Remembers the 64 most recently selected browsing positions, restoring folders and music queries on return. Lists of 16 or fewer items stay at one row per wheel detent, even during quick turns.
- **V2.1R**: Fast-spin acceleration stays within the current menu and resets after a folder/query change, list resize, interrupted gesture or sleep. Oversized rows reveal their title consistently when selected or restored.
- **V2.0R**: Centre presses now confirm after 300 ms, allowing a second press within that window to turn the screen off. Home carousel wheel input is paced to make cards easier to select. Includes an orientation fixed boot logo.
- **V1.9R**: The selection outline is now one crisp white line over a dark separator and the subtle dark fill, so it stays readable over bright album art. A canvas that declines rounded drawing keeps the square outline.
- **V1.8R**: Wheel acceleration, gliding music tables, a scoped double-press screen toggle, nested tap-target selection, per-context position memory with row-text identity, multi-pane surface selection, a centre-nearest swipe settle and a build-time context audit.
- **V1.7R**: Added centre button double-press to toggle the screen on/off.
- **V1.6R**: Home screen now keeps the stock selected-card highlight without any extra outline.
- **V1.5R**: Added menu item highlighting, centre-button selection, and music selection features.
