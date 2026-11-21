# Bluetooth track information

Q2 Pod publishes local title, artist, album, genre, duration and playback state through BlueZ's player store. Receivers choose which fields to display. Bluetooth buttons keep their existing stock route.

`patch/btmeta.c` uses the existing playback pass to write a bounded record on track, state or seek changes. It renames a complete file inside `/tmp/q2-bt` on the existing RAM filesystem. Paused seek commits supply their target directly; Play or a different track retires that target. Position uses track-relative CUE time and a monotonic timestamp, so ordinary playback does not need repeated writes.

`patch/mpris.c` waits on the D-Bus socket and inotify directory notifications, registering when BlueZ and a valid record are available. Each string is validated once as UTF-8. Metadata precedes Position because the target daemon resets position when it receives Metadata; state and seek changes omit unchanged Metadata.

S90play starts one helper for each demo run. After demo exits it terminates and waits for the helper, then removes the old record before Rockbox starts. The helper makes a bounded UnregisterPlayer call and closes its D-Bus connection before exiting. Direct Rockbox boot starts no metadata helper; returning to demo starts a fresh helper and record.

A full system-bus failure ends metadata until the next demo run. A failed registration waits for another record, BlueZ owner or adapter event; there is no timed retry or helper restart service.
