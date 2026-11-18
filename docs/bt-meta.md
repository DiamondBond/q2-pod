# Bluetooth track information

Q2 Pod publishes the local player's title, artist, album, genre, duration, track and playback status to BlueZ's standard media-player store. Compatible cars can request those fields over AVRCP. This does not add album artwork or replace the existing Bluetooth button route.

`patch/btmeta.c` reads the existing player state at most four times per second while Bluetooth is active. It prepares a bounded 2 KiB record; its single worker writes that record atomically in a private 64 KiB tmpfs. The UI does no metadata-file I/O. S90play starts one `q2mpris` supervisor before the demo loop, so restarting demo does not start another supervisor. A failed tmpfs mount leaves playback working without metadata publication. No Bluetooth capture, packet socket, diagnostic toasts, SD log/export or new SD writer is included.

`patch/mpris.c` registers `/q2pod/player` with `org.bluez.Media1.RegisterPlayer`, then sends MPRIS properties when the record changes. Metadata precedes Position because the target daemon's Metadata parser resets position. Status/seek changes omit Metadata. The helper reconnects after the system bus or Bluetooth daemon restarts. A delayed owner-up notification can follow successful registration; the exact `org.bluez.Error.AlreadyExists` response means the same adapter, unique publisher connection and path already own that player. It restores local registration and republishes all current fields. Other errors still fail and retry normally. Release, owner/bus loss and the optional card-root `q2pod-btmeta-off` file still invalidate registration.

The producer's wire timestamp is absolute CLOCK_MONOTONIC, low 32 milliseconds, matching the helper. Toolkit-relative time remains only in local poll/seek bookkeeping. A failed or invalid producer clock read skips publication and retries on the next eligible poll without advancing dedup state. An old Playing record therefore projects from its actual producer timestamp even after a helper restart; wrap uses unsigned subtraction.

The helper deduplicates the complete record text, rather than rejecting an equal generation number: demo restarts its producer counter while the helper survives. A new title with the same generation must still be published.

ponytail: publication proves a local queued update, not that every receiver displayed it. Local-player tags are the source; artwork, every streaming owner and remote-control interoperability are not established by these trials. Q2 Bluetooth OFF/ON on the upstream-based build remains a normal-use hardware check, separate from the successful Tesla-menu reconnects. The narrow clock correction has deterministic target/host tests but has not yet been hardware-tested in this build.

Review status: device logs recorded a q2mpris SIGSEGV during reconnect/playback testing. Its cause remains unresolved. Target emulation passing is not evidence that the device fault is fixed. Keep this change draft pending investigation.
