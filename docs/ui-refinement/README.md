# Native-size UI comparison

[Before](before.png), [after](after.png), and [battery levels / charging](battery.png) are 375×320 layout reconstructions using packaged firmware assets and the stock font, with sample metadata. They compare glyph size, clock spacing, percentages, and charge-level drawing; they are not hardware framebuffer captures.

The battery sheet shows 0%, 1%, 5%, 50%, 88%, 100%, then charging at 50% and 100%. MIPS checks verify the actual canvas rectangles and text positions, every ordinary Bluetooth/Wi-Fi/battery-mode combination, and codec fallback. Packaging checks measure `12:59 PM` and `100%` with the native font and check rounded-corner clearance.

Hardware verification is required before release: check these layouts through the glass, toggle both boot choices and restart, hold Play/Pause, exit Rockbox, remove the card before shortcut activation, and exercise Now Playing touch, wheel, favourites, modes, scrolling metadata, and seeking. No flashing or publishing was performed.
