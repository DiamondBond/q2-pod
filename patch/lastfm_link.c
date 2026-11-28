/* Library's Link Last.fm. The phone approves the request token; the card keeps the session key. */
#include "navigation.h"

#define SCROBBLE_INI "/mnt/mmc/.scrobble.ini"
#define LINK_PNG "/tmp/q2-lastfm-link.png"

static struct {
    widget_t *page, *code, *status, *button;
    unsigned long thread;
    int running;
    volatile int finished;
    char api[256], secret[256], token[64], session[64], previous[256];
    int error;
} fm __attribute__((section(".scratch")));

static void fm_setting(const char *name, char out[256]) {
    out[0] = 0;
    toolsReadConfig(SCROBBLE_INI, "LASTFM", name, out, "");
}

/* Both a URL parameter and an INI value must fit whole, without delimiters. */
static int valid_key(const char *s) {
    unsigned n = 0;
    for (; s && s[n]; n++) {
        char c = s[n];
        if (n >= 63 || !((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                         (c >= '0' && c <= '9') || c == '-' || c == '_'))
            return 0;
    }
    return n > 0;
}

static void *authorize(void *unused) {
    char body[1024];
    int exchange = fm.token[0] != 0;
    int ok = scrobble_auth(fm.api, fm.secret, fm.token, body, sizeof body);
    void *json = cJSON_Parse(body);
    void *error = json ? cJSON_GetObjectItem(json, "error") : 0;
    void *object = exchange && json ? cJSON_GetObjectItem(json, "session") : json;
    void *item = object ? cJSON_GetObjectItem(object, exchange ? "key" : "token") : 0;
    const char *value = item ? P(item, 16) : 0; /* stock cJSON's valuestring */
    fm.error = -1;
    if (ok && !error && value && valid_key(value)) {
        memcpy(exchange ? fm.session : fm.token, value, strlen(value) + 1);
        fm.error = 0;
    } else if (error) {
        int code = I(error, 20); /* valueint */
        if (code == 4 || code == 14 || code == 15) fm.error = code;
    }
    cJSON_Delete(json);
    fm.finished = 1;
    return 0;
}

static void prompt(const char *status, const char *action) {
    widget_set_text_utf8(fm.status, status);
    widget_set_visible(fm.button, action != 0, 0);
    if (action) widget_set_text_utf8(fm.button, action);
}

static int save_session(void) {
    char current[256];
    fm_setting("API_KEY", current);
    if (strcmp(current, fm.api)) return 0;
    fm_setting("API_SECRET", current);
    if (strcmp(current, fm.secret)) return 0;
    fm_setting("SESSION_KEY", current);
    if (navigator_window_is_exist("usbmode_page")) return 0;
    if (!strcmp(current, fm.session)) return 1;
    if (strcmp(current, fm.previous)) return 0;
    if (toolsWriteConfig(SCROBBLE_INI, "LASTFM", "SESSION_KEY", fm.session)) return 0;
    fm_setting("SESSION_KEY", current);
    return !strcmp(current, fm.session);
}

static void linked(void) {
    if (!save_session()) {
        prompt(tr("Could not save to this card"), tr("Retry"));
        return;
    }
    navigator_back();
    upload_scrobbles(0, 0);
}

static int link_poll(const void *unused) {
    if (!fm.finished) return 8;
    if (fm.page && window_manager_get_top_window(window_manager()) != fm.page) return 8;
    pthread_join(fm.thread, 0);
    fm.running = 0;
    if (!fm.page) {
        memset(&fm, 0, sizeof fm);
        return 0;
    }
    if (fm.token[0] && (fm.error == 4 || fm.error == 15)) {
        fm.token[0] = 0;
        widget_set_visible(fm.code, 0, 0);
        prompt(tr("This code is no longer valid"), tr("New code"));
    } else if (fm.error) {
        prompt(fm.error == 14 ? tr("Approve access on your phone first")
                              : tr("Last.fm link failed"),
               fm.token[0] ? tr("Done") : tr("Retry"));
    } else if (fm.session[0]) {
        linked();
    } else {
        char url[192];
        tk_snprintf(url, sizeof url, "https://www.last.fm/api/auth/?api_key=%s&token=%s", fm.api,
                    fm.token);
        unlink(LINK_PNG);
        /* Claim the name in sticky /tmp before stock opens it for writing. MIPS
         * O_WRONLY|O_CREAT|O_EXCL. */
        int fd = open(LINK_PNG, 0x501, 0600);
        if (fd >= 0 && !close(fd) && !toolsMakeQrcode(url, LINK_PNG) &&
            image_show(fm.code, "file://" LINK_PNG, 0)) {
            widget_set_visible(fm.code, 1, 0);
            prompt(tr("Scan and approve on your phone"), tr("Done"));
        } else {
            fm.token[0] = 0;
            prompt(tr("Could not display the code"), tr("Retry"));
        }
    }
    return 0;
}

static int proceed(void *ctx, event_t *event) {
    if (!fm.page || fm.running) return 0;
    if (fm.session[0]) {
        linked();
        return 0;
    }
    if (!need_link(proceed, ctx)) return 0;
    const char *waiting = fm.token[0] ? tr("Checking approval") : tr("Getting Last.fm code");
    fm.finished = 0;
    unsigned timer = timer_add(link_poll, 0, 250);
    if (!timer || pthread_create(&fm.thread, 0, authorize, 0)) {
        stop_timer(&timer);
        prompt(tr("Last.fm link failed"), tr("Retry"));
    } else {
        fm.running = 1;
        prompt(waiting, 0);
    }
    return 0;
}

static int link_key(void *ctx, event_t *event) {
    if (I(event, EVENT_KEY) == KEY_CENTER) {
        proceed(0, event);
        return STOP;
    }
    return page_keyup(ctx, event);
}

static int link_closed(void *ctx, event_t *event) {
    fm.page = 0;
    unlink(LINK_PNG);
    if (!fm.running) memset(&fm, 0, sizeof fm);
    return 0;
}

int lastfm_link(void *ctx, event_t *event) {
    if (fm.page || !need_link(lastfm_link, ctx)) return 0;
    if (fm.running) {
        toast(tr("Finishing Last.fm request"));
        return 0;
    }
    fm_setting("API_KEY", fm.api);
    fm_setting("API_SECRET", fm.secret);
    fm_setting("SESSION_KEY", fm.previous);
    if (!valid_key(fm.api) || !fm.secret[0]) {
        toast(tr("Check the Last.fm API key and secret"));
        return 0;
    }
    fm.page = page_open("qrcode_page", link_closed, link_key);
    if (!fm.page) return 0;
    page_title(fm.page, tr("Link Last.fm"), 1);
    int h = client_h();
    fm.code = image_create(fm.page, (375 - 164) / 2, h - 244, 164, 164);
    image_set_draw_type(fm.code, 4);
    widget_set_visible(fm.code, 0, 0);
    fm.status = text(fm.page, 8, h - 78, 359, 30);
    fm.button = button_create(fm.page, 110, h - 46, 155, 42);
    widget_use_style(fm.button, "s_btn_listitem");
    widget_on(fm.button, EVT_CLICK, proceed, 0);
    prompt(tr("Getting Last.fm code"), tr("Retry"));
    proceed(0, 0);
    return 0;
}
