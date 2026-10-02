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

enum { HOME, BAND, PRESETS, IMPORTS, SAVES, CONFIRM, DELETES, PICK, ADJUST };
enum { BACK = 1000, APPLY, BYPASS, MENU, IMPORT, SAVE, ENABLE, TYPE, RAISE, LOWER, TYPED, CHANNEL, STEP,
       YES, CANCEL, DELETE, BALANCE, PREAMP, GAIN, /* these three open the picker, in picks[] order */
       FREQUENCY, QUALITY, /* and these two the value menu */ KEYBOARD };
static struct {
    void *page, *view, *edit;
    unsigned timer;
    int screen, band, step, count, previous, rendered, dirty, pick, adjust, tries;
    double typed;
    peq_preset draft, candidate;
    char (*names)[256];
    char destination[600], status[160];
} ui __attribute__((section(".scratch")));

static const int steps[] = {1, 10, 100, 1000};
/* Wheel pickers in 0.5 dB rows: row i is first + step * i. Preamp's row 0 is Auto (first is unused there). */
static const struct { double first, step; int rows; } picks[] = {{-12, 0.5, 49}, {12.5, -0.5, 74}, {24, -0.5, 97}};
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

/* Preamp that keeps the combined response at or below 0 dB, as AutoEQ sets it: minus the peak
 * of |H| on a log grid from 20 Hz to 20 kHz at 48 kHz. ponytail: 1024 points (0.7% apart); a very
 * narrow boost between two can read a little low, refine around the best point if that matters. */
static double headroom(const peq_preset *p) {
    peq_engine e;
    if (!peq_compile(p, 48000, &e)) return p->preamp; /* preamp only sets e.gain, unused here */
    double peak = 1;
    for (int k = 0; k < 1024; ++k) {
        double w = 6.283185307179586 * 20 * pow(1000, k / 1023.0) / 48000, l = 1, r = 1;
        double c1 = cos(w), s1 = sin(w), c2 = 2 * c1 * c1 - 1, s2 = 2 * s1 * c1;
        for (int i = 0; i < PEQ_BANDS; ++i) {
            const peq_coeff *q = &e.c[i];
            double nr = q->b0 + q->b1 * c1 + q->b2 * c2, ni = q->b1 * s1 + q->b2 * s2;
            double dr = 1 + q->a1 * c1 + q->a2 * c2, di = q->a1 * s1 + q->a2 * s2;
            double m = (nr * nr + ni * ni) / (dr * dr + di * di);
            if (e.only[i] != 2) l *= m; /* only: 1 left, 2 right */
            if (e.only[i] != 1) r *= m;
        }
        if (l > peak) peak = l;
        if (r > peak) peak = r;
    }
    double gain = -10 * log(peak) / 2.302585092994046; /* power ratio to dB */
    return peak == 1 ? 0 : gain < -60 ? -60 : gain; /* no boost: +0, not -0.0 on screen */
}

static double *picked(void) {
    return (double *[]){&ui.draft.balance, &ui.draft.preamp, &ui.draft.bands[ui.band].gain}[ui.pick - BALANCE];
}

/* The value menu's edit closed with new text: apply it if it is a number (clamped like Raise/Lower), else restore it. */
static int typed(void *ctx, void *event) {
    (void)ctx; (void)event;
    const unsigned *t = ui.edit ? widget_get_text(ui.edit) : 0; /* wchar_t */
    char s[16];
    unsigned n = 0;
    while (t && t[n] && n < sizeof(s) - 1) { s[n] = (char)t[n]; ++n; }
    s[n] = 0;
    if (peq_number(s, &ui.typed)) action((void *)(long)TYPED, 0);
    else if (!ui.timer) ui.timer = timer_add(render, 0, 1); /* show the value again */
    return 0;
}

/* The T9 keyboard opens on its letters; a value only needs its "123" page (symnum). The keyboard can open a
 * moment after the focus, so look for its window every 16 ms, up to 20 times. */
static int numbers(const void *unused) {
    (void)unused;
    void *kb = widget_lookup(window_manager(), "kb_default_t9", 0);
    if (kb) pages_set_active_by_name(widget_lookup(kb, "panel", 1), "symnum");
    return kb || ++ui.tries >= 20 ? 7 : 8; /* RET_REMOVE, else RET_REPEAT */
}

static int focused(void *ctx, void *event) {
    (void)ctx; (void)event;
    ui.tries = 0;
    timer_add(numbers, 0, 16);
    return 0;
}

/* An edit styled and keyed as the stock playlist dialogs' (T9 keyboard, opening on its 123 page): the value
 * menu's, and iPod's custom accent colour (ringnav.c). Its action text is "done", as stock edit_on_event only
 * acts on the keyboard's OK for "done" (close the keyboard, then EVT_VALUE_CHANGED) or "next"; the dialogs'
 * "OK" is handled by their own EVT_IM_ACTION handlers. The keyboard's OK key shows an image, not the text. */
void *peq_edit(void *parent, int x, int y, int w, int h, const char *input_type) {
    void *edit = widget_factory_create_widget(widget_factory(), "edit", parent, x, y, w, h);
    static const char *const props[][2] = {{"keyboard", "kb_default_t9"}, {"input_type", 0}, {"action_text", "done"},
        {"bg_color", "#2B2B2B"}, {"border_color", "#2B2B2B00"}, {"text_color", "#FFFFFF"}, {"round_radius", "20"},
        {"margin_left", "12"}, {"font_size", "22"}};
    static const char *const states[] = {"normal", "focused", "empty", "empty_focus", "changed", "error", "over", "empty_over"};
    char name[40];
    for (unsigned i = 0; i < sizeof(props) / sizeof(props[0]); ++i) {
        if (i < 3) { widget_set_prop_str(edit, props[i][0], i == 1 ? input_type : props[i][1]); continue; }
        for (unsigned j = 0; j < sizeof(states) / sizeof(states[0]); ++j) {
            snprintf(name, sizeof(name), "style:%s:%s", states[j], props[i][0]);
            widget_set_prop_str(edit, name, props[i][1]);
        }
    }
    widget_on(edit, EVT_FOCUS, focused, 0);
    return edit;
}

static int on_auto(void) { return __builtin_fabs(ui.draft.preamp - headroom(&ui.draft)) < 0.05; }

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
    if (!ui.count && !ui.status[0]) snprintf(ui.status, sizeof(ui.status), "No presets found");
}

/* File name in ui.destination: sizeof skips PEQ_SAVED and its "/". */
static const char *deleting(void) { return ui.destination + sizeof(PEQ_SAVED); }

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
    /* The centre button on the value row; no render, which would destroy the edit and close the keyboard. */
    if (id == KEYBOARD) { widget_set_focused(ui.edit, 1); return 0; }
    peq_band *b = &ui.draft.bands[ui.band];
    ui.status[0] = 0;
    /* Band edits keep the preamp on Auto (just enough cut for the boosts) only if it was there. */
    int edit = (id >= ENABLE && id < STEP) || (id < 256 && ui.screen == PICK && ui.pick == GAIN);
    int automatic = edit && on_auto();
    if (id == BACK) {
        if (ui.screen == HOME) { navigator_back(); return 0; }
        if (ui.screen == PICK) ui.screen = ui.pick == GAIN ? BAND : HOME;
        else if (ui.screen == ADJUST) ui.screen = BAND;
        else ui.screen = ui.screen == BAND || ui.screen == PRESETS ? HOME : PRESETS;
    } else if (id == MENU) ui.screen = PRESETS;
    else if (id == IMPORT) ui.screen = IMPORTS;
    else if (id == DELETE) ui.screen = DELETES;
    else if (id >= BALANCE && id <= GAIN) { ui.pick = id; ui.screen = PICK; }
    else if (id == FREQUENCY || id == QUALITY) { ui.adjust = id; ui.screen = ADJUST; }
    else if (id == SAVE) ui.screen = SAVES;
    else if (id == BYPASS) {
        /* Takes effect at once and keeps unapplied band edits out of the active preset. */
        peq_preset active;
        peq_load_active(&active);
        active.bypass = !ui.draft.bypass;
        if (peq_save(PEQ_ACTIVE, &active, 1) == 1) {
            ui.draft.bypass = active.bypass;
            /* The stock switch's config key: boot instantiates the filter only when it is set. */
            write_int_config(!active.bypass, "PLAYSET", "EQFLAG");
            peq_stock_eq(1);
        } else snprintf(ui.status, sizeof(ui.status), "Switch failed; PEQ unchanged");
    }
    else if (id == ENABLE) b->enabled = !b->enabled;
    else if (id == TYPE) b->type = (b->type + 1) % 3;
    else if (id == CHANNEL && b->enabled) b->enabled = b->enabled % 3 + 1; /* both, left, right */
    else if (id == STEP) ui.step = (ui.step + 1) % 4;
    else if (id == RAISE || id == LOWER || id == TYPED) {
        int k = ui.adjust == QUALITY;
        double *value = k ? &b->q : &b->frequency, step = k ? 0.05 : steps[ui.step];
        *value = id == TYPED ? ui.typed : *value + (id == RAISE ? step : -step);
        if (*value < (k ? 0.1 : 20)) *value = k ? 0.1 : 20;
        if (*value > (k ? 10 : 20000)) *value = k ? 10 : 20000;
    } else if (id == APPLY) {
        if (peq_save(PEQ_ACTIVE, &ui.draft, 1) == 1) {
            peq_stock_eq(1);
            ui.dirty = 0;
            snprintf(ui.status, sizeof(ui.status), "Applied");
        } else snprintf(ui.status, sizeof(ui.status), "Apply failed; active EQ unchanged");
    } else if (id == YES) {
        ui.screen = ui.previous;
        if (ui.screen != DELETES) save_candidate(1);
        /* Saved presets are copies; the active EQ and the editor draft are untouched. */
        else if (unlink(ui.destination)) snprintf(ui.status, sizeof(ui.status), "Delete failed; preset kept");
        else snprintf(ui.status, sizeof(ui.status), "Deleted %.100s; active EQ unchanged", deleting());
    } else if (id == CANCEL) ui.screen = ui.previous;
    else if (id < 256) {
        if (ui.screen == HOME && id < PEQ_BANDS) { ui.band = id; ui.screen = BAND; }
        else if (ui.screen == PICK && id < picks[ui.pick - BALANCE].rows) {
            /* Preamp's Auto row: the band-edit cut, which later band edits then keep up to date. */
            *picked() = ui.pick == PREAMP && !id ? headroom(&ui.draft) : picks[ui.pick - BALANCE].first + picks[ui.pick - BALANCE].step * id;
            if (ui.pick == GAIN && !b->enabled) b->enabled = 1; /* picking a gain is using the band */
            ui.dirty = 1;
            ui.screen = ui.pick == GAIN ? BAND : HOME;
        }
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
        } else if (id < ui.count && ui.screen == DELETES) {
            snprintf(ui.destination, sizeof(ui.destination), PEQ_SAVED "/%s", ui.names[id]);
            ui.previous = DELETES;
            ui.screen = CONFIRM;
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
                snprintf(ui.status, sizeof(ui.status), "Preset loaded; choose Apply to activate");
            } else snprintf(ui.status, sizeof(ui.status), "Cannot read preset; settings unchanged");
        }
    }
    if (edit) { /* ENABLE, TYPE, RAISE, LOWER, TYPED, CHANNEL and a picked gain */
        ui.dirty = 1;
        if (automatic) ui.draft.preamp = headroom(&ui.draft);
    }
    if (!ui.timer) ui.timer = timer_add(render, 0, 1);
    return 0;
}

static int render(const void *unused) {
    (void)unused;
    ui.timer = 0;
    if (!ui.page) return 7;
    int selection = 0, offset = 0;
    int height = widget_get_prop_int(ui.page, "h", 320);
    /* Whole rows only, so the last row is never clipped. */
    int rows = (height - 48) / 48 * 48;
    if (ui.view && ui.rendered == ui.screen) {
        selection = widget_get_prop_int(ui.view, "_ringnav_index", 0);
        offset = widget_get_prop_int(ui.view, "yoffset", 0);
    } else if (ui.screen == PICK) { /* opens on the nearest row to the current value (Auto if on it), centred */
        int last = picks[ui.pick - BALANCE].rows - 1;
        double r = (*picked() - picks[ui.pick - BALANCE].first) / picks[ui.pick - BALANCE].step + 0.5;
        selection = r < 0 ? 0 : r > last ? last : (int)r;
        if (ui.pick == PREAMP && on_auto()) selection = 0;
        else if (ui.pick == PREAMP && !selection) selection = 1;
        offset = selection * 48 - (rows - 48) / 2;
        offset = offset < 0 ? 0 : offset > (last + 1) * 48 - rows ? (last + 1) * 48 - rows : offset;
    }
    ui.rendered = ui.screen;
    ui.edit = 0;
    widget_destroy_children(ui.page);
    void *list = list_view_create(ui.page, 0, 48, 375, rows);
    widget_set_prop_int(list, "item_height", 48);
    /* The theme's default list_view is a light card; stock pages paint theirs black inline. */
    widget_set_prop_int(list, "style:normal:bg_color", (int)0xff000000u);
    widget_set_prop_int(list, "style:normal:border_color", 0);
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
        snprintf(text, sizeof(text), "Preamp %.1f dB", ui.draft.preamp); row(view, n++, text, PREAMP);
        /* Balance turns one side down: R 1.0 dB is the left 1 dB quieter. */
        snprintf(text, sizeof(text), __builtin_fabs(ui.draft.balance) >= 0.05 ? "Balance: %s %.1f dB" : "Balance: Centre",
                 ui.draft.balance > 0 ? "R" : "L", __builtin_fabs(ui.draft.balance));
        row(view, n++, text, BALANCE);
        row(view, n++, "Presets", MENU);
        /* Ten rows, then one spare past the last used band to add another. */
        for (int i = 0; i < PEQ_BANDS && (i < 10 || i <= ui.draft.count); ++i) {
            peq_band *b = &ui.draft.bands[i];
            snprintf(text, sizeof(text), "%d %s %s %.0fHz %+.1fdB Q%.2f", i+1,
                     (const char *[]){"OFF", "ON", "ON L", "ON R"}[b->enabled], b->type == 0 ? "PK" : b->type == 1 ? "LS" : "HS",
                     b->frequency, b->gain, b->q);
            row(view, n++, text, i);
        }
    } else if (ui.screen == BAND) {
        peq_band *b = &ui.draft.bands[ui.band];
        /* Imported missing bands already have valid defaults from peq_default. */
        if (ui.draft.count <= ui.band) ui.draft.count = ui.band + 1;
        row(view, n++, b->enabled ? "Band: ON" : "Band: OFF", ENABLE);
        if (b->enabled) row(view, n++, (const char *[]){0, "Channels: Both", "Channels: Left", "Channels: Right"}[b->enabled], CHANNEL);
        row(view, n++, b->type == 0 ? "Type: Peaking" : b->type == 1 ? "Type: Low shelf" : "Type: High shelf", TYPE);
        snprintf(text, sizeof(text), "Frequency %.0f Hz", b->frequency); row(view, n++, text, FREQUENCY);
        snprintf(text, sizeof(text), "Gain %+.1f dB", b->gain); row(view, n++, text, GAIN);
        snprintf(text, sizeof(text), "Q %.2f", b->q); row(view, n++, text, QUALITY);
    } else if (ui.screen == ADJUST) {
        /* Row 0 is the value in an edit (peq_edit); a tap or the centre button opens the keyboard and the value
         * applies when it closes. */
        void *item = list_item_create(view, 0, 0, 375, 48);
        widget_use_style(item, "s_listitem_black");
        widget_on(item, EVT_CLICK, action, (void *)(long)KEYBOARD);
        ui.edit = peq_edit(item, 12, 4, 351, 40, "ufloat");
        peq_band *b = &ui.draft.bands[ui.band];
        snprintf(text, sizeof(text), ui.adjust == QUALITY ? "%.2f" : "%.0f", ui.adjust == QUALITY ? b->q : b->frequency);
        widget_set_text_utf8(ui.edit, text);
        widget_on(ui.edit, EVT_VALUE_CHANGED, typed, 0);
        n = 1;
        if (ui.adjust == QUALITY) { row(view, n++, "Raise 0.05", RAISE); row(view, n++, "Lower 0.05", LOWER); }
        else {
            snprintf(text, sizeof(text), "Raise %d Hz", steps[ui.step]); row(view, n++, text, RAISE);
            snprintf(text, sizeof(text), "Lower %d Hz", steps[ui.step]); row(view, n++, text, LOWER);
            snprintf(text, sizeof(text), "Step: %d Hz", steps[ui.step]); row(view, n++, text, STEP);
        }
    } else if (ui.screen == PICK) {
        for (int i = 0; i < picks[ui.pick - BALANCE].rows; ++i) {
            double v = picks[ui.pick - BALANCE].first + picks[ui.pick - BALANCE].step * i;
            if (ui.pick == BALANCE) /* L 12.0 dB to R 12.0 dB */
                snprintf(text, sizeof(text), i == 24 ? "Centre" : "%s %.1f dB", v < 0 ? "L" : "R", __builtin_fabs(v));
            else if (ui.pick == PREAMP && !i) snprintf(text, sizeof(text), "Auto (%.1f dB)", headroom(&ui.draft));
            else snprintf(text, sizeof(text), "%+.1f dB", v);
            row(view, n++, text, i);
        }
    } else if (ui.screen == CONFIRM && ui.previous == DELETES) {
        snprintf(text, sizeof(text), "Delete %.100s? Confirm", deleting()); row(view, n++, text, YES);
        row(view, n++, "Cancel", CANCEL);
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
            row(view, n++, "Delete a preset", DELETE);
        }
        list_files(ui.screen == IMPORTS ? PEQ_IMPORT : PEQ_SAVED, ui.screen == IMPORTS ? ".txt" : ".peq");
        for (int i = 0; i < ui.count; ++i) row(view, n++, ui.names[i], i);
    }
    widget_set_prop_int(view, "virtual_h", n * 48);
    /* ringnav keeps the selection above on a view whose row count it already knows. */
    if (ui.screen == PICK) widget_set_prop_int(view, "_ringnav_count", n);
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
    else if (ui.screen == ADJUST) snprintf(text, sizeof(text), ui.adjust == QUALITY ? "PEQ Band %d Q" : "PEQ Band %d Frequency (Hz)", ui.band + 1);
    else if (ui.screen == PICK && ui.pick == GAIN) snprintf(text, sizeof(text), "PEQ Band %d Gain", ui.band + 1);
    else if (ui.screen == PICK) snprintf(text, sizeof(text), ui.pick == PREAMP ? "PEQ Preamp" : "PEQ Balance");
    else snprintf(text, sizeof(text), "PEQ");
    widget_set_text_utf8(title, text);
    widget_invalidate_force(ui.page, 0);
    return 7; /* RET_REMOVE */
}

/* Replaces the stock page's on_common_keyup: Return steps back one screen. */
static int keyup(void *ctx, void *event) {
    if (I(event, EVENT_KEY) != KEY_RETURN) return 0;
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
    peq_load_active(&ui.draft);
    /* Boot instantiates the filter only when the switch left PLAYSET/EQFLAG set; the flag
     * then follows the active preset's bypass (peq_stock_eq). */
    ui.draft.bypass = !g_equalizer_flag;
    widget_on(page, EVT_DESTROY, closed, 0);
    widget_on(page, EVT_KEY_UP, keyup, 0);
    render(0);
    return 0;
}
