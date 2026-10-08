**Librespot is plausible on the Q2, but needs a custom port.** SoundCloud is out of scope.

The Q2 already has Linux, Wi-Fi, ALSA audio and OpenSSL—the main building blocks. The difficult part is compiling librespot for its particular MIPS floating-point ABI. Upstream removed MIPS from its supplied cross-build setup, so there’s no ready-made build to install. [Cross-compilation notes](<https://github.com/librespot-org/librespot/wiki/Cross-compiling>)

The smallest useful first version would be:

- **Streaming → Spotify Connect**, launching librespot from the microSD card.
- Q2 streams and decodes music itself; your phone selects music through Spotify Connect.
- Spotify Premium required. Browsing playlists directly on the Q2 would need additional UI and integration work. [Librespot](<https://github.com/librespot-org/librespot>)

First we should prove a compatible binary can start, authenticate and play through the Q2’s audio output. That establishes feasibility before adding menus.

## Port

The port lives in [DiamondBond/q2-librespot](https://github.com/DiamondBond/q2-librespot), a librespot fork. Its branch `shanlingq2` is v0.8.0 plus an IPv4 fallback for discovery, because the Q2's kernel has no IPv6. Its `contrib/shanlingq2/` holds the build, the card launcher and the README.

- **No firmware change:** the binary and its launcher go in the card's Rockbox slot (`/mnt/mmc/.rockbox/rockbox`), which the boot hook runs at power-on.
- **Build:** librespot is built **static and soft-float (musl)**, so the firmware's `-mfp64`, NaN-2008 and glibc 2.28 don't matter. The kernel still requires the `nan2008` ELF flag, so the build sets it.
- **Audio:** goes through the stock `aplay` to `plughw:0,0`, the CS43131 headphone DAC. A small helper switches the DAC on first, the same way q2-rockbox does.

**It plays.** On the device, librespot appears in Spotify Connect, the phone's session authenticates, and audio comes out of the headphones at 160 kbit/s. Soft-float decoding keeps up, with no stutter heard.

It isn't integrated with Q2 Pod yet, because Q2 Pod doesn't know librespot is playing:
- The Q2's keys and volume don't reach librespot. Only the phone controls it.
- Standby still runs, so playback stopped when the screen went off.
- A headphone replug was needed once before sound came through.

The next step belongs on Q2 Pod's side. It would treat librespot the way it treats q2video, keeping the power timers and DAC power up while it plays, and forward keys and volume to librespot. The plan is [q2-librespot.md](https://github.com/DiamondBond/q2-librespot/blob/shanlingq2/q2-librespot.md) in the fork.
