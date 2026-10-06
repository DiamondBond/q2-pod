#!/bin/sh
# Stock's Bluetooth setting and last paired headset are the only controls.
settings=$(awk '
    { sub(/\r$/, ""); gsub(/^[ \t]+|[ \t]+$/, "") }
    /^\[/ { section = $0; next }
    section == "[SYSSET]" && /=/ {
        key = substr($0, 1, index($0, "=") - 1)
        value = substr($0, index($0, "=") + 1)
        gsub(/^[ \t]+|[ \t]+$/, "", key)
        gsub(/^[ \t]+|[ \t]+$/, "", value)
        if (key == "BLUETOOTH") { enabled = value; n++ }
        if (key == "BTLINKMAC") { mac = value; m++ }
    }
    END { if (n == 1 && m == 1 && enabled == "1") print mac }
' /mnt/data/config.ini 2>/dev/null)
printf '%s\n' "$settings" | grep -Eq '^([[:xdigit:]]{2}:){5}[[:xdigit:]]{2}$' || exit 0
[ "$settings" != '00:00:00:00:00:00' ] || exit 0
mac=$(printf '%s' "$settings" | tr 'a-f' 'A-F')
[ "$mac" != 'FF:FF:FF:FF:FF:FF' ] || exit 0
reply=$(mktemp /tmp/q2bt.XXXXXX) || exit 0
trap 'rm -f "$reply"' EXIT
child=
cleanup() {
    trap '' TERM INT
    [ -z "$child" ] || { kill "$child" 2>/dev/null; wait "$child" 2>/dev/null; }
    exit 0
}
trap cleanup TERM INT
pause() { sleep "$1" & child=$!; wait "$child"; child=; }
# Do not reset the radio on Home handoff: that would drop an existing link.
if ! pidof rtk_hciattach >/dev/null; then
    cmd_gpio set_func PD20 output1 || exit 0
    pause 0.1
    rtk_hciattach -n -s 115200 ttyS0 rtk_h5 >/dev/null 2>&1 &
fi
for i in 1 2 3 4 5 6 7 8 9 10; do
    hciconfig hci0 >/dev/null 2>&1 && break
    [ "$i" = 10 ] && exit 0
    pause 1
done
if ! pidof bluetoothd >/dev/null; then
    hciconfig hci0 reset || exit 0
    bluetoothd >/dev/null 2>&1 &
fi
# bluealsa2 is stock's codec wrapper, including our existing AAC patch.
if ! pidof bluealsa >/dev/null; then
    bluealsa2 >/dev/null 2>&1 &
fi
# D-Bus calls have their own deadline; never scan or pair.
path=/org/bluez/hci0/dev_$(printf '%s' "$mac" | tr ':' '_')
property() {
    dbus-send --system --print-reply --reply-timeout=5000 --dest=org.bluez \
        "$path" org.freedesktop.DBus.Properties.Get \
        string:org.bluez.Device1 string:"$1" >"$reply" 2>/dev/null &
    child=$!; wait "$child"; child=
    grep -q 'boolean true' "$reply"
}
for i in 1 2 3 4 5 6 7 8 9 10; do
    property Paired && break
    [ "$i" = 10 ] && exit 0
    pause 1
done
for attempt in 1 2 3 4; do
    # Preserve any existing headset connection, including a different headset.
    hcitool con 2>/dev/null | grep -Eq '([[:xdigit:]]{2}:){5}[[:xdigit:]]{2}' && exit 0
    property Paired || exit 0
    dbus-send --system --print-reply --reply-timeout=15000 --dest=org.bluez \
        "$path" org.bluez.Device1.Connect >/dev/null 2>&1 &
    child=$!; wait "$child"; child=
    property Connected && exit 0
    [ "$attempt" = 4 ] || pause 20
done
