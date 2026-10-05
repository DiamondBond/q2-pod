# Boot

The Q2 splash shown on the screen at power-on is a JPEG inside the rootfs. There is no on-device setting; changing it is part of building a firmware update.

| What       | Where                                                             |
| ---------- | ----------------------------------------------------------------- |
| Image      | `/release/assets/default/raw/images/xx/logo.jpg` (320x375 JPEG)   |
| Drawn by   | `/usr/bin/display_logo` (libjpeg, writes `/dev/fb0`)              |
| Started by | `/etc/init.d/S11logo_display_shell`, as soon as `/dev/fb0` exists |

## Boot sequence

BusyBox `init` runs `/etc/init.d/rcS`, which starts the `S??*` scripts in order:

1. `S10mdev`, `S10mount_ubifs`: devices and the data partition.
2. `S11logo_display_shell`: in the background, polls every 20 ms for `/dev/fb0`, then runs `display_logo` on the splash.
3. `S11module_driver_default`: `/module_driver/driver_default_init_script.sh` loads the drivers, among them `soc_fb.sh` (the framebuffer, so `/dev/fb0` appears and the splash is drawn) and the LCD panel.
4. `S20urandom`, `S40network`.
5. `S90play`: starts `dbus-daemon`, then the player: `/release/bin/demo`, or Rockbox first when it is chosen ([Rockbox](#rockbox)).

demo's `platform_init` starts `checkappprocess.sh &`, the watchdog: it checks with `pgrep` that `/release/bin/demo` runs and reboots if not. Stock checks every 2 s; Q2 Pod every 10 s ([internals.md](internals.md#battery)).

## Framebuffer

`/dev/fb0` is 320x375 (portrait), 32 bpp, red at bit 16 (BGRA in memory), with two pages: `module_driver/soc_fb.sh` loads `soc_fb.ko` with `layer0_frames=2` and `is_rotated=0`, and the driver makes `yres_virtual` = `yres` x frames. Landscape content is stored turned 90° clockwise, as the stock splash is.

- `display_logo` opens the framebuffer through `libhardware2` (`fb_open`, `fb_enable`), refuses a depth under 18 bpp, writes each pixel as `0xff000000 | R << 16 | G << 8 | B` and pans to page 0 (`fb_pan_display(fd, info, 0)`). It does not scale.
- demo's AWTK flush thread draws one page while the other is shown and swaps them with `FBIOPAN_DISPLAY`, then `FBIO_WAITFORVSYNC`. Q2 Pod's video player shares the same two pages ([internals.md](internals.md#videos)).

## Rockbox

Q2 Pod can share the device with [Rockbox](https://github.com/DiamondBond/rockbox/tree/shanlingq2), which runs from the microSD card. **Hold Play/Pause while powering on** to switch between them; the Q2 then starts the system chosen at every power-on until Play/Pause is held again.

| What       | Where                                                                                      |
| ---------- | ------------------------------------------------------------------------------------------ |
| Choice     | `/mnt/data/boot-target`: present for Rockbox, absent for Q2 Pod                            |
| Key check  | `/usr/bin/q2boot` (`patch/boot.c`): exits 0 while Play/Pause (`md-gpio-keys`, 108) is held |
| Rockbox    | `/mnt/mmc/.rockbox/rockbox`, run from that folder, its output in `rockbox.log` there       |
| Started by | `S90play`, in place of `/release/bin/demo &`                                               |

With Rockbox chosen, `S90play` waits up to 3 s for the card (`/tmp/mmc_add`), runs Rockbox and appends `exit N` to `rockbox.log`. Whenever Rockbox exits (its **Boot stock OS**, a shutdown or a crash), or the card has no Rockbox, demo starts with its usual name, so the watchdog finds it. Neither changes the choice, so the next power-on starts Rockbox again. Install Rockbox by unzipping its `rockbox.zip` to the card's root. A Rockbox that hangs keeps Q2 Pod away: hold its own escape key, Return, at power-on, or remove `/.rockbox/rockbox` with a card reader.

## Custom boot logo

Every build replaces the splash with `assets/boot-logo.jpg`. Pass another 320x375 JPEG with `--logo` to use your own:

```sh
python3 tools/build.py 'Q2 Firmware V1.32.zip' --out /tmp/q2-logo --logo my-logo.jpg
```

Flash `/tmp/q2-logo/update.tar` the normal way: copy it to the root of the microSD card, then **System settings → System Update → TF card update**. The update keeps the scroll-wheel patch, and **About** still shows the build on its **CFW. Version** row (`VERSION` in `tools/build.py`).

## Making a logo that works

- **Orientation: rotate upright artwork 90° clockwise before fitting it.** The stock JPEG is stored sideways because of the framebuffer orientation. The supplied SHANLING logo therefore reads downward along the left side of the stored JPEG and appears upright on the device.
- **Canvas: exactly 320x375 pixels, black.** `display_logo` does not scale the image. Fit the rotated artwork within both dimensions, preserve its aspect ratio, and centre it horizontally and vertically without cropping. The build rejects any other size.
- **Format: 8-bit, three-component baseline JPEG (RGB/YCbCr).** No PNG, alpha, grayscale or CMYK. The stock renderer assumes three decoded bytes per pixel; the builder rejects incompatible frame headers.
- **Keep it small.** JPEG data barely compresses and the repacked rootfs must stay within the stock image size (50,442,240 bytes). The stock splash is 47.8 KB and a rebuilt Stock rootfs with `assets/boot-logo.jpg` leaves about 12 KB of slack (iPod, without the Home carousel images, about 272 KB), so keep a Stock-build logo under about 28 KB (this file plus that slack); re-save at lower quality if the build fails with `Repacked rootfs exceeds stock size`. `assets/boot-logo.jpg` is about 16.5 KB.

The supplied logo comes from the [original artwork](https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRA0yLsPKygK-EqPHDCqGfsbNtwv2mp9Lk4l-aqDei6Qy85qhC-mONCnwo&s=10), transformed directly with ImageMagick. The downloaded source is a 428x346 PNG despite the URL having no filename. To reproduce the transform from that source:

```sh
magick original-logo.png -background black -alpha remove -alpha off -rotate 90 \
  -resize 320x375 -gravity center -extent 320x375 -colorspace sRGB -type TrueColor \
  -strip -interlace none -quality 92 assets/boot-logo.jpg
```

To check what landed in the image:

```sh
unsquashfs -cat /tmp/q2-logo/rootfs.squashfs release/assets/default/raw/images/xx/logo.jpg | sha256sum
sha256sum my-logo.jpg
```

## Notes

- Only `rootfs.squashfs` and the kernel are shipped in `update.tar`; the bootloader is untouched. Anything displayed before Linux starts is not affected.
- `manifest.json` records the logo's SHA-256, and identical inputs (including the logo) still produce an identical `update.tar`.
- The splash is only shown while the app starts, so a logo you dislike is cosmetic: flash a corrected update to replace it.
