# Channing’s AirPods playback test

Experimental Bluetooth volume fix for both Q2 Pod variants, based on [PR #3](https://github.com/DiamondBond/q2-pod/pull/3). The existing 48 kHz AAC patch stays in place. Connected-but-silent playback may involve headset volume; the cause is unconfirmed until device testing.

Before installing, record:

- AirPods model: \***\*\_\_\*\***
- AirPods firmware version: \***\*\_\_\*\***
- Current Q2 firmware / Q2 Pod version and edition: \***\*\_\_\*\***
- Test ZIP filename and SHA-256: \***\*\_\_\*\***

## Install

1. Choose the iPod or Stock dev ZIP matching the desired UI. Verify it against the supplied `SHA256SUMS` (`sha256sum -c SHA256SUMS` on Linux).
2. Unzip it and copy `update.tar` to the root of the microSD card.
3. Start Q2 Pod (hold Play/Pause at power-on if the card boots Rockbox). Select **System settings > System Update > TF card update** and wait for the restart; keep power connected during the update.
4. About should show **V9.3 iPod dev** or **V9.3 Stock dev** on the CFW. Version row. These tests use Q2 Pod playback.

The updater refuses the same version tag. If already running V9.3i/V9.3s, install the stable V9.2 edition first, then this dev build. To roll back, install the stable Q2 Pod ZIP or stock Shanling V1.32 through the same menu.

## Test at low volume

Select AAC in Bluetooth quality settings and start with Q2 volume around 5. Have a known playable track on the card. Record audible playback and volume response for each path:

| Connection path                                | Audible? | Volume up/down and mute work? | Notes |
| ---------------------------------------------- | -------- | ----------------------------- | ----- |
| Pair/connect from the Q2                       |          |                               |       |
| Put AirPods in the case, then reopen/reconnect |          |                               |       |
| Turn Q2 Bluetooth off/on, then reconnect       |          |                               |       |
| Reboot Q2, then reconnect                      |          |                               |       |

After each connection, allow a few seconds for the audio transport to appear, start/resume playback, and try small volume changes including zero. Success means audible playback and working volume after every path. If silent, record whether playback time advances, whether changing volume helps, and whether reconnecting helps. Include model, firmware versions, edition, codec and the failing path when reporting results.

## Implementation and local checks

Both variants hook `mclSetBtVol`. An active Bluetooth output outside receiver mode reads absolute volume, maps the larger requested channel from 0–100 to 0–127 with rounding and clamping, and avoids redundant writes. Full software gain is used only when the headset value already matches or `btctl_transport_set_volume` returns 0. Unsupported readings and failed writes retain stock gain.

The main loop checks readiness every 400 ms and synchronizes the current Q2 volume once when a usable transport appears. Invalid readings and failed writes retry; disconnect, Bluetooth off, receiver mode, codec loss or a different audio output reset readiness. This changes no battery, ear detection, stem controls, cards or settings.

Build both with `tools/build.py --dev` (add `--ipod` for iPod), then run `test/patch.py`, `test/playback.py` and `test/build.py --build` against each output. The MIPS harness covers the shared hook, failure fallback, readiness and native `device_set_volume` routing for Bluetooth, wired and USB. Packaging checks retain the one-byte AAC assertion; the builder enforces the stock rootfs size limit. Hardware playback remains pending Channing’s test.
