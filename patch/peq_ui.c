#include "peq.h"
#include "offsets.inc"

extern int stock_eq_trampoline(int mode);
/* All calls, including restored playback, instantiate the replacement even in bypass.
 * Afterwards the flag only drives the status-bar EQ icon (systembar_showface @0x52f8b0). */
int peq_stock_eq(int mode) {
    (void)mode;
    g_equalizer_flag = 1;
    int result = stock_eq_trampoline(1);
    peq_preset active;
    peq_load_active(&active);
    g_equalizer_flag = !active.bypass;
    return result;
}

enum { HOME, BAND, PRESETS, IMPORTS, SAVES, CONFIRM };
enum { BACK = 1000, APPLY, BYPASS, MENU, IMPORT, SAVE, ENABLE, TYPE,
       FREQ_DOWN, FREQ_UP, GAIN_DOWN, GAIN_UP, Q_DOWN, Q_UP, STEP,
       YES, CANCEL };
static struct {
    void *page, *view;
    unsigned timer;
    int screen, band, step, count, previous, rendered, dirty;
    peq_preset draft, candidate;
    char (*names)[256];
    /* name: preset in the editor; active_name: last applied. Both last until reboot. */
    char destination[600], status[160], name[64], active_name[64];
} ui __attribute__((section(".scratch")));

static const int steps[] = {1, 10, 100, 1000};
static int action(void *ctx, void *event);
static int render(const void *unused);

static void row(void *view, int index, const char *text, int id) {
    void *item = list_item_create(view, 0, index * 48, 375, 48);
    widget_use_style(item, "s_listitem_black");
    void *label = label_create(item, 12, 0, 350, 48);
    widget_use_style(label, "s_label_white20c");
    widget_set_text_utf8(label, text);
    widget_on(item, EVT_CLICK, action, (void *)(long)id);
}

static int compare_names(const void *a, const void *b) { return strcmp(a, b); }

static void list_files(const char *folder, const char *extension) {
    ui.count = 0;
    if (!ui.names) ui.names = calloc(256, 256);
    if (!ui.names) { snprintf(ui.status, sizeof(ui.status), "Out of memory"); return; }
    void *dir = opendir(folder);
    if (!dir) { snprintf(ui.status, sizeof(ui.status), "Folder missing or unavailable"); return; }
    struct dirent *entry;
    while ((entry = readdir(dir))) {
        const char *name = entry->d_name;
        unsigned n = strlen(name), e = strlen(extension);
        if (entry->d_type != 8 && entry->d_type != 0) continue;
        if (n <= e || n >= 256 || strcmp(name + n - e, extension)) continue;
        if (ui.count == 256) break; /* show the first 256 */
        memcpy(ui.names[ui.count++], name, n + 1);
    }
    closedir(dir);
    qsort(ui.names, ui.count, 256, compare_names);
    if (!ui.count) snprintf(ui.status, sizeof(ui.status), "No presets found");
}

static void save_candidate(int replace) {
    mkdir(PEQ_SAVED, 0700);
    int result = peq_save(ui.destination, &ui.candidate, replace);
    if (result == 2) { ui.previous = ui.screen; ui.screen = CONFIRM; }
    else snprintf(ui.status, sizeof(ui.status), result ? "Preset saved; active EQ unchanged" : "Save failed; settings unchanged");
}

static int action(void *ctx, void *event) {
    (void)event;
    int id = (int)(long)ctx;
    if (id < 0) return 0; /* display-only rows */
    peq_band *b = &ui.draft.bands[ui.band];
    ui.status[0] = 0;
    if (id == BACK) {
        if (ui.screen == HOME) { navigator_back(); return 0; }
        ui.screen = ui.screen == BAND || ui.screen == PRESETS ? HOME : PRESETS;
    } else if (id == MENU) ui.screen = PRESETS;
    else if (id == IMPORT) ui.screen = IMPORTS;
    else if (id == SAVE) ui.screen = SAVES;
    else if (id == BYPASS) {
        /* Takes effect at once and keeps unapplied band edits out of the active preset. */
        peq_preset active;
        peq_load_active(&active);
        active.bypass = !ui.draft.bypass;
        if (peq_save(PEQ_ACTIVE, &active, 1) == 1) {
            ui.draft.bypass = active.bypass;
            peq_stock_eq(1);
        } else snprintf(ui.status, sizeof(ui.status), "Switch failed; PEQ unchanged");
    }
    else if (id == ENABLE) b->enabled = !b->enabled;
    else if (id == TYPE) b->type = (b->type + 1) % 3;
    else if (id == STEP) ui.step = (ui.step + 1) % 4;
    else if (id >= FREQ_DOWN && id <= Q_UP) {
        static const double lo[] = {20, -24, 0.1}, hi[] = {20000, 24, 10}, fixed[] = {0, 0.5, 0.05};
        int k = (id - FREQ_DOWN) / 2;
        double *value = (double *[]){&b->frequency, &b->gain, &b->q}[k], step = k ? fixed[k] : steps[ui.step];
        *value += ((id - FREQ_DOWN) & 1) ? step : -step;
        if (*value < lo[k]) *value = lo[k];
        if (*value > hi[k]) *value = hi[k];
    } else if (id == APPLY) {
        if (peq_save(PEQ_ACTIVE, &ui.draft, 1) == 1) {
            peq_stock_eq(1);
            ui.dirty = 0;
            memcpy(ui.active_name, ui.name, sizeof(ui.name));
            snprintf(ui.status, sizeof(ui.status), "Applied");
        } else snprintf(ui.status, sizeof(ui.status), "Apply failed; active EQ unchanged");
    } else if (id == YES) {
        ui.screen = ui.previous;
        save_candidate(1);
    } else if (id == CANCEL) ui.screen = ui.previous;
    else if (id >= 0 && id < 256) {
        if (ui.screen == HOME && id < PEQ_BANDS) { ui.band = id; ui.screen = BAND; }
        else if (ui.screen == SAVES && id < 10) {
            snprintf(ui.destination, sizeof(ui.destination), PEQ_SAVED "/Manual %02d.peq", id + 1);
            ui.candidate = ui.draft;
            save_candidate(0);
        } else if (id < ui.count && ui.screen == IMPORTS) {
            char path[600];
            peq_error error;
            snprintf(path, sizeof(path), PEQ_IMPORT "/%s", ui.names[id]);
            if (!peq_import_file(path, &ui.candidate, &error))
                snprintf(ui.status, sizeof(ui.status), "Line %u: %s", error.line, error.reason);
            else {
                unsigned n = strlen(ui.names[id]) - 4;
                snprintf(ui.destination, sizeof(ui.destination), PEQ_SAVED "/%.*s.peq", (int)n, ui.names[id]);
                save_candidate(0);
            }
        } else if (id < ui.count && ui.screen == PRESETS) {
            char path[600];
            snprintf(path, sizeof(path), PEQ_SAVED "/%s", ui.names[id]);
            peq_preset p;
            if (peq_load(path, &p)) {
                /* Loading into the editor is deliberate; Apply is the activation step. */
                p.bypass = ui.draft.bypass; /* ON/OFF is live state, not part of the edit */
                ui.draft = p;
                ui.dirty = 1;
                ui.screen = HOME;
                snprintf(ui.name, sizeof(ui.name), "%.*s", (int)strlen(ui.names[id]) - 4, ui.names[id]);
                snprintf(ui.status, sizeof(ui.status), "Loaded %s; choose Apply to activate", ui.name);
            } else snprintf(ui.status, sizeof(ui.status), "Cannot read preset; settings unchanged");
        }
    }
    if (id >= ENABLE && id < STEP) ui.dirty = 1; /* band edits: ENABLE, TYPE, FREQ_DOWN..Q_UP */
    if (!ui.timer) ui.timer = timer_add(render, 0, 1);
    return 0;
}

static int render(const void *unused) {
    (void)unused;
    ui.timer = 0;
    if (!ui.page) return 7;
    int selection = 0, offset = 0;
    if (ui.view && ui.rendered == ui.screen) {
        selection = widget_get_prop_int(ui.view, "_ringnav_index", 0);
        offset = widget_get_prop_int(ui.view, "yoffset", 0);
    }
    ui.rendered = ui.screen;
    int height = widget_get_prop_int(ui.page, "h", 320);
    /* Whole rows only, so the last row is never clipped. */
    int rows = (height - 48) / 48 * 48;
    widget_destroy_children(ui.page);
    void *list = list_view_create(ui.page, 0, 48, 375, rows);
    widget_set_prop_int(list, "item_height", 48);
    void *view = scroll_view_create(list, 0, 0, 375, rows);
    ui.view = view;
    widget_set_prop_int(view, "yslidable", 1);
    widget_set_prop_int(view, "xslidable", 0);
    widget_set_prop_int(view, "_ringnav_index", selection);
    char text[160];
    int n = 0;
    /* No Back row: Return steps back on every screen (keyup). */
    if (ui.screen == HOME) {
        row(view, n++, ui.dirty ? "Apply changes" : "Nothing to apply", ui.dirty ? APPLY : -1);
        row(view, n++, ui.draft.bypass ? "PEQ: OFF" : "PEQ: ON", BYPASS);
        /* Display only: the preamp comes from the loaded preset; -1 matches no action. */
        snprintf(text, sizeof(text), "Preamp %.1f dB", ui.draft.preamp); row(view, n++, text, -1);
        row(view, n++, "Presets", MENU);
        for (int i = 0; i < PEQ_BANDS; ++i) {
            peq_band *b = &ui.draft.bands[i];
            snprintf(text, sizeof(text), "%d %s %s %.0fHz %+.1fdB Q%.2f", i+1,
                     b->enabled ? "ON" : "OFF", b->type == 0 ? "PK" : b->type == 1 ? "LS" : "HS",
                     b->frequency, b->gain, b->q);
            row(view, n++, text, i);
        }
    } else if (ui.screen == BAND) {
        peq_band *b = &ui.draft.bands[ui.band];
        /* Imported missing bands already have valid defaults from peq_default. */
        if (ui.draft.count <= ui.band) ui.draft.count = ui.band + 1;
        row(view, n++, b->enabled ? "Band: ON" : "Band: OFF", ENABLE);
        row(view, n++, b->type == 0 ? "Type: Peaking" : b->type == 1 ? "Type: Low shelf" : "Type: High shelf", TYPE);
        snprintf(text, sizeof(text), "Frequency step: %d Hz", steps[ui.step]); row(view, n++, text, STEP);
        snprintf(text, sizeof(text), "Frequency %.0f Hz: lower", b->frequency); row(view, n++, text, FREQ_DOWN);
        row(view, n++, "Raise frequency", FREQ_UP);
        snprintf(text, sizeof(text), "Gain %.1f dB: lower 0.5", b->gain); row(view, n++, text, GAIN_DOWN);
        row(view, n++, "Raise gain 0.5 dB", GAIN_UP);
        snprintf(text, sizeof(text), "Q %.2f: lower 0.05", b->q); row(view, n++, text, Q_DOWN);
        row(view, n++, "Raise Q 0.05", Q_UP);
    } else if (ui.screen == CONFIRM) {
        row(view, n++, "Replace existing preset? Confirm", YES);
        row(view, n++, "Cancel replacement", CANCEL);
    } else if (ui.screen == SAVES) {
        for (int i = 0; i < 10; ++i) {
            snprintf(text, sizeof(text), "Save as Manual %02d", i+1); row(view, n++, text, i);
        }
    } else {
        if (ui.screen == PRESETS) {
            row(view, n++, "Import from SD /EQ", IMPORT);
            row(view, n++, "Save editor preset", SAVE);
        }
        list_files(ui.screen == IMPORTS ? PEQ_IMPORT : PEQ_SAVED, ui.screen == IMPORTS ? ".txt" : ".peq");
        for (int i = 0; i < ui.count; ++i) row(view, n++, ui.names[i], i);
    }
    widget_set_prop_int(view, "virtual_h", n * 48);
    if (n * 48 < rows) { /* short lists: shrink so the list's white background never shows below the rows */
        widget_resize(list, 375, n * 48);
        widget_resize(view, 375, n * 48);
    }
    scroll_view_set_offset(view, 0, offset);
    /* A message takes the title bar until the next action, so it never shrinks the list. */
    void *title = label_create(ui.page, 8, 0, 359, 48);
    widget_use_style(title, "s_label_white20c");
    widget_set_prop_int(title, "line_wrap", 1);
    if (ui.status[0]) snprintf(text, sizeof(text), "%s", ui.status);
    else if (ui.screen == BAND) snprintf(text, sizeof(text), "PEQ Band %d", ui.band + 1);
    else snprintf(text, sizeof(text), ui.name[0] ? "PEQ: %s" : "PEQ", ui.name);
    widget_set_text_utf8(title, text);
    widget_invalidate_force(ui.page, 0);
    return 7; /* RET_REMOVE */
}

/* Replaces the stock page's on_common_keyup: Return steps back one screen. */
static int keyup(void *ctx, void *event) {
    if (*(int *)((char *)event + EVENT_KEY) != KEY_RETURN) return 0;
    action((void *)(long)BACK, ctx);
    return 11; /* RET_STOP */
}

static int closed(void *ctx, void *event) {
    (void)ctx; (void)event;
    if (ui.timer) timer_remove(ui.timer);
    ui.timer = 0;
    ui.page = 0;
    ui.view = 0;
    free(ui.names);
    ui.names = 0;
    return 0;
}

int peq_page_init(void *page, void *context) {
    (void)context;
    if (!page) return 16;
    ui.page = page;
    ui.view = 0;
    ui.screen = HOME;
    ui.status[0] = 0;
    ui.dirty = 0;
    memcpy(ui.name, ui.active_name, sizeof(ui.name));
    peq_load_active(&ui.draft);
    widget_on(page, EVT_DESTROY, closed, 0);
    widget_on(page, EVT_KEY_UP, keyup, 0);
    render(0);
    return 0;
}
