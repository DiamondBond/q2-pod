**Librespot is plausible on the Q2, but needs a custom port.** SoundCloud is out of scope.

The Q2 already has Linux, Wi-Fi, ALSA audio and OpenSSL—the main building blocks. The difficult part is compiling librespot for its particular MIPS floating-point ABI. Upstream removed MIPS from its supplied cross-build setup, so there’s no ready-made build to install. [Cross-compilation notes](<https://github.com/librespot-org/librespot/wiki/Cross-compiling>)

The smallest useful first version would be:

- **Streaming → Spotify Connect**, launching librespot from the microSD card.
- Q2 streams and decodes music itself; your phone selects music through Spotify Connect.
- Spotify Premium required. Browsing playlists directly on the Q2 would need additional UI and integration work. [Librespot](<https://github.com/librespot-org/librespot>)

First we should prove a compatible binary can start, authenticate and play through the Q2’s audio output. That establishes feasibility before adding menus.

No firmware changed or librespot build tested yet; CPU load, memory use and Bluetooth playback remain unverified.