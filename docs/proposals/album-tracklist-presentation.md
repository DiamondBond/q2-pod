# Album track-list presentation: Minimal and Modern

## Scope

Apply the proposal to **both Minimal and Modern themes**, in **both light and dark variants**.

This is a deliberately narrow UI change. Preserve the existing layout and styling everywhere else.

## Proposed changes

### 1. Album title separators

Add one short horizontal line on each side of the album title, matching the supplied mockup's placement, length, thickness, spacing and vertical alignment.

The lines should flank the title symmetrically. Do not add a full-width divider or change the title's typography, position or surrounding spacing.

### 2. Album artist in each track's detail line

Show the album artist on the secondary line for every song in an album track list. Keep the entire detail line horizontally centred.

- When **Scan Song Durations** is enabled and a duration is available: `Album Artist · 3:30`
- When the duration is disabled or unavailable: `Album Artist`

The middle dot and its surrounding spaces must only appear when a duration is actually displayed. Never leave a trailing or leading separator.

Use the album artist for the album, rather than each track's individual artist. Preserve the current duration toggle behaviour.

## Explicit non-goals

Do not change:
- song-title text, font, size, weight or alignment;
- row height, selection highlight, colours, margins or spacing;
- album title text, font, size, weight or position;
- playback controls or any other screen;
- Classic or Classic Modern theme behaviour;
- any unrelated UI or firmware behaviour.

## Acceptance criteria

- [ ] The title has two short, symmetric horizontal lines exactly as shown in the supplied mockup.
- [ ] The result is consistent in Minimal Light, Minimal Dark, Modern Light and Modern Dark.
- [ ] Album track details are centred and read `Album Artist · duration` when a duration is shown.
- [ ] With **Scan Song Durations** off, the detail reads only `Album Artist`; there is no middle dot.
- [ ] If a duration is unavailable, the artist remains visible without a separator.
- [ ] No other visual or behavioural changes are introduced.

## Implementation notes

The existing Cover Flow album-track list is built in `patch/coverflow.c`. It already obtains durations through `duration_text()`, which respects the **Scan Song Durations** setting, and the album record exposes album-artist metadata. The implementation should compose the detail string from those existing values rather than introducing a new setting or changing duration scanning.

The title separators should be scoped to the centred album-track title used by Minimal and Modern, and should follow the active theme's foreground colour so they remain legible in both light and dark modes.

## Validation

This proposal does not claim that firmware changes have been implemented or tested. Before merging an implementation, validate the four theme/colour combinations and run the repository's required checks.