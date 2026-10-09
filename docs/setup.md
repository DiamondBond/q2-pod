# Q2 setup guide

For a brand new Q2. You need the Q2, its microSD card, a computer and internet.

## 1. Install Q2 Pod

1. Download the latest `Q2.Firmware.*.zip` here: https://github.com/DiamondBond/q2-pod/releases/latest (the `-stock` file next to it looks like the normal Shanling player; either works).
2. Unzip it, then copy `update.tar` onto the card (the main folder).
3. Put the card in the Q2 and turn it on.
4. On the Q2: **System settings > System Update > TF card update**. Wait for the restart. Do not unplug it while it updates.

## 2. Install Rockbox

1. Download `rockbox.zip` here: https://github.com/DiamondBond/q2-rockbox/releases
2. Unzip it onto the card (the main folder). It adds a `.rockbox` folder.
3. Turn the Q2 on. Rockbox starts.

## 3. Install the themes

1. Download the zip here: https://github.com/DiamondBond/q2-rockbox-themes/releases
2. Unzip it onto the card. It fills in the `.rockbox` folder.
3. On the Q2: **Settings > Theme Settings > Browse Theme Files**. Pick one and load it.

## How to use it

- **Want the stock player (Q2 Pod) instead?** Hold Play/Pause while turning the Q2 on. It only lasts that time; the next start is Rockbox.
- **To copy music over USB:** turn on with Play/Pause held, plug in, drag your files over.
- **No card in it?** It starts Q2 Pod.
- **Bluetooth headphones with Rockbox:** shut Rockbox down (it goes to Q2 Pod), turn on Bluetooth and connect your headphones, and pick **Rockbox** on the Home menu (above Streaming). Rockbox starts and plays through the headphones. When it shuts down, you are back in Q2 Pod.

## If something goes wrong

- **Rockbox is stuck:** hold Return while turning the Q2 on. It goes to Q2 Pod.
- **Rockbox does not start:** the card must be exFAT or FAT32, and the `.rockbox` folder must be in the card's main folder.
- **Want the normal Shanling player back:** flash Shanling's stock V1.32 file the same way as step 1.
