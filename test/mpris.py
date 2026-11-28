#!/usr/bin/env python3
"""Optional private-bus metadata check (cc, libdbus, dbus-daemon, Python dbus/gi)."""
import fcntl
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
FAKE = r'''
import json, sys, dbus, dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
DBusGMainLoop(set_as_default=True)
bus = dbus.SessionBus()
def plain(v):
    if isinstance(v, dict): return {str(k):plain(x) for k,x in v.items()}
    if isinstance(v, (list,tuple)): return [plain(x) for x in v]
    return int(v) if isinstance(v,(dbus.Int64,dbus.Int32)) else str(v)
def out(event, props={}): print(json.dumps([event,plain(props)]),flush=True)
class Media(dbus.service.Object):
    @dbus.service.method('org.bluez.Media1', in_signature='oa{sv}', sender_keyword='sender')
    def RegisterPlayer(self, path, props, sender=None):
        out('register',props)
        bus.add_signal_receiver(lambda i,c,v:out('change',c), 'PropertiesChanged',
                                'org.freedesktop.DBus.Properties',sender,path)
    @dbus.service.method('org.bluez.Media1', in_signature='o')
    def UnregisterPlayer(self,path): out('unregister')
media=Media(bus,'/org/bluez/hci0')
name=dbus.service.BusName('org.bluez',bus)
out('ready')
GLib.MainLoop().run()
'''


def event(proc, kind, timeout=3):
    assert select.select([proc.stdout], [], [], timeout)[0], kind
    got, props = json.loads(proc.stdout.readline())
    assert got == kind, (kind, got, props)
    return props


def record(path, status='Playing', position=1000, title='日本語'.encode()):
    """A record as patch/btmeta.c writes it (test/fw/test_btmeta.py), renamed into place."""
    text = (b'status=%s\ntitle=%s\nartist=Someone\nalbum=Album\ngenre=Pop\nduration=200000\ntrack=3\n'
            b'position=%d\nnow=%d\n' % (status.encode(), title, position, int(time.monotonic()*1000) & 0xffffffff))
    tmp = path.with_suffix('.tmp')
    tmp.write_bytes(text)
    tmp.replace(path)


def main():
    with tempfile.TemporaryDirectory(prefix='q2mpris-') as tmp:
        d = Path(tmp)
        subprocess.run(['cc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', str(ROOT/'patch/mpris.c'),
                        '-o', str(d/'helper'), '-l:libdbus-1.so.3'], check=True)
        with open('/tmp/q2-mpris-tests.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = Path('/tmp/q2-bt/nowplaying')
            made = not path.parent.exists()
            path.parent.mkdir(mode=0o700, exist_ok=True)
            assert not path.parent.is_symlink() and not path.is_symlink()
            prior = path.read_bytes() if path.exists() else None
            bus = subprocess.Popen(['dbus-daemon', '--session', '--nofork', '--print-address=1'],
                                   stdout=subprocess.PIPE, text=True)
            address = bus.stdout.readline().strip()
            env = dict(os.environ, DBUS_SESSION_BUS_ADDRESS=address, DBUS_SYSTEM_BUS_ADDRESS=address)
            fake = helper = None
            try:
                path.unlink(missing_ok=True)
                fake = subprocess.Popen([sys.executable, '-c', FAKE], env=env,
                                        stdout=subprocess.PIPE, bufsize=0)
                event(fake, 'ready')
                helper = subprocess.Popen([str(d/'helper')], env=env)
                assert not select.select([fake.stdout], [], [], .1)[0]
                record(path)
                props = event(fake, 'register')
                assert props['Metadata']['xesam:title'] == '日本語'
                record(path, 'Paused', 2000)
                props = event(fake, 'change')
                assert props['PlaybackStatus'] == 'Paused' and props['Position'] == 2000000
                assert 'Metadata' not in props
                record(path, 'Paused', 2500, b'bad\xff')
                assert not select.select([fake.stdout], [], [], .1)[0]
                record(path, 'Paused', 3000)
                assert event(fake, 'change')['Position'] == 3000000
                fake.kill(); fake.wait()
                fake = subprocess.Popen([sys.executable, '-c', FAKE], env=env,
                                        stdout=subprocess.PIPE, bufsize=0)
                event(fake, 'ready')
                props = event(fake, 'register')
                assert props['PlaybackStatus'] == 'Paused' and props['Position'] == 3000000
                helper.terminate()
                event(fake, 'unregister')
                assert helper.wait(timeout=3) == 0
                print('mpris: metadata, UTF-8 rejection, status/seek, owner return and shutdown passed')
            finally:
                for proc in (helper, fake, bus):
                    if proc and proc.poll() is None: proc.kill(); proc.wait()
                if prior is None: path.unlink(missing_ok=True)
                else: path.write_bytes(prior)
                path.with_suffix('.tmp').unlink(missing_ok=True)
                if made: path.parent.rmdir()


if __name__ == '__main__':
    main()
