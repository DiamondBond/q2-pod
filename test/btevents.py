#!/usr/bin/env python3
"""Real helper notifications, quiet idle, interface recovery and fail-closed setup.

The counting wrappers exist only in this separate test binary. No firmware/device access.
"""
import json
import os
import pathlib
import shlex
import subprocess
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
namespace = {'__file__': str(ROOT/'test/mpris.py')}
text = (ROOT/'test/mpris.py').read_text()
exec(compile(text[:text.index("with tempfile.TemporaryDirectory(prefix='q2mpris-')")],
             str(ROOT/'test/mpris.py'), 'exec'), namespace)
Fake, record = namespace['Fake'], namespace['record']
namespace['FAKE'] = namespace['FAKE'].replace("    sender, path = media.player", '''    what = line.strip()
    if what in ('remove', 'add'):
        member = 'InterfacesRemoved' if what == 'remove' else 'InterfacesAdded'
        message = dbus.lowlevel.SignalMessage('/', 'org.freedesktop.DBus.ObjectManager', member)
        if what == 'remove':
            media.remove_from_connection()
            media.players.clear()
            message.append(dbus.ObjectPath('/org/bluez/hci0'), dbus.Array(['org.bluez.Media1'], signature='s'), signature='oas')
        else:
            media.add_to_connection(bus, '/org/bluez/hci0')
            message.append(dbus.ObjectPath('/org/bluez/hci0'), dbus.Dictionary({'org.bluez.Media1':dbus.Dictionary({}, signature='sv')}, signature='sa{sv}'), signature='oa{sa{sv}}')
        bus.send_message(message)
        out(event='reply', what=what)
        return True
    sender, path = media.player''')
namespace['FAKE'] = namespace['FAKE'].replace('import json, sys, dbus, dbus.service',
                                            'import json, sys, os, dbus, dbus.service')
namespace['FAKE'] = namespace['FAKE'].replace('        key = (sender, str(path))', '''        scenario = os.environ.get('Q2_RETRY_SCENARIO')
        self.attempts = getattr(self, 'attempts', 0) + 1
        if scenario == 'final-error' and self.attempts <= 3:
            if self.attempts == 3:
                signal = dbus.lowlevel.SignalMessage('/', 'org.freedesktop.DBus.ObjectManager', 'InterfacesAdded')
                signal.append(dbus.ObjectPath('/org/bluez/hci0'), dbus.Dictionary({'org.bluez.Media1':dbus.Dictionary({}, signature='sv')}, signature='sa{sv}'), signature='oa{sa{sv}}')
                bus.send_message(signal)
                bus.flush()
            raise dbus.exceptions.DBusException('not ready', name='org.bluez.Error.Failed')
        if scenario == 'success-queue' and self.attempts == 1:
            raise dbus.exceptions.DBusException('not ready', name='org.bluez.Error.Failed')
        if scenario == 'success-queue' and self.attempts == 2:
            release = dbus.lowlevel.MethodCallMessage(sender, path, 'org.mpris.MediaPlayer2.Player', 'Release')
            bus.send_message_with_reply(release, lambda reply: out(event='queued-release', type=reply.get_type()), timeout_s=2)
            getall = dbus.lowlevel.MethodCallMessage(sender, path, 'org.freedesktop.DBus.Properties', 'GetAll')
            getall.append('org.mpris.MediaPlayer2.Player', signature='s')
            bus.send_message_with_reply(getall, lambda reply: out(event='queued-properties', type=reply.get_type()), timeout_s=2)
            bus.flush()
        key = (sender, str(path))''')

C = r'''
#include <dbus/dbus.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/inotify.h>
#include <unistd.h>
static void count(const char *kind,int value){
    static unsigned calls;
    if(++calls>4096)_exit(99);
    const char *path=getenv("Q2_EVENT_TRACE");
    if(path){FILE *f=fopen(path,"a");if(f){fprintf(f,"%s %d\n",kind,value);fclose(f);}}
}
static int counted_open(const char *path,int flags){count("open",0);return open(path,flags);}
static int counted_poll(struct pollfd *fds,nfds_t n,int timeout){count("poll",timeout);return poll(fds,n,timeout);}
static DBusMessage *test_sync(DBusConnection *c,DBusMessage *m,int t,DBusError *e){
    DBusMessage *reply=dbus_connection_send_with_reply_and_block(c,m,t,e);
    if(getenv("Q2_RETRY_SCENARIO"))count("queued",dbus_connection_get_dispatch_status(c)==DBUS_DISPATCH_DATA_REMAINS);
    return reply;
}
static int test_notify(int flags){if(getenv("Q2_NO_NOTIFY")){errno=ENOSYS;return -1;}return inotify_init1(flags);}
#define open counted_open
#define poll counted_poll
#define inotify_init1 test_notify
#define dbus_connection_send_with_reply_and_block test_sync
#define main helper_main
#include "mpris.c"
#undef main
#include <assert.h>
int main(int argc,char **argv){
    if(argc==2&&!strcmp(argv[1],"unit")){
        struct bm_event event={.mask=IN_Q_OVERFLOW};
        assert(notification_events((char*)&event,sizeof event)==1);
        event.mask=IN_IGNORED;assert(notification_events((char*)&event,sizeof event)==-1);
        event.mask=IN_DELETE_SELF;assert(notification_events((char*)&event,sizeof event)==-1);
        event.mask=0;event.len=999;assert(notification_events((char*)&event,sizeof event)==-1);
        DBusWatch *dummy=(DBusWatch*)1;
        for(unsigned i=0;i<BUS_SLOTS;i++)assert(add_watch(dummy,0));
        assert(!add_watch(dummy,0));remove_watch(dummy,0);
        for(unsigned i=0;i<BUS_SLOTS;i++)assert(!bus_watches[i]);
        return 0;
    }
    if(argc==2&&!strcmp(argv[1],"oom")){message_space(FALSE);return 9;}
    assert(argc==3);
    record_path=argv[1];record_dir=argv[2];record_leaf="record";
    return helper_main();
}
'''

with tempfile.TemporaryDirectory(prefix='q2-events-') as tmp:
    d = pathlib.Path(tmp)
    (d/'events.c').write_text(C)
    flags = subprocess.check_output(['pkg-config','--cflags','--libs','dbus-1'],text=True).split()
    common = ['cc','-std=gnu99','-Wall','-Wextra','-Werror','-Wno-unused-parameter',
              '-I'+str(ROOT/'patch')]
    subprocess.run([*common,str(d/'events.c'),'-o',str(d/'helper'),*flags],check=True)
    subprocess.run([str(d/'helper'),'unit'],check=True)
    assert subprocess.run([str(d/'helper'),'oom']).returncode == 1
    subprocess.run([*common,str(ROOT/'patch/mpris.c'),'-o',str(d/'production'),*flags],check=True)
    shipping = (d/'production').read_bytes()
    for removed in (b'--session',b'--record',b'--bluez',b'--off',b'q2pod-btmeta-off'):
        assert removed not in shipping, removed
    bus = subprocess.Popen(['dbus-daemon','--session','--nofork','--print-address=1'],stdout=subprocess.PIPE,text=True)
    address = bus.stdout.readline().strip()
    env = dict(os.environ,DBUS_SESSION_BUS_ADDRESS=address,DBUS_SYSTEM_BUS_ADDRESS=address,Q2_EVENT_TRACE=str(d/'trace'))
    transport = d/'transport'
    transport.mkdir(mode=0o700)
    rec = transport/'record'
    helper = fake = supervised = None

    def start_helper(extra=None):
        return subprocess.Popen([str(d/'helper'),str(rec),str(transport)],
                                env=dict(env,**(extra or {})),stderr=subprocess.PIPE,text=True)

    def trace():
        return (d/'trace').read_text().splitlines()

    def quiet(label):
        time.sleep(.15)
        before = trace()
        assert [line for line in before if line.startswith('poll ')][-1]=='poll -1',(label,before[-8:])
        time.sleep(.65)
        added = trace()[len(before):]
        assert not any(line.startswith('open ') for line in added),(label,added)
        assert len(added)<=1 and all(line=='poll -1' for line in added),(label,len(added),added[:8])
        active = supervised or helper
        assert active.poll() is None,(label,active.poll())

    try:
        record(rec,1,title='Initial',status='Paused')
        unavailable = start_helper({'Q2_NO_NOTIFY':'1'})
        _,error = unavailable.communicate(timeout=3)
        assert unavailable.returncode==2,error
        helper = start_helper()
        quiet('healthy bus, no BlueZ owner')
        fake = Fake(env,'org.bluez')
        assert fake.wait('RegisterPlayer')['props']['Metadata']['xesam:title']=='Initial'
        quiet('registered and paused')
        record(rec,2,title='Atomic rename',status='Paused',position=9000)
        changed = fake.wait('PropertiesChanged')
        assert changed['changed']['Metadata']['xesam:title']=='Atomic rename',changed
        assert changed['changed']['Position']==9000000,changed
        quiet('registered after notification')
        assert fake.ask('remove')
        time.sleep(.05)
        record(rec,3,title='While Media1 absent',status='Paused',position=17000)
        time.sleep(.1)
        assert fake.ask('add')
        restored = fake.wait('RegisterPlayer')['props']
        assert restored['Metadata']['xesam:title']=='While Media1 absent',restored
        assert restored['Position']==17000000,restored
        quiet('same owner, Media1 removed and restored')
        # Losing the watched directory must not leave an alive deaf publisher.
        moved = d/'transport-moved'
        transport.rename(moved)
        try:
            assert helper.wait(timeout=3)==1
        finally:
            moved.rename(transport)
        helper = start_helper()
        restored = fake.wait('RegisterPlayer')['props']
        assert restored['Metadata']['xesam:title']=='While Media1 absent',restored
        assert helper.poll() is None
        helper.terminate();helper.wait(timeout=3);helper=None
        launcher=d/'launch'
        launcher.write_text('#!/bin/sh\nexec '+shlex.join([str(d/'helper'),str(rec),str(transport)])+'\n')
        launcher.chmod(0o700)
        supervised=namespace['start_publisher'](launcher,env,transport)
        assert fake.wait('RegisterPlayer')['props']['Metadata']['xesam:title']=='While Media1 absent'
        # Actual loss differs from a rename: the supervisor can rebuild the directory,
        # but a fresh helper must not advertise its default empty record.
        rec.unlink();transport.rmdir()
        time.sleep(5.4)
        assert transport.is_dir() and not rec.exists()
        assert fake.wait('RegisterPlayer',timeout=.6) is None
        quiet('supervised restart waiting for lost snapshot')
        record(rec,4,title='Republished after loss',status='Paused',position=23000)
        restored=fake.wait('RegisterPlayer')['props']
        assert restored['Metadata']['xesam:title']=='Republished after loss' and restored['Position']==23000000
        namespace['stop_publisher'](supervised); supervised=None
        fake.stop(); fake=None
        # The synchronous reply can consume socket readiness while leaving other messages
        # queued. No producer write or command supplies a later, unrelated wakeup here.
        for scenario,queued_attempt in (('final-error',3),('success-queue',2)):
            trial_env=dict(env,Q2_RETRY_SCENARIO=scenario)
            before=len(trace())
            fake=Fake(trial_env,'org.bluez')
            helper=start_helper({'Q2_RETRY_SCENARIO':scenario})
            assert fake.wait('RegisterPlayer',timeout=5),scenario
            if scenario=='success-queue':
                assert fake.wait('queued-release')['type']==2
                assert fake.wait('queued-properties')['type']==2
                assert fake.wait('AlreadyExists'),scenario  # Release caused re-registration
            queued=[line for line in trace()[before:] if line.startswith('queued ')]
            assert len(queued)>=queued_attempt and queued[queued_attempt-1]=='queued 1',(scenario,queued)
            quiet('queued messages after '+scenario)
            helper.terminate();helper.wait(timeout=3);helper=None
            fake.stop();fake=None
        print('btevents: no idle file polls/timed wakes with absent owner or paused player; rename, Media1 recovery, overflow/invalidation, bounded slots, fail-fast OOM/setup and shipping flag removal passed.')
        print('Timed registration: final failed reply drains queued Media1 readiness; successful reply drains queued Release and property request without later producer/bus activity.')
    finally:
        if fake: fake.stop()
        if helper:
            if helper.poll() is None: helper.terminate()
            helper.wait(timeout=3)
        if supervised: namespace['stop_publisher'](supervised)
        bus.terminate();bus.wait(timeout=3)
