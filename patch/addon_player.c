/* Card apps' player (addon.c's apps whose q2app holds player=1, the caps word "player"): what the
 * Q2 plays, and requests to control it, through /tmp, for a player app of its own.
 * While such an app is launched or restarting, addon_player_poll keeps PLAYER_FILE, one key=value a
 * line (a value's tabs and line ends written as spaces), looked at every PLAYER_LOOK_MS and right
 * after a request is answered, and written whole (blob_io) only when its text changes: status,
 * owner, kind (MCL_TYPE in hex), the playing record's path (a card path, else empty), tags
 * (now_tag, as Now Playing shows them), track, disc, its CUE range in ms, sec and len
 * (player_playtime_and_length), volume and maxvolume, output, shuffle, repeat and group
 * (playback_option), heart (checkFavExist, asked again only for a new track or after a heart
 * command), pos and count, the queue's queue_hash in hex and upnext, up to UPNEXT indices of
 * playback_upcoming, empty when they are the queue's own from pos on. PLAYER_QUEUE is written whole
 * whenever that hash changes: the hash, then a line a record, up to QUEUE_LINES, "more\t<count>"
 * after them for a longer queue. With no such app running both files are removed.
 * A running app's /tmp/q2-<id>.player holds a seq (1 to SEQ - 1 bytes of [0-9A-Za-z]) on its first
 * line and up to REQ_LINES commands after it; addon_player_ask reads its first SEQ bytes every UI
 * pass, at most every ASK_MS for an app, and the whole file once when those are new for the app's
 * slot, as addon_eq_poll reads an .eq. The commands run in order and the answer goes to
 * .player.done, written whole: "<seq> ok", or "<seq> error <N>: <why>" for line N, the lines
 * before it done and none after it run. A seq .player.done already answers is taken as done, and a
 * first line that isn't a seq is never answered. */
#include "navigation.h"

#define PLAYER_FILE "/tmp/q2-player"
#define PLAYER_QUEUE "/tmp/q2-player.queue"
#define PLAYER_TMP "/tmp/q2-player.tmp" /* a request's answer, renamed into its .done */
#define PLAYER_LOOK_MS 100
#define ASK_MS 30
#define SEQ 24 /* a seq's bytes and its line end */
#define REQ_LINES 16
#define REQ_RAW 1024
#define QUEUE_LINES 5000
#define UPNEXT 50
#define FIELD_MAX 1023     /* a value's bytes at most, so a line's tail always fits */
#define LIST_MAX (1 << 20) /* an app's .list read this far: 5000 paths of 200 bytes */
#define LOCAL(t) ((t) == 1 || ((t) & 0xf000) == 0xf000) /* a folder or library queue */

static struct {
    unsigned said;   /* the state text written, hashed | 2; 1 the files removed; 0 before a look */
    unsigned polled; /* the last look */
    int force;       /* a request answered: looked at on this pass */
    unsigned qkey, qhash, qsaid; /* the queue as last hashed (its deque, size and loads), its hash,
                                  * and the hash PLAYER_QUEUE holds (qfile) */
    int qfile;
    unsigned track; /* the track whose heart was asked, and the answer */
    int heart;
    unsigned seen[APPS_MAX],
        asked[APPS_MAX]; /* each app's request as last read, hashed; its read */
} pr __attribute__((section(".scratch")));

typedef struct {
    char *p;
    unsigned n, size;
} text_t;

/* s, at most FIELD_MAX bytes of it, its tabs and line ends as spaces, then end (0 none) */
static void add(text_t *t, const char *s, char end) {
    for (unsigned k = 0; s && *s && k < FIELD_MAX && t->n + 2 < t->size; ++s, ++k)
        t->p[t->n++] = *s == '\t' || *s == '\r' || *s == '\n' ? ' ' : *s;
    if (end && t->n + 1 < t->size) t->p[t->n++] = end;
    t->p[t->n] = 0;
}
static void key(text_t *t, const char *k, const char *v) { add(t, k, '='), add(t, v, '\n'); }
static void num(text_t *t, const char *k, const char *fmt, int v) {
    char s[16];
    snprintf(s, sizeof s, fmt, v);
    key(t, k, s);
}

static const char *on_card(const char *p) {
    return p && tk_str_start_with(p, "/mnt/mmc/") ? p : "";
}
static const char *title(void *r) {
    const char *t = now_tag(r, REC_TITLE);
    return t && *t ? t : P(r, REC_NAME);
}

/* The queue playing when it is a local one (qm_apply's rule), else 0 */
static void *local_queue(void) {
    void *q = P(mcl_pdeqplaylist, 0);
    unsigned type = (unsigned)MCL(MCL_TYPE);
    return q && airplayGetFlag() != 2 && LOCAL(type) ? q : (void *)0;
}

static unsigned state_text(char *out, unsigned size) {
    text_t t = { out, 0, size };
    unsigned pos, n, up[UPNEXT], type = (unsigned)MCL(MCL_TYPE);
    void *q = P(mcl_pdeqplaylist, 0), *r = queue_now(&pos, &n);
    int status = mclGetPlayStatus(), owner = media_owner(), sec = -1, len = -1, way;
    /* hashed whole only when another deque, size or load says it may have changed */
    unsigned was[3] = { (unsigned)(unsigned long)q, n, playback_loads },
             qk = hash_bytes(FNV_SEED, (const unsigned char *)was, sizeof was);
    if (qk != pr.qkey) pr.qkey = qk, pr.qhash = q ? queue_hash(q) : 0;
    was[1] = pos;
    unsigned track = r ? fnv(hash_bytes(FNV_SEED, (const unsigned char *)was, sizeof was),
                             (const unsigned char *)on_card(P(r, REC_PATH))) |
                             1
                       : 0;
    if (track != pr.track) pr.track = track, pr.heart = r && LOCAL(type) && checkFavExist(r) != 0;
    if (r) player_playtime_and_length(&sec, &len);
    key(&t, "status", status == 2 ? "playing" : status == 3 ? "paused" : "stopped");
    key(&t, "owner",
        addon_game_audio() ? "game"
        : owner == 3       ? "radio"
        : owner == 2       ? "spotify"
        : r                ? "player"
                           : "none");
    num(&t, "kind", "%x", (int)type);
    key(&t, "path", r ? on_card(P(r, REC_PATH)) : "");
    key(&t, "title", r ? title(r) : "");
    key(&t, "artist", r ? now_tag(r, REC_ARTIST) : "");
    key(&t, "album", r ? now_tag(r, REC_ALBUM) : "");
    key(&t, "albumartist", r ? now_tag(r, REC_ALBUM_ARTIST) : "");
    key(&t, "genre", r ? P(r, REC_GENRE) : "");
    num(&t, "track", "%d", r ? I(r, REC_TRACK) : 0);
    num(&t, "disc", "%d", r ? I(r, REC_DISC) : 0);
    num(&t, "cuestart", "%d", r ? I(r, REC_CUE_START) * 1000 : 0);
    num(&t, "cueend", "%d", r ? I(r, REC_CUE_END) * 1000 : 0);
    num(&t, "sec", "%d", sec);
    num(&t, "len", "%d", len);
    num(&t, "volume", "%d", g_volume);
    num(&t, "maxvolume", "%d", g_maxvolume);
    way = mclGetOutputWay();
    key(&t, "output",
        airplay_on() ? "airplay"
        : way == 1   ? "bluetooth"
        : way == 2   ? "usb"
                     : "jack");
    num(&t, "shuffle", "%d", playback_option(0));
    num(&t, "repeat", "%d", playback_option(1));
    num(&t, "group", "%d", playback_option(2));
    num(&t, "heart", "%d", pr.heart);
    num(&t, "pos", "%d", (int)pos);
    num(&t, "count", "%d", (int)n);
    num(&t, "queue", "%x", (int)pr.qhash);
    unsigned k = playback_upcoming(up, UPNEXT), own = 1;
    for (unsigned i = 0; i < k; ++i) own &= up[i] == pos + 1 + i;
    add(&t, "upnext=", 0);
    for (unsigned i = 0; !own && i < k; ++i) {
        char s[12];
        snprintf(s, sizeof s, "%s%u", i ? "," : "", up[i]);
        add(&t, s, 0);
    }
    add(&t, "", '\n');
    return t.n;
}

/* PLAYER_QUEUE, whole: hash, then <path>\t<title>\t<artist>\t<album>\t<albumartist>\t<track>\t
 * <cuestart>\t<cueend> a record, the record's own text, up to QUEUE_LINES. */
static int queue_write(void *q, unsigned hash) {
    void *f = fopen(PLAYER_QUEUE ".tmp", "wb");
    if (!f) return 0;
    char line[5 * (FIELD_MAX + 1) + 64];
    unsigned n = q ? deque_size(q) : 0;
    int ok = fwrite(line, (unsigned)snprintf(line, sizeof line, "%x\n", hash), 1, f) == 1;
    for (unsigned i = 0; ok && i < n && i < QUEUE_LINES; ++i) {
        void *r = deque_at(q, i);
        const char *t = P(r, REC_TITLE);
        text_t l = { line, 0, sizeof line };
        add(&l, on_card(P(r, REC_PATH)), '\t');
        add(&l, t && *t ? t : P(r, REC_NAME), '\t');
        add(&l, P(r, REC_ARTIST), '\t');
        add(&l, P(r, REC_ALBUM), '\t');
        add(&l, P(r, REC_ALBUM_ARTIST), '\t');
        l.n += (unsigned)snprintf(line + l.n, sizeof line - l.n, "%d\t%d\t%d\n", I(r, REC_TRACK),
                                  I(r, REC_CUE_START) * 1000, I(r, REC_CUE_END) * 1000);
        ok = fwrite(line, l.n, 1, f) == 1;
    }
    if (ok && n > QUEUE_LINES)
        ok = fwrite(line, (unsigned)snprintf(line, sizeof line, "more\t%u\n", n), 1, f) == 1;
    if (fclose(f) || !ok || rename(PLAYER_QUEUE ".tmp", PLAYER_QUEUE)) {
        unlink(PLAYER_QUEUE ".tmp");
        return 0;
    }
    return 1;
}

void addon_player_poll(int on) {
    unsigned ms = time_now_ms();
    if (!on) {
        if (pr.said != 1) unlink(PLAYER_FILE), unlink(PLAYER_QUEUE);
        pr.said = 1, pr.qfile = 0;
        return;
    }
    if (pr.said > 1 && !pr.force && ms - pr.polled < PLAYER_LOOK_MS) return;
    pr.polled = ms, pr.force = 0;
    char text[8 * (FIELD_MAX + 16) + 1024];
    unsigned n = state_text(text, sizeof text),
             h = hash_bytes(FNV_SEED, (const unsigned char *)text, n) | 2;
    if ((!pr.qfile || pr.qsaid != pr.qhash) && queue_write(P(mcl_pdeqplaylist, 0), pr.qhash))
        pr.qfile = 1, pr.qsaid = pr.qhash;
    if (h != pr.said && blob_io(PLAYER_FILE, PLAYER_FILE ".tmp", text, n, 1)) pr.said = h;
}

/* s as a number of 1 to 9 digits, else -1 */
static int arg_number(const char *s) {
    int v = 0, k = 0;
    for (; *s >= '0' && *s <= '9' && k < 9; ++s, ++k) v = v * 10 + (*s - '0');
    return k && !*s ? v : -1;
}

/* The app's /tmp/q2-<id>.list as songs, in its order: each line a card path (card_path), at most
 * QUEUE_LINES of them; one its folder's listing (app_album_songs) has no song of is skipped. *at,
 * an index among the list's lines (empty ones not counted), becomes the index of the first song
 * from that line on, or ~0u when there is none. A deque the caller destroys.
 * ponytail: a folder is listed each time the list comes back to it after another, on the UI
 * thread; a list of songs scattered over many folders takes a while (the watchdog's long count). */
static void *list_songs(const char *id, unsigned *at) {
    char path[48], dir[1024] = "";
    snprintf(path, sizeof path, "/tmp/q2-%s.list", id);
    char *raw = calloc(1, LIST_MAX + 3);
    void *out = song_list(), *songs = 0;
    if (raw && state_read(path, raw, LIST_MAX + 3) > LIST_MAX) strrchr(raw, '\n')[1] = 0;
    unsigned entry = 0, want = *at;
    *at = ~0u;
    if (raw && raw[1]) ringnav_wdt_long();
    for (char *l = raw ? raw + 1 : 0, *e; l && *l && entry < QUEUE_LINES; l = e) {
        if ((e = strstr(l, "\n")))
            *e++ = 0;
        else
            e = l + strlen(l);
        unsigned k = strlen(l);
        if (k && l[k - 1] == '\r') l[--k] = 0;
        if (!k) continue;
        if (entry++ == want) *at = deque_size(out);
        if (!card_path(l) || k >= sizeof dir) continue;
        char *slash = strrchr(l, '/');
        *slash = 0;
        if (!songs || strcmp(l, dir)) {
            if (songs) deque_destroy(songs);
            snprintf(dir, sizeof dir, "%s", l);
            songs = app_album_songs(dir);
        }
        *slash = '/';
        for (unsigned i = 0, n = deque_size(songs); i < n; ++i) {
            void *r = deque_at(songs, i);
            const char *p = P(r, REC_PATH);
            if (p && !strcmp(p, l)) {
                _deque_push_back(out, r);
                break;
            }
        }
    }
    if (*at != ~0u && *at >= deque_size(out)) *at = ~0u;
    if (songs) deque_destroy(songs);
    free(raw);
    return out;
}

/* My Favourites, as the queue menu's Favourites rows: in through batch-select's Add, or out. */
static void heart_set(void *r, int on) {
    if (on) {
        void *one = song_list();
        _deque_push_back(one, r);
        batch_init_selectrecord(1);
        batch_set_selectitem(0);
        batch_add_file(0xf001, 0xf00a, one, P(p_vector_select_record, 0), 0);
        deque_destroy(one);
    } else
        deleteMusicFromFav(r);
    ratings_copy_due();
    fav_told(r, on);
    st.np_seen = 0; /* Now Playing's heart drawn again */
}

#define NO_OUTPUT "No output connected"
#define NOT_LOCAL "Not a local queue"
#define NOTHING "Nothing is playing"
#define NO_SONG "No such song in the queue"
#define BAD "Bad value"

/* A start of the Q2's own player, Require Output asked first (stock's message shown) */
static int refused(void) {
    return media_owner() == 1 && !addon_game_audio() && check_forbid_play_no_headset(0);
}

/* One command line: 0 done, else why not. */
static const char *run(char *l, const char *id) {
    char *sp = strstr(l, " ");
    const char *arg = sp ? sp + 1 : "";
    if (sp) *sp = 0;
    int v = arg_number(arg), none = !sp;
    unsigned pos, n, at = (unsigned)v;
    void *r = queue_now(&pos, &n), *q = P(mcl_pdeqplaylist, 0), *lq = local_queue();
    int loaded = r || media_owner() != 1;
    if (!strcmp(l, "play") || !strcmp(l, "pause") || !strcmp(l, "toggle")) {
        int play = l[0] == 't' ? !media_playing() : l[1] == 'l';
        if (!none) return BAD;
        if (play == media_playing()) return 0;
        if (play && !loaded) return NOTHING;
        if (play && refused()) return NO_OUTPUT;
        media_set_playing(play);
    } else if (!strcmp(l, "next") || !strcmp(l, "prev")) {
        if (!none) return BAD;
        if (!loaded) return NOTHING;
        if (refused()) return NO_OUTPUT;
        media_key(l[0] == 'n' ? KEY_FWD_BTN : KEY_BACK_BTN);
    } else if (!strcmp(l, "seek")) {
        int sec = -1, len = -1, status = mclGetPlayStatus();
        if (v < 0) return BAD;
        if (!r || media_owner() != 1 || (status != 2 && status != 3)) return NOTHING;
        player_playtime_and_length(&sec, &len);
        sec = (v + 500) / 1000;
        seek_position(len > 0 && sec > len ? len : sec);
    } else if (!strcmp(l, "volume")) {
        if (v < 0 || v > 100) return BAD;
        if (v > g_maxvolume) v = g_maxvolume;
        g_volume = (unsigned char)v; /* as a game's volume (addon.c game_volume) */
        device_set_volume(v, 1);
        write_int_config(v, "PLAYSET", "VOLUME");
    } else if (!strcmp(l, "shuffle") || !strcmp(l, "repeat")) {
        int kind = l[0] == 'r';
        if (v < 0 || v > (kind ? 5 : 4)) return BAD;
        if (!lq || !playback_set(kind, v)) return NOT_LOCAL;
    } else if (!strcmp(l, "heart")) {
        if (v != 0 && v != 1) return BAD;
        if (!r) return NOTHING;
        if (!LOCAL((unsigned)MCL(MCL_TYPE))) return NOT_LOCAL;
        if ((checkFavExist(r) != 0) != v) heart_set(r, v);
        pr.track = 0; /* asked again */
    } else if (!strcmp(l, "jump")) {
        if (v < 0) return BAD;
        if (!q || at >= deque_size(q)) return NO_SONG;
        if (playback_keeps(q, v)) { /* the file playing or paused, as an Up Next row (un_play) */
            if (mclGetPlayStatus() == 3) player_play_pause();
            return 0;
        }
        if (check_forbid_play_no_headset(0)) return NO_OUTPUT;
        press_stamp();
        player_start_queue(v);
    } else if (!strcmp(l, "playnext") || !strcmp(l, "remove")) {
        if (v < 0) return BAD;
        if (!lq) return NOT_LOCAL;
        if (at >= deque_size(lq)) return NO_SONG;
        if (at == pos) return BAD;
        if (l[0] == 'r') return playback_queue_remove(at) ? 0 : NO_SONG;
        /* advanced play first, as Up Next's (playback_listable) or Next Group's (stock modes) */
        if (playback_move(at) < 0 &&
            (!(playback_listable() || playback_set(2, playback_option(2))) ||
             playback_move(at) < 0))
            return NOT_LOCAL;
    } else if (!strcmp(l, "load")) {
        if (v < 0) return BAD;
        void *songs = list_songs(id, &at);
        const char *why = !deque_size(songs)                ? BAD
                          : at == ~0u                       ? NO_SONG
                          : check_forbid_play_no_headset(0) ? NO_OUTPUT
                                                            : 0;
        if (!why) player_start(songs, (int)at, 0xf001, 2); /* plays, no Now Playing; it copies */
        deque_destroy(songs);
        return why;
    } else if (!strcmp(l, "insert")) {
        int next = !strcmp(arg, "next");
        if (!next && strcmp(arg, "end")) return BAD;
        if (!q || airplayGetFlag() == 2 || (deque_size(q) && !lq)) return NOT_LOCAL;
        at = 0;
        void *songs = list_songs(id, &at);
        if (!deque_size(songs)) {
            deque_destroy(songs);
            return BAD;
        }
        if (!deque_size(q)) /* loads without playing, as the queue menu's Add (qm_apply) */
            mclLoadPlayList(songs, 0, 0xf001);
        else
            qm_insert(q, songs, next);
        deque_destroy(songs);
    } else
        return "Unknown command";
    return 0;
}

void addon_player_ask(int slot, const char *id) {
    unsigned ms = time_now_ms();
    if (ms - pr.asked[slot] < ASK_MS) return;
    pr.asked[slot] = ms;
    char path[48], done[56], head[SEQ + 2], old[SEQ + 2], seq[SEQ], raw[REQ_RAW];
    snprintf(path, sizeof path, "/tmp/q2-%s.player", id);
    unsigned n = state_read(path, head, sizeof head),
             h = hash_bytes(FNV_SEED, (const unsigned char *)head + 1, n) | 1, k = 0;
    if (!n || h == pr.seen[slot]) return;
    pr.seen[slot] = h;
    state_read(path, raw, sizeof raw);
    while (k < SEQ - 1 &&
           ((raw[1 + k] >= '0' && raw[1 + k] <= '9') || (raw[1 + k] >= 'A' && raw[1 + k] <= 'Z') ||
            (raw[1 + k] >= 'a' && raw[1 + k] <= 'z')))
        ++k;
    snprintf(seq, sizeof seq, "%.*s", (int)k, raw + 1);
    snprintf(done, sizeof done, "%s.done", path);
    state_read(done, old, sizeof old);
    if (!k || raw[1 + k] != '\n' || (!strncmp(old + 1, seq, k) && old[1 + k] == ' ')) return;
    const char *why = 0;
    int line = 0;
    for (char *l = raw + 2 + k, *e; *l && !why; l = e) {
        if ((e = strstr(l, "\n")))
            *e++ = 0;
        else
            e = l + strlen(l);
        unsigned m = strlen(l);
        if (m && l[m - 1] == '\r') l[--m] = 0;
        ++line;
        if (m) why = line > REQ_LINES ? BAD : run(l, id);
    }
    int m = why ? snprintf(raw, sizeof raw, "%s error %d: %s\n", seq, line, why)
                : snprintf(raw, sizeof raw, "%s ok\n", seq);
    if (!blob_io(done, PLAYER_TMP, raw, (unsigned)m, 1)) unlink(PLAYER_TMP);
    pr.force = 1;
}
