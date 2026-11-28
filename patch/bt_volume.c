/* Bluetooth's volume for each device: the level saved and loaded under the device that plays. */
#include "navigation.h"

/* Bluetooth keeps a level for each device, under Q2POD BTV and its address (headset_volume_key),
 * through navigation.c's volume save (vsave) and output change (ringnav_output). btv.key is the
 * device whose level g_volume holds, "" before one is known. A device with no level of its own
 * yet, or not known yet, starts at the lower of PLAYSET BT_VOLUME (every device's one level until
 * 1.9.6, still saved while no device is known) and the wired level, so it is never louder than
 * either. Default Volume stays the boot's, wired, as before: a device connecting after the boot
 * takes its own level.
 *
 * ponytail: a key for every device ever connected, never removed (about 20 bytes of config.ini
 * each). Inferred from stock's callers, not seen on a Q2: the device is in the link list by the
 * time stock moves the output to it (handleBluetoothLink, checkBluetoothStatus); if it isn't,
 * the lower level plays until bt_device_poll's next look, at most 500 ms. */
static struct {
    char key[16];
    unsigned at; /* bt_device_poll's last look */
} btv __attribute__((section(".scratch")));

const char *bt_volume_key(void) { return btv.key; }

void bt_volume_device(void) { headset_volume_key(btv.key); }

/* The saved level of output way (1: Bluetooth, btv.key's device), def if none, in Max Volume. */
int output_volume(int way, int def) {
    int wired = config_value("PLAYSET", "VOLUME", 101, def), v = wired;
    if (way == 1) {
        int shared = config_value("PLAYSET", "BT_VOLUME", 101, wired);
        v = btv.key[0] ? config_value("Q2POD", btv.key, 101, -1) : -1;
        if (v < 0) v = shared < wired ? shared : wired;
    }
    return v > g_maxvolume ? g_maxvolume : v;
}

/* Another Bluetooth device, or the one that plays first known, with the output left as it was
 * (ringnav_output loads a level only as Bluetooth comes or goes): its own level, the last
 * device's held save written first. Every 500 ms while Bluetooth plays, not while a speaker casts
 * (airplay.c gives the level back at its end; the next look loads the device's if it changed). */
void bt_device_poll(void) {
    unsigned now = time_now_ms();
    if (now - btv.at < 500 || mclGetOutputWay() != 1 || airplay_on()) return;
    btv.at = now;
    char key[16];
    headset_volume_key(key);
    if (!key[0] || !tk_strcmp(key, btv.key)) return;
    volume_save_flush();
    memcpy(btv.key, key, sizeof key);
    g_volume = (unsigned char)output_volume(1, g_volume);
    headset_volume_reset();
    device_set_volume(g_volume, 1);
}
