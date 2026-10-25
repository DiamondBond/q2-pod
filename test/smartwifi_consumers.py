#!/usr/bin/env python3
"""Execute the production consumer entry/worker functions with deterministic host seams."""
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]

def function(path, name):
    text = (ROOT / path).read_text()
    import re
    match = re.search(r"(?m)^(?:static )?(?:void \*|int |void )" + re.escape(name) + r"\(", text)
    assert match, (path, name)
    begin = text.index("{", match.start())
    depth = 1
    end = begin + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[match.start():end]

net = "\n".join(function("patch/netupdate.c", n) for n in
                ("wifi_wait", "worker", "online_click", "label_gone", "sh_worker",
                 "sh_start", "sh_closed"))
match = "\n".join(function("patch/onlinematch.c", n) for n in
                  ("match_ready", "ringnav_lyric_search", "ringnav_cover_search"))
addon = "\n".join(function("patch/addon.c", n) for n in
                  ("addon_wifi_busy", "launch_cancel", "launch", "poll_one", "addon_forget"))
preamble = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "smartwifi.h"
enum { NU_IDLE, NU_RUNNING, NU_DONE, NU_LATEST, NU_NET, NU_MISSING, NU_CARD, NU_CANCELLED };
enum { SH_OK, SH_NET, SH_SPACE, SH_CARD, SH_MISSING, SH_BAD, SH_CANCELLED, SH_BUSY };
enum { JOB_CHECK = 1, JOB_INSTALL, JOB_REMOVE, JOB_ERASE };
#define SPOT_DIR "/mock/spotify"
#define ADDON_POLL_MS 500
#define ADDON_START_MS 10000
typedef struct { char dir[24]; } shelf_app;
static shelf_app apps[3];
static int shelf_n;
static struct { unsigned long thread; unsigned wifi; volatile int state,cancel,percent; void *label; } nu;
static struct {
    unsigned long thread; unsigned wifi;
    volatile int running,cancel,percent,stage,result;
    int job,app,armed,rows,n; unsigned long long checked;
    shelf_app next[3]; void *page;
} sh;
typedef struct {
    char id[24], bin[24], run[24], pid[24], state[24];
    int launched,hold,relaunch;
    unsigned polled,launch_at,wifi;
} app_t;
static struct { app_t a[3]; int n; } ap;
static unsigned serial, live[256], acquires, releases, ready_calls, waits, sleeps;
static int readiness, create_error, timer_error, owner, download_result, downloads;
static int checks, installs, install_result, removals, systems, held, pid_present, fallbacks, lyrics, covers_called;
static unsigned clock_ms = 1000;
static void *(*pending)(void *);
unsigned smart_wifi_acquire(enum smart_wifi_owner who) {
    owner=who; acquires++; assert(serial+1<256); live[++serial]=1; return serial;
}
int smart_wifi_ready(unsigned token) {
    ready_calls++; assert(token && live[token]);
    if (waits) { waits--; return SW_WAIT; }
    return readiness;
}
void smart_wifi_release(unsigned token) {
    if (token) { assert(live[token]); live[token]=0; releases++; }
}
void smart_wifi_hold(enum smart_wifi_owner who,int on) { assert(who==SW_ADDON); held=on; }
static int active(void) { int n=0; for (unsigned i=1;i<=serial;i++) n+=live[i]; return n; }
static int usleep(unsigned usec) { assert(usec==50000); sleeps++; return 0; }
static int get_wifisignal(void) { return 1; }
static unsigned time_now_ms(void) { return clock_ms; }
static unsigned long long now_ms(void) { return clock_ms; }
static int download(void) { assert(active()); downloads++; return download_result; }
static void show(const char *s) { (void)s; }
static void toast(const char *s) { (void)s; }
static int wait_done(const void *unused) { return 0; }
static int sh_wait(const void *unused) { return 0; }
static unsigned timer_add(int (*f)(const void *),void *a,unsigned ms) {
    assert(ms==500); return timer_error ? 0 : 1;
}
static void stop_timer(unsigned *t) { *t=0; }
static int pthread_create(unsigned long *t,void *attr,void *(*run)(void *),void *arg) {
    assert(active() || sh.job==JOB_REMOVE || sh.job==JOB_ERASE);
    if (create_error) return 1;
    *t=1; pending=run; return 0;
}
static int sh_find(const char *id) { return 1; }
static int is(int i,const char *id) { return 0; }
static int check(void) { assert(active()); checks++; return 1; }
static int install(int i) { assert(active()); installs++; return install_result; }
static int system(const char *cmd) { systems++; return 0; }
static int rmdir(const char *path) { return 0; }
static void shelf_remove(int i) { removals++; }
static void addon_quit(const char *dir) {}
static void addon_forget(const char *dir);
static void spot_stop(void) {}
static int lrclib(const char *out) { assert(active()); lyrics++; return 0; }
static int stock_kugou_trampoline(const char *k,const char *o) { assert(active()); fallbacks++; return 1; }
static void covers(void) { assert(active()); covers_called++; }
static void stock_kugoucover_trampoline(const char *k) { assert(active()); fallbacks++; }
static const char *shelf_busy(void) { return 0; }
static int access(const char *path,int mode) { return !strcmp(path,"pid") ? !pid_present : 0; }
static int navigator_window_is_exist(const char *name) { return 0; }
static unsigned state_read(const char *path,char *out,unsigned size) { *out=0; return 0; }
static unsigned number(const char *raw,const char *key) { return 0; }
static void reset_poweroptions_timer(int a,int b,int c) {}
static void stream_poll(app_t *a) {}
static void reset(void) {
    assert(!active());
    memset(&nu,0,sizeof nu); memset(&sh,0,sizeof sh); memset(&ap,0,sizeof ap);
    readiness=SW_READY; create_error=timer_error=0; download_result=NU_DONE;
    downloads=checks=installs=removals=systems=held=pid_present=0;
    lyrics=fallbacks=covers_called=0; waits=sleeps=ready_calls=0;
    shelf_n=2; strcpy(apps[0].dir,".kept"); install_result=SH_OK; pending=0;
}
'''
tests = r'''
int main(void) {
    reset();
    waits=2;
    online_click(0,0);
    assert(nu.state==NU_RUNNING && active()==1 && owner==SW_NETUPDATE && !ready_calls);
    unsigned before=acquires;
    online_click(0,0); /* repeat press cancels, never replaces an in-flight token */
    assert(acquires==before && nu.cancel);
    pending(0);
    assert(!active() && nu.state==NU_CANCELLED && !downloads && !nu.wifi);
    reset();
    online_click(0,0); pending(0);
    assert(!active() && nu.state==NU_DONE && downloads==1);
    reset();
    download_result=NU_NET;
    online_click(0,0); pending(0);
    assert(!active() && nu.state==NU_NET);
    reset();
    nu.label=(void *)42;
    online_click(0,0); label_gone((void *)42,0);
    assert(active() && nu.cancel && !nu.label);
    pending(0); assert(!active() && !downloads);
    for (int state=SW_USER_OFF; state>=SW_INVALID; state--) {
        reset(); readiness=state;
        online_click(0,0); pending(0);
        assert(!active() && !downloads && nu.state==NU_NET);
    }
    reset(); create_error=1;
    online_click(0,0); assert(!active() && !pending && nu.state==NU_IDLE);
    reset(); timer_error=1;
    online_click(0,0); assert(!active() && !pending && nu.state==NU_IDLE);

    reset(); waits=2; sh.page=(void *)99;
    sh_start(JOB_CHECK,0);
    assert(active()==1 && owner==SW_SHELF && !ready_calls);
    before=acquires;
    sh_start(JOB_INSTALL,0); assert(acquires==before); /* older worker owns its job until joined */
    sh_closed(0,0); assert(active() && sh.running && !sh.page);
    pending(0);
    assert(!active() && !sh.wifi && !sh.running && checks==1 && sleeps==2 && sh.checked);
    assert(sh.job==JOB_CHECK); /* next job cannot start before UI completion consumes this */
    sh_start(JOB_INSTALL,0); assert(acquires==before);
    reset(); readiness=SW_TIMEOUT;
    sh_start(JOB_CHECK,0); pending(0);
    assert(!active() && !checks && sh.result==SH_NET && sh.n==2 && !strcmp(sh.next[0].dir,".kept"));
    reset(); sh_start(JOB_INSTALL,0); sh.cancel=1; pending(0);
    assert(!active() && !installs && sh.result==SH_CANCELLED);
    reset(); install_result=SH_NET;
    sh_start(JOB_INSTALL,0); pending(0);
    assert(!active() && installs==1 && sh.result==SH_NET);
    reset(); create_error=1; sh_start(JOB_CHECK,0);
    assert(!active() && !pending && !sh.job && !sh.running);
    reset(); timer_error=1; sh_start(JOB_INSTALL,0);
    assert(!active() && !pending && !sh.job && !sh.running);
    reset(); before=acquires; sh_start(JOB_REMOVE,0); pending(0);
    assert(acquires==before && !active() && removals==1);
    reset(); before=acquires; sh_start(JOB_ERASE,0); pending(0);
    assert(acquires==before && !active() && systems==2);

    reset(); waits=2; assert(ringnav_lyric_search("k","out"));
    assert(!active() && lyrics==1 && fallbacks==1 && sleeps==2);
    reset(); readiness=SW_USER_OFF; assert(!ringnav_lyric_search("k","out"));
    assert(!active() && !lyrics && !fallbacks);
    reset(); ringnav_cover_search("k");
    assert(!active() && covers_called==1 && fallbacks==1);
    reset(); readiness=SW_TIMEOUT; ringnav_cover_search("k");
    assert(!active() && !covers_called && !fallbacks);

    reset(); ap.n=1; app_t *a=&ap.a[0]; strcpy(a->id,"demo"); strcpy(a->pid,"pid");
    waits=1; launch(a);
    assert(active() && !systems && held && addon_wifi_busy());
    poll_one(a); assert(active() && !systems);
    clock_ms+=500; poll_one(a);
    assert(!active() && systems==1 && a->launched && !a->hold && addon_wifi_busy());
    a->launched=0; assert(!addon_wifi_busy());
    a->relaunch=1; assert(addon_wifi_busy()); a->relaunch=0;
    pid_present=1; assert(addon_wifi_busy()); pid_present=0;
    launch(a); addon_forget(".demo"); assert(!active() && !addon_wifi_busy());
    launch(a); readiness=SW_USER_OFF; clock_ms+=500; poll_one(a);
    assert(!active() && a->launched && systems==2 && addon_wifi_busy());
    assert(acquires==releases);
    puts("Smart Wi-Fi production consumer functions: worker/page/cancel/failure leases, readiness, stock fallback, addon lifetime passed.");
    return 0;
}
'''
# The tested functions retain production names and bodies; only external APIs are seams.
source = preamble + "\n" + addon + "\n" + net + "\n" + match + "\n" + tests
with tempfile.TemporaryDirectory(prefix="q2-wifi-consumers-") as td:
    path = pathlib.Path(td)
    (path / "consumers.c").write_text(source)
    subprocess.run(["cc", "-std=c11", "-Werror=implicit-function-declaration",
                    "-I", str(ROOT / "patch"), str(path / "consumers.c"),
                    "-o", str(path / "consumers")], check=True)
    subprocess.run([path / "consumers"], check=True)

tidal_preamble = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "smartwifi.h"
#define TIDAL_DIR "/mock/tidal"
#define I(a,b) 0
#define P(a,b) mock_ptr()
static void *mock_ptr(void) { return 0; }
#define REC_TIDAL_ID 0
#define REC_TITLE 0
#define REC_ARTIST 0
#define tk_snprintf snprintf
static struct {
    unsigned lock[16]; int busy,job; volatile unsigned gen,want,job_gen;
    unsigned cleared; unsigned long thread; char id[48],url[2048],path[296];
} td;
static unsigned live[256],serial,acquires,releases,waits,ready_calls,injected;
static int readiness,locked,create_error,cached_result,open_error,curl_error;
static int fetches,trimmed,unlinked,slept,inject_idle;
static void *(*pending)(void *); static void *pending_arg;
unsigned smart_wifi_acquire(enum smart_wifi_owner owner) {
    assert(owner==SW_TIDAL && locked);
    acquires++; assert(serial+1<256); live[++serial]=1; return serial;
}
int smart_wifi_ready(unsigned token) {
    assert(token && live[token]); ready_calls++;
    if (waits) { waits--; return SW_WAIT; }
    return readiness;
}
void smart_wifi_release(unsigned token) { assert(token && live[token]); live[token]=0; releases++; }
static int active(void) { int n=0; for (unsigned i=1;i<=serial;i++) n+=live[i]; return n; }
static void pthread_mutex_lock(unsigned *lock) { assert(!locked); locked=1; }
static void pthread_mutex_unlock(unsigned *lock) {
    assert(locked); locked=0;
    if (inject_idle && !td.busy) {
        inject_idle=0;
        /* A new caller queues work after the old worker marked itself idle, but
         * before that old worker releases its own token. This is the real race. */
        locked=1; td.busy=td.job=1; td.job_gen=td.gen;
        injected=smart_wifi_acquire(SW_TIDAL);
        locked=0;
    }
}
static int pthread_create(unsigned long *t,void *attr,void *(*fn)(void *),void *arg) {
    assert(!locked && (unsigned long)arg && live[(unsigned long)arg]);
    if (create_error) return 1;
    *t=1; pending=fn; pending_arg=arg; return 0;
}
static void pthread_detach(unsigned long thread) {}
static void sleep_ms(unsigned ms) { assert(ms==100); slept++; }
static void headset_manual(void) {}
static int stock_tidal_trampoline(const char *url) { return 77; }
static const char *tidal_ext(const char *url,char *out,unsigned n) { strcpy(out,".flac"); return out; }
static char *tidal_name(char *out,unsigned n,const char *k,const char *a,const char *t,const char *ext) {
    snprintf(out,n,"%s%s",k,ext); return out;
}
static int cached(const char *key,const char *ext,char *path,unsigned n) {
    snprintf(path,n,"cached"); return cached_result;
}
static int mkdir(const char *path,unsigned mode) { return 0; }
static int card_space(const char *path) { return 1; }
static unsigned deque_size(void *q) { return 0; }
static void *deque_at(void *q,unsigned i) { return 0; }
static void *td_fopen(const char *path,const char *mode) { assert(active()); return open_error ? 0 : (void *)1; }
static int td_fflush(void *f) { return 0; }
static int td_ferror(void *f) { return 0; }
static int td_fclose(void *f) { return 0; }
static int td_fileno(void *f) { return 9; }
static int fsync(int fd) { return 0; }
static int td_rename(const char *from,const char *to) { return 0; }
static int unlink(const char *path) { unlinked++; return 0; }
static void trim(void) { trimmed++; }
#define fopen td_fopen
#define fflush td_fflush
#define ferror td_ferror
#define fclose td_fclose
#define fileno td_fileno
#define rename td_rename
static void *curl_easy_init(void) { return (void *)2; }
static int curl_easy_setopt(void *c,int option,...) { return 0; }
static int curl_easy_perform(void *c) { assert(active()); fetches++; return curl_error; }
static int curl_easy_getinfo(void *c,int option,long *out) { *out=200; return 0; }
static void curl_easy_cleanup(void *c) {}
static unsigned save(const void *d,unsigned s,unsigned n,void *f) { return s*n; }
static int progress(void *s,long long a,long long b,long long c,long long d) { return 0; }
static void reset(void) {
    assert(!active() && !locked); memset(&td,0,sizeof td);
    readiness=SW_READY; create_error=cached_result=open_error=curl_error=0;
    fetches=trimmed=unlinked=slept=inject_idle=0;
    waits=ready_calls=injected=0; pending=0; pending_arg=0;
}
'''
tidal_body = "\n".join(function("patch/tidal.c", n) for n in ("download", "tidal_play"))
tidal_tests = r'''
int main(void) {
    reset(); unsigned before=acquires;
    assert(tidal_play(0,"id")==77 && acquires==before && !pending);
    reset(); cached_result=1;
    assert(tidal_play("url.flac","id")==77 && acquires==before && !pending);
    reset(); waits=2; tidal_play("url.flac","id");
    assert(active()==1 && !ready_calls && td.busy && td.job);
    pending(pending_arg);
    assert(!active() && !td.busy && !td.job && fetches==1 && trimmed==1 && slept==2);
    reset(); open_error=1; tidal_play("url.flac","id"); pending(pending_arg);
    assert(!active() && !fetches && unlinked==1);
    reset(); curl_error=1; tidal_play("url.flac","id"); pending(pending_arg);
    assert(!active() && fetches==1 && unlinked==1 && !trimmed);
    for (int state=SW_USER_OFF; state>=SW_INVALID; state--) {
        reset(); readiness=state; tidal_play("url.flac","id"); pending(pending_arg);
        assert(!active() && !td.busy && !td.job && !fetches);
    }
    reset(); waits=2; tidal_play("url.flac","id"); ++td.gen; pending(pending_arg);
    assert(!active() && !td.busy && !td.job && !fetches && !slept);
    reset(); tidal_play("url.flac","id"); td.job=0; pending(pending_arg);
    assert(!active() && !td.busy && !fetches);
    reset(); create_error=1; tidal_play("url.flac","id");
    assert(!active() && !td.busy && !td.job && !pending);
    reset(); tidal_play("url.flac","id"); inject_idle=1; pending(pending_arg);
    assert(active()==1 && injected && live[injected] && td.busy && td.job);
    download((void *)(unsigned long)injected);
    assert(!active() && fetches==2 && !td.busy && !td.job && acquires==releases);
    puts("Tidal production worker: acquired-before-create, success/failure/cancel/timeout/no-job cleanup and overlapping worker token ownership passed.");
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix="q2-wifi-tidal-") as td:
    path = pathlib.Path(td)
    (path / "tidal.c").write_text(tidal_preamble + tidal_body + tidal_tests)
    subprocess.run(["cc", "-std=c11", "-Werror=implicit-function-declaration",
                    "-I", str(ROOT / "patch"), str(path / "tidal.c"),
                    "-o", str(path / "tidal")], check=True)
    subprocess.run([path / "tidal"], check=True)
