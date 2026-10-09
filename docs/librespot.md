**Librespot is plausible on the Q2, but needs a custom port.** SoundCloud is out of scope.

The Q2 already has Linux, Wi-Fi, ALSA audio and OpenSSL—the main building blocks. The difficult part is compiling librespot for its particular MIPS floating-point ABI. Upstream removed MIPS from its supplied cross-build setup, so there’s no ready-made build to install. [Cross-compilation notes](https://github.com/librespot-org/librespot/wiki/Cross-compiling)

The smallest useful first version would be:

- **Streaming → Spotify Connect**, launching librespot from the microSD card.
- Q2 streams and decodes music itself; your phone selects music through Spotify Connect.
- Spotify Premium required. Browsing playlists directly on the Q2 would need additional UI and integration work. [Librespot](https://github.com/librespot-org/librespot)

First we should prove a compatible binary can start, authenticate and play through the Q2’s audio output. That establishes feasibility before adding menus.

## Port

The port lives in [DiamondBond/q2-librespot](https://github.com/DiamondBond/q2-librespot), a librespot fork. Its branch `shanlingq2` is v0.8.0 plus an IPv4 fallback for discovery, because the Q2's kernel has no IPv6. Its `contrib/shanlingq2/` holds the build, the card launcher and the README.

- **Release:** [q2-librespot's releases](https://github.com/DiamondBond/q2-librespot/releases/latest) ship the prebuilt card files as `q2-librespot-*.zip`, unzipped to the card's root.
- **On the card:** the binary, its launcher and its sink go in the card's `.spotify` folder, with the saved login in `.spotify/cache/`. Q2 Pod starts it; see the [guide](guide.md#spotify) to install it.
- **Build:** librespot is built **static and soft-float (musl)**, so the firmware's `-mfp64`, NaN-2008 and glibc 2.28 don't matter. The kernel still requires the `nan2008` ELF flag, so the build sets it.
- **Audio:** goes through the stock `aplay` to `plughw:0,0`, the CS43131 headphone DAC, started only while librespot plays (its subprocess backend), so local music can open the DAC whenever Spotify is paused.

**It plays.** On the device, librespot appears in Spotify Connect, the phone's session authenticates, and audio comes out of the headphones at 160 kbit/s. Soft-float decoding keeps up, with no stutter heard.

## Q2 Pod

**Streaming → Spotify** opens a Now Playing page for it: the cover, title, artist and album, a moving progress bar and the play state, in Now Playing's layout in both builds. Q2 Pod treats librespot as a source of its own playback, as it treats Videos' q2video:

- **Start:** once per boot, from the row, or at boot once the card holds a saved login.
- **Power:** while it plays, standby, auto power-off and the DAC's power-off are held off; the screen still turns off.
- **DAC:** set up as stock's AirPlay receiver sets it (`config_outputchannel`, as a headset insert does, then PCM mode, unmuted and the Q2's volume).
- **Keys:** Play/Pause and the side buttons control Spotify while it was the last thing played; the wheel is the Q2's volume, which is Spotify's.
- **Hand-over:** casting stops local music; starting a local track pauses Spotify first.

The fork adds two options for this: `--status-file`, the player's state, track, position and cover for the page, and `--control-socket`, the commands from the keys. How they fit together is in [internals.md](internals.md#spotify).
