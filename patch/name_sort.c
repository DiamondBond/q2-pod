/* The library's name comparators, hooked at entry (HOOKS' library_name_cmp*). Keep stock's non-CJK
 * order (including numeric names and leading articles). A CJK-leading name sorts after those
 * names; two CJK names compare their UTF-8 bytes, which have Unicode code-point order (RFC 3629).
 * No pinyin conversion, locale tables or per-comparison allocation.
 * ponytail: a name led by CJK punctuation or brackets stays in stock's place, folders keep stock's
 * own comparators, and Han names lose pinyin order (docs/internals.md#sorting). With a Chinese
 * language pack the comparators leave every pair to stock, pinyin order and all. The pack's flag
 * is read as it stands, 0 (the rule on) before the first text is asked for; the first is asked for
 * when Home is built, and lists open from Home. A language pick reboots, so it holds for a boot. */
#include "navigation.h"

/* What stock's toolsTrimLeft trims: tab, LF, CR and space. */
static const char *trimmed(const char *s) {
    if (!s) return "";
    while (*s == ' ' || *s == '\t' || *s == '\n' || *s == '\r') ++s;
    return s;
}

static const char *sort_name_start(const char *s) {
    s = trimmed(s);
    return s + article(s);
}

static unsigned sort_initial(const char *s) {
    const unsigned char *p = (const unsigned char *)s;
    unsigned c = *p++;
    if (c < 0x80) return c;
    if (c < 0xc2 || c > 0xf4) return 0;
    unsigned n = c < 0xe0 ? 1 : c < 0xf0 ? 2 : 3;
    unsigned min = n == 1 ? 0x80 : n == 2 ? 0x800 : 0x10000;
    c &= (1u << (6 - n)) - 1;
    while (n--) {
        if ((*p & 0xc0) != 0x80) return 0;
        c = (c << 6) | (*p++ & 0x3f);
    }
    return c >= min && c <= 0x10ffff && !(c >= 0xd800 && c <= 0xdfff) ? c : 0;
}

/* Han, kana, Bopomofo and Hangul blocks, including supplementary ideographs and halfwidth
 * kana. The script of the first character is all we know; a Romanized name stays in A-Z. */
static int sort_cjk_initial(const char *s) {
    unsigned c = sort_initial(s);
    return (c >= 0x1100 && c <= 0x11ff) || (c >= 0x2e80 && c <= 0x2fdf) || c == 0x3005 ||
           c == 0x3007 || (c >= 0x3031 && c <= 0x3035) || (c >= 0x3040 && c <= 0x318f) ||
           (c >= 0x31a0 && c <= 0x31bf) || (c >= 0x31f0 && c <= 0x31ff) ||
           (c >= 0x3400 && c <= 0x4dbf) || (c >= 0x4e00 && c <= 0x9fff) ||
           (c >= 0xa960 && c <= 0xa97f) || (c >= 0xac00 && c <= 0xd7ff) ||
           (c >= 0xf900 && c <= 0xfaff) || (c >= 0xff66 && c <= 0xffdc) ||
           (c >= 0x1aff0 && c <= 0x1b16f) || (c >= 0x20000 && c <= 0x2fa1f) ||
           (c >= 0x30000 && c <= 0x3347f);
}

/* -1 delegates to stock, 0/1 is the libcstl less-than result. */
static int sort_cjk_less(const char *a, const char *b) {
    a = sort_name_start(a);
    b = sort_name_start(b);
    int x = sort_cjk_initial(a), y = sort_cjk_initial(b);
    if (!x && !y) return -1;
    return x != y ? x < y : strcmp(a, b) < 0;
}

/* The name stock sorts a record by: its title, else its file name when the title is empty after
 * the trim. */
static const char *sort_record_name(void *r) {
    const char *s = P(r, REC_TITLE);
    return *trimmed(s) ? s : P(r, REC_NAME);
}

/* Sets *out and returns 1 when the two records' names decide it, 0 to leave it to stock. */
static int sort_decided(void *a, void *b, unsigned *out) {
    if (language_zh()) return 0;
    int less = sort_cjk_less(sort_record_name(a), sort_record_name(b));
    if (less >= 0) *out = (unsigned)less;
    return less >= 0;
}

extern void stock_name_cmp_pinyin_trampoline(void *, void *, unsigned *),
    stock_name_cmp_trampoline(void *, void *, unsigned *);

/* libcstl's bool_t is size_t, a 32-bit word on the Q2. Both stock comparators have this ABI. */
void ringnav_name_cmp_pinyin(void *a, void *b, unsigned *out) {
    if (!sort_decided(a, b, out)) stock_name_cmp_pinyin_trampoline(a, b, out);
}
void ringnav_name_cmp(void *a, void *b, unsigned *out) {
    if (!sort_decided(a, b, out)) stock_name_cmp_trampoline(a, b, out);
}
