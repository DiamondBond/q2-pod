#!/usr/bin/env python3
"""q2mpris (patch/mpris.c) on the host: a private session bus, a fake org.bluez with the Media1
RegisterPlayer/UnregisterPlayer methods, and the helper built natively against the host's libdbus.
Checks registration, update ordering, UTF-8 bounds, recovery and rejected controls.
Requires dbus-daemon, Python dbus/gi and libdbus-1-dev. `python test/mpris.py` from the repo root."""
import ast, contextlib, fcntl, json, os, pathlib, select, signal, subprocess, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
FAKE = r'''
import json, sys, dbus, dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
DBusGMainLoop(set_as_default=True)
bus = dbus.SessionBus()
controls=[]
def inspect_message(bus, message):
    if message.get_type() == dbus.lowlevel.MESSAGE_TYPE_METHOD_CALL and message.get_member() in ('Acquire','TryAcquire','Release','Connect','Disconnect','Set','Start','Stop','Play','Pause'):
        controls.append(message.get_member())
    return dbus.lowlevel.HANDLER_RESULT_NOT_YET_HANDLED
bus.add_message_filter(inspect_message)
def out(**kw): print(json.dumps(kw), flush=True)
class Media(dbus.service.Object):
    players = set()
    @dbus.service.method('org.bluez.Media1', in_signature='oa{sv}', sender_keyword='sender')
    def RegisterPlayer(self, path, props, sender=None):
        key = (sender, str(path))
        if key in self.players:
            out(event='AlreadyExists', path=str(path), sender=sender)
            raise dbus.exceptions.DBusException('already registered', name='org.bluez.Error.AlreadyExists')
        self.players.add(key)
        out(event='RegisterPlayer', path=str(path), props=plain(props), sender=sender)
        bus.add_signal_receiver(lambda i, c, inv, **k: out(event='PropertiesChanged', iface=str(i), changed=plain(c)),
                                'PropertiesChanged', 'org.freedesktop.DBus.Properties', sender, path)
        self.player = (sender, path)
    @dbus.service.method('org.bluez.Media1', in_signature='o', sender_keyword='sender')
    def UnregisterPlayer(self, path, sender=None):
        self.players.discard((sender, str(path)))
        out(event='UnregisterPlayer', path=str(path))
def plain(v):
    if isinstance(v, dict): return {str(k): plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)): return [plain(x) for x in v]
    if isinstance(v, (dbus.Int64, dbus.Int32, dbus.UInt32)): return int(v)
    return str(v) if not isinstance(v, bool) else v
media = Media(bus, '/org/bluez/hci0')
name = dbus.service.BusName(sys.argv[1], bus)
out(event='ready')
def command(fd, cond):
    line = sys.stdin.readline()
    if not line: GLib.MainLoop().quit(); return False
    sender, path = media.player
    obj = bus.get_object(sender, path)
    what = line.strip()
    try:
        if what == 'controls': out(event='reply', what=what, value=controls)
        elif what == 'introspect': out(event='reply', what=what, value=str(obj.Introspect(dbus_interface='org.freedesktop.DBus.Introspectable')))
        elif what == 'getall': out(event='reply', what=what, value=plain(obj.GetAll('org.mpris.MediaPlayer2.Player', dbus_interface='org.freedesktop.DBus.Properties')))
        elif what == 'get': out(event='reply', what=what, value=plain(obj.Get('org.mpris.MediaPlayer2.Player', 'Metadata', dbus_interface='org.freedesktop.DBus.Properties')))
        elif what == 'get-wrong-interface': out(event='reply', what=what, value=plain(obj.Get('org.example.Other', 'Metadata', dbus_interface='org.freedesktop.DBus.Properties')))
        elif what == 'getall-wrong-interface': out(event='reply', what=what, value=plain(obj.GetAll('org.example.Other', dbus_interface='org.freedesktop.DBus.Properties')))
        elif what == 'get-bad-args': out(event='reply', what=what, value=plain(bus.call_blocking(sender, path, 'org.freedesktop.DBus.Properties', 'Get', 's', ('org.mpris.MediaPlayer2.Player',))))
        elif what == 'getall-bad-args': out(event='reply', what=what, value=plain(bus.call_blocking(sender, path, 'org.freedesktop.DBus.Properties', 'GetAll', 'ss', ('org.mpris.MediaPlayer2.Player', 'Metadata'))))
        elif what == 'play': out(event='reply', what=what, value=plain(obj.Play(dbus_interface='org.mpris.MediaPlayer2.Player')))
    except dbus.exceptions.DBusException as e: out(event='reply', what=what, error=e.get_dbus_name())
    return True
GLib.io_add_watch(sys.stdin.fileno(), GLib.IO_IN, command)
GLib.MainLoop().run()
'''

def record(path, gen, title='A Song', artist='Someone', album='An Album', status='Playing', position=0, duration=200000):
    text = f'v=1\nstatus={status}\ntitle={title}\nartist={artist}\nalbum={album}\ngenre=Pop\nduration={duration}\ntrack=3\ntracks=12\nfile=song.flac\nposition={position}\ngen={gen}\n'
    tmp = path.with_suffix('.tmp'); tmp.write_text(text); os.replace(tmp, path)

@contextlib.contextmanager
def shipping_record():
    """Serialize default-path tests and restore any prior RAM snapshot."""
    with open('/tmp/q2-mpris-tests.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = pathlib.Path('/tmp/q2-bt/nowplaying')
        made = not path.parent.exists()
        path.parent.mkdir(mode=0o700, exist_ok=True)
        assert not path.parent.is_symlink() and not path.is_symlink()
        prior = path.read_bytes() if path.exists() else None
        try:
            yield path
        finally:
            if prior is None: path.unlink(missing_ok=True)
            else: path.write_bytes(prior)
            path.with_suffix('.tmp').unlink(missing_ok=True)
            if made: path.parent.rmdir()

def start_publisher(executable, env, transport=None):
    """Use the production supervisor, adapting its executable and host mount check.

    Container /tmp need not be tmpfs. This exercises the exact wait/restart/exit-2
    lifecycle, not target startup mount provenance (separately checked on stock).
    """
    tree = ast.parse((ROOT/'tools/build.py').read_text())
    startup = next(ast.literal_eval(n.value)[1].decode() for n in tree.body
                   if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id=='MPRIS_START' for t in n.targets))
    script = startup[:startup.index('        while :; do\n            /release/bin/demo')]
    assert script.rstrip().endswith('done) &')
    script = script.rstrip()[:-1]
    script = script.replace("grep -q ' /tmp tmpfs ' /proc/mounts", 'true')
    import shlex
    if transport is not None: script = script.replace('/tmp/q2-bt', shlex.quote(str(transport)))
    script = script.replace('/usr/bin/q2mpris', shlex.quote(str(executable)))
    return subprocess.Popen(['/bin/sh','-c',script], env=env, stderr=subprocess.PIPE,
                            text=True, start_new_session=True)

def stop_publisher(p):
    if p.poll() is None: os.killpg(p.pid, signal.SIGTERM)
    p.wait(timeout=3)

class Fake:
    def __init__(self, env, name):
        self.p = subprocess.Popen([sys.executable, '-c', FAKE, name], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        assert self.wait('ready')
    def wait(self, event, timeout=5, **match):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if not select.select([self.p.stdout], [], [], max(0, end - time.monotonic()))[0]: return None
            line = self.p.stdout.readline()
            if not line: return None
            e = json.loads(line)
            if e.get('event') == event and all(e.get(k) == v for k, v in match.items()): return e
        return None
    def ask(self, what):
        self.p.stdin.write(what + '\n'); self.p.stdin.flush(); return self.wait('reply', what=what)
    def stop(self):
        self.p.kill(); self.p.wait()


with tempfile.TemporaryDirectory(prefix='q2mpris-') as tmp, shipping_record() as rec:
    d = pathlib.Path(tmp)
    cflags = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'dbus-1'], text=True).split()
    subprocess.run(['cc','-std=gnu99','-Wall','-Wextra','-Werror','-Wno-unused-parameter',str(ROOT/'patch/mpris.c'),'-o',str(d/'q2mpris'),*cflags],check=True)
    def start_bus():
        p = subprocess.Popen(['dbus-daemon','--session','--nofork','--print-address=1','--address=unix:path='+str(d/'bus')],stdout=subprocess.PIPE,text=True)
        address = p.stdout.readline().strip().split(',guid=')[0]
        return p,dict(os.environ,DBUS_SESSION_BUS_ADDRESS=address,DBUS_SYSTEM_BUS_ADDRESS=address)
    bus,env = start_bus()
    helper = fake = None
    def start_helper():
        return start_publisher(d/'q2mpris', env)
    try:
        rec.unlink(missing_ok=True)
        fake = Fake(env,'org.bluez')
        helper = start_helper()
        assert fake.wait('RegisterPlayer',timeout=0.6) is None
        fake.stop(); fake=Fake(env,'org.bluez')
        assert fake.wait('RegisterPlayer',timeout=0.6) is None  # owner return cannot invent a record
        rec.write_text('v=1\nstatus=Paused\ntitle=Malformed\nposition=0\n')
        assert fake.wait('RegisterPlayer',timeout=0.6) is None
        record(rec,1,title='First valid paused',status='Paused',position=12000)
        first=fake.wait('RegisterPlayer')['props']
        assert first['Metadata']['xesam:title']=='First valid paused' and first['PlaybackStatus']=='Paused'
        stop_publisher(helper); helper=None
        record(rec,2,title='',artist='',album='',status='Stopped',position=0,duration=0)
        helper=start_helper()
        first=fake.wait('RegisterPlayer')['props']
        assert first['Metadata']['xesam:title']=='' and first['PlaybackStatus']=='Stopped'
        stop_publisher(helper); helper=None
        rec.write_text('malformed at cold start\n')
        helper=start_helper()
        assert fake.wait('RegisterPlayer',timeout=0.6) is None
        record(rec,1)
        reg = fake.wait('RegisterPlayer'); assert reg and reg['path']=='/q2pod/player',reg
        props = reg['props']; meta=props['Metadata']
        assert meta['xesam:title']=='A Song' and meta['xesam:artist']==['Someone'] and meta['xesam:album']=='An Album'
        assert meta['mpris:length']==200000000 and props['PlaybackStatus']=='Playing'
        assert not any(k.startswith('Can') for k in props)
        record(rec,1,title='Next Song',position=5000,status='Paused')  # producer restarted, same generation
        ch=fake.wait('PropertiesChanged'); assert ch and ch['changed']['Metadata']['xesam:title']=='Next Song',ch
        assert ch['changed']['Position']==5000000 and ch['changed']['PlaybackStatus']=='Paused'
        keys=list(ch['changed']); assert keys.index('Metadata')<keys.index('Position')
        record(rec,1,title='Next Song',position=5000,status='Paused')
        assert fake.wait('PropertiesChanged',timeout=0.6) is None  # exact complete text still deduplicates
        record(rec,3,title='Next Song',position=5000,status='Playing')
        ch=fake.wait('PropertiesChanged'); assert ch and 'Metadata' not in ch['changed'],ch
        time.sleep(2.2)
        reply=fake.ask('getall'); assert 7000000<=reply['value']['Position']<=9000000,reply
        rec.write_text('garbage\n'); assert fake.wait('PropertiesChanged',timeout=0.6) is None
        torn=b'v=1\nstatus=Playing\ntitle='+b'A'*198+b'\xe2\nartist=\xff\xfeBad\nalbum=Ok\ngenre=\ntrack=1\ntracks=1\nduration=1\nfile=f\nposition=0\ngen=5\n'
        rec.write_bytes(torn)
        ch=fake.wait('PropertiesChanged'); assert ch['changed']['Metadata']['xesam:title']=='A'*198+'?'
        assert ch['changed']['Metadata']['xesam:artist']==['??Bad']
        for text in ('v=1\nstatus=Playing\ntitle=No gen\nposition=1\n','v=1\nstatus=Playing\ntitle=Junk\nduration=12abc\nposition=0\ngen=99\n'):
            rec.write_text(text); assert fake.wait('PropertiesChanged',timeout=0.6) is None
        valid = 'v=1\nstatus=Paused\ntitle=Rejected\nposition=0\ngen=99\n'
        for text in (valid+'title=Duplicate\n', valid.replace('gen=99', 'gen=4294967296'),
                     valid+'track=2147483648\n', valid+'duration=1000000001\n',
                     valid+'now=4294967296\n', valid.rstrip('\n'), valid+'\0title=Hidden\n'):
            rec.write_text(text); assert fake.wait('PropertiesChanged',timeout=0.6) is None
        assert fake.ask('get')['value']['xesam:title']=='A'*198+'?'
        record(rec,8,title='A|B',artist='C'); assert fake.wait('PropertiesChanged')
        record(rec,9,title='A',artist='B|C'); ch=fake.wait('PropertiesChanged')
        assert ch['changed']['Metadata']['xesam:title']=='A' and ch['changed']['Metadata']['xesam:artist']==['B|C']
        stamp=(int(time.monotonic()*1000)-3000)&0xffffffff
        rec.write_text(f'v=1\nstatus=Playing\ntitle=Stamped\nduration=200000\nnow={stamp}\nposition=5000\ngen=10\n')
        assert 7900000<=fake.wait('PropertiesChanged')['changed']['Position']<=9500000
        for what in ('introspect','getall','get'):
            r=fake.ask(what); assert r and 'error' not in r,r
        assert fake.ask('get')['value']==fake.ask('getall')['value']['Metadata']
        for what in ('get-wrong-interface', 'getall-wrong-interface'):
            assert fake.ask(what)['error']=='org.freedesktop.DBus.Error.UnknownInterface'
        for what in ('get-bad-args', 'getall-bad-args'):
            assert fake.ask(what)['error']=='org.freedesktop.DBus.Error.InvalidArgs'
        assert fake.ask('play')['error']=='org.freedesktop.DBus.Error.NotSupported'
        record(rec,11,title='Latest before owner return'); assert fake.wait('PropertiesChanged')
        fake.stop(); fake=Fake(env,'org.bluez')
        assert fake.wait('RegisterPlayer')['props']['Metadata']['xesam:title']=='Latest before owner return'
        record(rec,12,title='After owner restart'); assert fake.wait('PropertiesChanged')['changed']['Metadata']['xesam:title']=='After owner restart'
        fake.stop(); fake=None
        bus.kill(); bus.wait(); time.sleep(0.5); assert helper.poll() is None
        record(rec,13,title='Quiet while bus absent',status='Paused',position=12345)
        time.sleep(2.2)  # beyond one capped retry; no later write may be needed for recovery
        bus,env=start_bus(); fake=Fake(env,'org.bluez')
        restored=fake.wait('RegisterPlayer',timeout=6)['props']
        assert restored['Metadata']['xesam:title']=='Quiet while bus absent' and restored['Position']==12345000,restored
        record(rec,13,title='After bus restart'); assert fake.wait('PropertiesChanged')['changed']['Metadata']['xesam:title']=='After bus restart'
        # Same absolute monotonic stamp still projects correctly after helper restart.
        stamp=(int(time.monotonic()*1000)-3000)&0xffffffff
        rec.write_text(f'v=1\nstatus=Playing\ntitle=Old Playing\nduration=200000\nnow={stamp}\nposition=5000\ngen=14\n')
        assert fake.wait('PropertiesChanged')
        stop_publisher(helper); helper=start_helper()
        p=fake.wait('RegisterPlayer')['props']; assert p['Metadata']['xesam:title']=='Old Playing' and 7900000<=p['Position']<=11000000,p
        print('mpris: registration, metadata/status ordering, UTF-8/torn fields, property reads, refused controls, owner/quiet-bus recovery with fresh initial state and old-record helper restart passed.')
    finally:
        if fake: fake.stop()
        if helper: stop_publisher(helper)
        bus.terminate(); bus.wait(timeout=3)
