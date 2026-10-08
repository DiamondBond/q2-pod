# Q2 Pod: Discord feedback summary

Source: Q2 Pod Discord export, 2026-10-03 to 2026-10-08. Covers #feedback (84 messages), #general (819) and #updates (10).
Images were not reviewed; the export only links them. Raw text is in `~/dce/txt/`.
Trimmed against V9.7: items it or earlier releases already cover are removed.

## Bugs still open

1. **Bluetooth stutters after skipping a track.** Reported on 9.4 and 9.6 (ohokayluke, AirPods Pro 2), with both AAC and LDAC. It does not happen when a song ends on its own. On 9.6 they also reported BT "really choppy on most of the songs" during a walk, which may be a regression. The 9.4/9.5 flush fixes did not resolve it.
2. **AirPods double-tap skip/pause does nothing.** They connect and play, but the controls do not reach the Q2.
3. **Lock screen is just black.** It needs user-supplied images, and nothing tells the user. Fix: a built-in placeholder image or a line in the docs.
4. **Playlist import is confusing.** M3U files only import from the `_explaylist_data` folder that export creates (dinglehopper found this by trial and error). This is stock Shanling behaviour, so documenting it is the quick fix.
5. Touch targets such as the favourite heart are hard to hit on the small screen. Minor.

## Feature requests, ranked by how many people asked

1. **Battery life** (vanyakatana, adamve, ohokayluke). Low power and Charge limit exist since V8.6; remaining ideas are a CPU governor (it runs at 100% all the time) and powering down unused DAC chips.
2. **Layout:** a narrower left menu and shorter labels ("Playback", not "Playback Settings") so less album art is cut off (vanyakatana, ohokayluke). Also an option to hide the status bar, with a two-swipe gesture to keep Quick Settings reachable.
3. **Font size:** a reader font size for Books, and a system-wide size. adamve wants smaller and beelzalbob wants bigger, so it must go both ways.
4. **Library lists:** Most Played longer than 100 (up to about 200), unlimited Recent and Recently Added history, and a "Long" tab for songs over 10 minutes (deferred because it needs a full SD card scan).
5. **Bluetooth:** now-playing info when the Q2 is used as a Bluetooth DAC from a phone.
6. **Smaller items:**
   - Bookmarks inside long tracks.
   - Renaming playlists (9.1 added delete; there is no rename yet).
   - Volume steps per wheel click. One user wants bigger steps; one with sensitive IEMs wants smaller. Wheel sensitivity does not cover this: volume still moves one step per event.
7. **Long term:** Spotify/Apple Music, Chromecast, Shanling's remote app, and more Rockbox themes (some current ports are broken).

## Users missed features that already exist

Several people asked for things that are already there:

- the hold-Play/Pause actions menu (also has Next/Previous album during album shuffle)
- double-click the center button to turn the screen off
- the Album Artist toggle
- custom boot logos (`assets/boot-logo.jpg` on the SD card)
- where the wheel-sensitivity setting is (Settings → Display)
- Low power and Charge limit (System settings → Power management)
- Coverflow Sort by Recently Added or Most Played

A short "tips" page or a first-boot hint screen would cut down on these questions.

## Not actionable in software

No physical power button, the large screen corner radius, and one dead-on-arrival touchscreen.
