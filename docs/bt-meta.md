# Bluetooth track information

Q2 Pod publishes the local player's title, artist, album, genre, duration, track and playback status through BlueZ's standard media-player store. Compatible receivers choose which fields to display. This does not add album artwork or change the existing Bluetooth button route.

`patch/btmeta.c` samples the existing playback state at most four times per second while Bluetooth is active, using the existing UI playback pass. It writes a complete snapshot of at most 2 KiB only when tags, playback status, queue information or a seek change. Ordinary playback advances from a monotonic timestamp without repeated position writes. Bluetooth being enabled again forces a fresh snapshot. No producer thread or new sampling timer is created.

Position and duration use stock's track-relative time wrapper, including CUE segment bounds; unavailable or stopped time is zero. The existing paused seek commit passes its target to `btmeta.c`, which retains it while the same track remains paused at the original reported second. A second commit publishes even below the ordinary seek threshold. On resume, the committed timeline advances for at most two seconds of Playing while the decoder catches up; pausing suspends that budget. Clock catch-up, timeout, a track/path change or stop retires the hold and explicitly publishes the reported anchor, including small corrections. The single call in navigation.c belongs to its existing paused seek branch; metadata state stays in btmeta.c.

The snapshot is written to a temporary file and renamed within the private `/tmp/q2-bt` directory on the existing `/tmp` tmpfs. Failed writes, closes or renames leave the change pending for a later eligible pass. Publication checks that the filesystem is RAM-backed. There is no private mount, SD marker check, capture socket or SD log writer.

ponytail: change-only tmpfs calls now run on the UI thread. They avoid card I/O but can allocate memory or wait under pressure; actual device latency remains to be measured.

`patch/mpris.c` watches the containing directory before reading the initial snapshot, so replacing the file by rename does not lose its watch. Notifications trigger a read of the latest complete state; intermediate states may coalesce. Queue overflow resynchronizes the snapshot. Invalidating the directory watch ends the helper so its existing supervisor can restart it and establish a new watch.

The helper waits for its first valid snapshot before registering a player; a missing or malformed startup file does not advertise invented empty metadata. A valid Stopped record with an empty title is accepted. After a valid record has been read, a temporarily missing or malformed file leaves that cached record available.

ponytail: if something outside this path deletes the record and its directory after publication, an unchanged paused producer still deduplicates its last successful write. The supervisor recreates the directory, but a fresh helper waits until a real metadata/status/seek change or Bluetooth gate cycle republishes the snapshot. Detecting external loss without another producer event would require an additional notification or existence check.

The helper uses libdbus readiness and timeout callbacks alongside file notifications. It does not periodically reread the snapshot. BlueZ ownership and adapter interface changes drive registration, with a fresh snapshot read immediately before `RegisterPlayer`. S90play retains one supervisor that waits while the helper runs and delays five seconds after failure. Bus setup failure or disconnection ends the helper; the same supervisor relaunches it and replays the latest paused or playing snapshot without another producer write. Ordinary Bluetooth off/on uses bus ownership events without that delay. The five seconds is the restart wait, not a total recovery deadline: D-Bus setup and registration calls can also wait for replies. Unsupported notification setup stops the supervisor rather than repeatedly launching an unusable helper.

A timed registration attempt returns to the dispatch drain before polling, including its last failed attempt: a synchronous libdbus reply can leave readiness signals, Release or property requests queued after consuming their socket wakeup.

Metadata precedes Position because the target daemon's Metadata parser resets position. Status-only and seek-only updates omit Metadata. The existing control capability flags preserve stock button handling. The complete record is compared for deduplication: a producer restart may reuse a generation number with different metadata. Absolute monotonic milliseconds, rather than toolkit-relative time, allow position projection after helper restart.

The helper source has no card-root disable marker, command-line overrides or diagnostic logging path. Host and target tests use a private bus through the standard system-bus address environment variable; instrumentation and synthetic path adapters live only in the test harness. Property replies, registration and change signals share their value writers. Parsing commits only a bounded complete record, rejects duplicate fields and invalid numbers, and repairs invalid UTF-8 bytes. The helper uses the firmware's vendor libdbus; standard headers remain a build dependency.

## Review limits

This local redesign is undergoing validation and has not been installed on a Q2. Device logs previously recorded a `q2mpris` SIGSEGV during reconnect/playback testing; its cause remains unresolved. Passing host or target-emulation tests does not establish that the device fault is fixed. Keep PR #420 draft pending that investigation and hardware validation. Timer, settings and PNG fixes are separately scoped.
