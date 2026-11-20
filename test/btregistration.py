#!/usr/bin/env python3
"""Actual helper reconciliation on a private bus; deterministic delayed-owner ordering."""
import json
import os
import pathlib
import subprocess
import tempfile
import time

ROOT=pathlib.Path(__file__).resolve().parents[1]
namespace={'__file__':str(ROOT/'test/mpris.py')}
text=(ROOT/'test/mpris.py').read_text()
exec(compile(text[:text.index("with tempfile.TemporaryDirectory(prefix='q2mpris-')")],str(ROOT/'test/mpris.py'),'exec'),namespace)
fake=namespace['FAKE'].replace("out(event='ready')", "out(event='ready', owner=bus.get_unique_name())")
C=r'''
#include <dbus/dbus.h>
static const char *failure;
static unsigned sync_calls;
static DBusMessage *test_block(DBusConnection *c,DBusMessage *m,int t,DBusError *e){
    sync_calls++;
    if(failure){if(*failure)dbus_set_error_const(e,failure,"fixture error");return 0;}
    return dbus_connection_send_with_reply_and_block(c,m,t,e);
}
#define dbus_connection_send_with_reply_and_block test_block
#define main helper_main
#include "mpris.c"
#undef main
#undef dbus_connection_send_with_reply_and_block
#include <assert.h>
static void owner_up(const char *owner){
    DBusMessage *m=dbus_message_new_signal(DBUS_PATH_DBUS,DBUS_INTERFACE_DBUS,"NameOwnerChanged");
    const char *old="";assert(m);dbus_message_set_sender(m,DBUS_SERVICE_DBUS);
    dbus_message_append_args(m,DBUS_TYPE_STRING,&bluez_name,DBUS_TYPE_STRING,&old,DBUS_TYPE_STRING,&owner,DBUS_TYPE_INVALID);
    on_signal(conn,m,0);dbus_message_unref(m);
}
static void other_player(DBusConnection *c,const char *path){
    DBusMessage *m=dbus_message_new_method_call(bluez_name,adapter_path,MEDIA_IFACE,"RegisterPlayer");
    DBusMessageIter a,d;dbus_message_iter_init_append(m,&a);dbus_message_iter_append_basic(&a,DBUS_TYPE_OBJECT_PATH,&path);
    dbus_message_iter_open_container(&a,DBUS_TYPE_ARRAY,"{sv}",&d);append_properties(&d,1);dbus_message_iter_close_container(&a,&d);
    DBusError error;dbus_error_init(&error);DBusMessage *r=dbus_connection_send_with_reply_and_block(c,m,2000,&error);
    assert(r&&!dbus_error_is_set(&error));dbus_message_unref(r);dbus_message_unref(m);
}
int main(int argc,char **argv){
    assert(argc==2);
    snprintf(rec.status,sizeof rec.status,"Paused");snprintf(rec.title,sizeof rec.title,"Initial");rec.generation=1;
    assert(bm_connect()&&registered);
    /* A newer record was read before the delayed notification; duplicate error
     * must republish it fully, not pretend registration parsed the dictionary. */
    snprintf(rec.title,sizeof rec.title,"Latest at reconciliation");rec.generation=2;
    owner_up(argv[1]);assert(registered);
    snprintf(rec.title,sizeof rec.title,"Later title");snprintf(rec.status,sizeof rec.status,"Playing");rec.position_us=19000000;rec.generation=3;
    bm_changed(1);bm_changed(0);dbus_connection_flush(conn);
    /* Only the exact named error reconciles; generic/timeout/missing replies fail. */
    const char *errors[]={"org.bluez.Error.Failed","org.freedesktop.DBus.Error.NoReply","org.example.AlreadyExists",""};
    for(unsigned i=0;i<4;i++){registered=0;failure=errors[i];assert(!bm_register()&&!registered);}
    failure=0;assert(bm_register()&&registered);
    unsigned before=sync_calls;assert(!bm_register()&&registered&&sync_calls==before);
    /* A late Release still invalidates local state, then the same owned player
     * is recoverable through normal bounded retry. No exception hides Release. */
    DBusMessage *release=dbus_message_new_method_call(dbus_bus_get_unique_name(conn),PLAYER_PATH,PLAYER_IFACE,"Release");
    assert(release);dbus_message_set_sender(release,argv[1]);dbus_message_set_serial(release,91);
    on_message(conn,release,0);dbus_message_unref(release);assert(!registered);assert(bm_register()&&registered);
    /* Same path from a different unique connection, and different path on this
     * connection, are independent registrations, never ownership adoption. */
    DBusError error;dbus_error_init(&error);DBusConnection *other=dbus_bus_get_private(DBUS_BUS_SESSION,&error);
    assert(other);dbus_connection_set_exit_on_disconnect(other,FALSE);other_player(other,PLAYER_PATH);other_player(conn,"/q2pod/other");
    dbus_connection_flush(conn);usleep(100000);
    printf("{\"registered\":%d,\"exact_error_only\":true,\"full_republish\":true,\"release_recovery\":true,\"foreign_keys\":true}\n",registered);
    dbus_connection_close(other);dbus_connection_unref(other);dbus_connection_close(conn);dbus_connection_unref(conn);return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='q2-registration-') as tmp:
    d=pathlib.Path(tmp);(d/'test.c').write_text(C)
    flags=subprocess.check_output(['pkg-config','--cflags','--libs','dbus-1'],text=True).split()
    subprocess.run(['cc','-std=gnu99','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-I',str(ROOT/'patch'),str(d/'test.c'),'-o',str(d/'test'),*flags],check=True)
    bus=subprocess.Popen(['dbus-daemon','--session','--nofork','--print-address=1'],stdout=subprocess.PIPE,text=True)
    address=bus.stdout.readline().strip()
    env=dict(os.environ,DBUS_SESSION_BUS_ADDRESS=address,DBUS_SYSTEM_BUS_ADDRESS=address)
    service=subprocess.Popen(['/usr/bin/python3','-c',fake,'org.bluez'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,text=True)
    ready=json.loads(service.stdout.readline());assert ready['event']=='ready'
    try:
        result=subprocess.run([str(d/'test'),ready['owner']],env=env,capture_output=True,text=True,check=True)
        time.sleep(.1);service.terminate();output,error=service.communicate(timeout=5)
        events=[json.loads(line) for line in output.splitlines()]
        changes=[e.get('changed',{}) for e in events if e['event']=='PropertiesChanged']
        titles=[e.get('Metadata',{}).get('xesam:title') for e in changes]
        assert 'Latest at reconciliation' in titles and 'Later title' in titles
        assert any(e.get('PlaybackStatus')=='Playing' for e in changes)
        assert any(e.get('Position',0)>=19000000 for e in changes)
        registrations=[e for e in events if e['event']=='RegisterPlayer']
        assert len(registrations)==3 and len({e['sender'] for e in registrations})==2
        assert any(e['path']=='/q2pod/other' for e in registrations)
        assert sum(e['event']=='AlreadyExists' for e in events)==3
        assert not error
        print(result.stdout.strip())
        print('Private-bus delayed owner-up: full latest and later metadata/status/position, exact error/no-reply refusal, registered guard, late Release recovery, foreign connection/path keys passed.')
    finally:
        if service.poll() is None:service.kill();service.wait()
        bus.terminate();bus.wait()
