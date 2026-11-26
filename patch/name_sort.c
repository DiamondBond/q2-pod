/* The library's name comparators, hooked at entry (HOOKS' library_name_cmp*). Keep stock's non-CJK
 * order (including numeric names and leading articles). A CJK-leading name sorts after those
 * names; two CJK names compare their UTF-8 bytes, which have Unicode code-point order (RFC 3629).
 * The rule needs no pinyin conversion, locale tables or per-comparison allocation.
 * ponytail: a name led by CJK punctuation or brackets stays in stock's place, folders keep stock's
 * own comparators, and Han names lose pinyin order (docs/internals.md#sorting). With a Chinese
 * language pack the comparators leave every pair to stock's order, pinyin and all. The pack's flag
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

/* A pair is answered here from each name's first NEAR bytes at most: stock compares 1 KB copies,
 * which a name's blanks, its article, these and a number's ten digits all fit in. */
#define NEAR 960
#define DIGIT(c) ((unsigned)(c) - '0' < 10)

/* Where a name sorts by its first byte, in stock's Chinese order (0x5cc870) and its Japanese one
 * (0x5cd188): the byte's range, then that range's place, lowest first. Two names of one place go
 * by strcasecmp, but for BY_STOCK, which reads them through its pinyin or kana tables (the Chinese
 * order sorts letters and Chinese characters as one place), and AS_IS, which the Japanese order
 * leaves as they are: two names that start with a digit. Stock's Chinese order puts a letter and
 * another byte above 0x7e in order by strcasecmp, which in the C locale, the Q2's only one, answers
 * as these places do. */
enum { BY_STOCK = 1, AS_IS = 2 };
#define PLACE(n, how) ((n) << 2 | (how))
/* one past each range: below '0', digits, : to @, A to Z, [ to `, a to z, { to ~, 0x7f to 0xdf,
 * 0xe0 (Thai), 0xe1 and 0xe2, 0xe3 (kana), 0xe4-0xe9 (Chinese), 0xea-0xec (Korean), the rest */
static const unsigned char RANGE_END[] = { '0',  ':',  'A',  '[',  'a',  '{', 0x7f,
                                           0xe0, 0xe1, 0xe3, 0xe4, 0xea, 0xed };
static const unsigned char PLACES[2][sizeof RANGE_END + 1] = {
    { PLACE(9, 0), PLACE(0, 0), PLACE(8, 0), PLACE(1, 0), PLACE(7, 0), PLACE(1, 0), PLACE(6, 0),
      PLACE(2, 0), PLACE(5, 0), PLACE(2, 0), PLACE(3, 0), PLACE(1, BY_STOCK), PLACE(4, 0),
      PLACE(2, 0) },
    { PLACE(8, 0), PLACE(4, AS_IS), PLACE(7, 0), PLACE(0, 0), PLACE(6, 0), PLACE(0, 0), PLACE(5, 0),
      PLACE(3, 0), PLACE(10, 0), PLACE(3, 0), PLACE(1, BY_STOCK), PLACE(2, BY_STOCK), PLACE(9, 0),
      PLACE(3, 0) },
};
static unsigned place(unsigned c, int jp) {
    unsigned k = 0;
    while (k < sizeof RANGE_END && c >= RANGE_END[k]) ++k;
    return PLACES[jp][k];
}

/* The text stock compares a record by: its name (+0x10) past the blanks toolsTrimLeft takes (tab,
 * line feed, return, space: its own test) and the article ringnav_sort_key drops, or, with nothing
 * left, its file name (+0x08) as it is. 0 when the name is missing or starts with more blanks than
 * NEAR allows for. */
static const unsigned char *name_key(const void *row) {
    const unsigned char *s = *(const unsigned char *const *)((const char *)row + 0x10);
    unsigned n = 0, c;
    if (!s) return 0;
    while (n < 24 && (c = s[n] - 9u) < 24 && (0x800013u >> c & 1)) ++n;
    if (n == 24) return 0;
    if (!s[n]) return *(const unsigned char *const *)((const char *)row + 8);
    return s + n + article((const char *)s + n);
}

/* atoi of a number's first ten digits, which is all stock takes of it */
static int name_number(const unsigned char *s) {
    char digits[11];
    unsigned n = 0;
    for (; n < 10 && DIGIT(s[n]); ++n) digits[n] = (char)s[n];
    digits[n] = 0;
    return atoi(digits);
}

/* Stock's order, for each pair sort_decided leaves to it: most pairs a name sort weighs. Each call
 * of stock's comparator copies both names into 1 KB buffers it has cleared, and looks for a number
 * in each with a strlen for every byte: about 6,000 instructions a pair of 16-byte names, 15,000
 * at 40 bytes. The answer is the same here from the records' own strings, read once as far as the
 * names differ. Stock's own body still answers the pairs its tables decide (BY_STOCK), a record
 * without a name, and a pair NEAR bytes don't settle. */
__attribute__((noinline)) static void name_less(void *ra, void *rb, unsigned *less, int jp) {
    unsigned ta = *(const unsigned *)((const char *)ra + 0x34),
             tb = *(const unsigned *)((const char *)rb + 0x34);
    const unsigned char *a = *(const unsigned char *const *)((const char *)ra + 0x10),
                        *b = *(const unsigned char *const *)((const char *)rb + 0x10);
    unsigned i = 0;
    if (ta + tb == 12 && (ta == 4 || ta == 8)) { /* record types 4 and 8: 4 first */
        *less = ta == 4;
        return;
    }
    if (!a || !b) goto stock;
    /* two Chinese names (0xe4 to 0xe9), or in the Japanese order two kana ones (0xe3), are stock's
     * to answer whatever follows: nothing more is read of them here */
    unsigned ca = a[0] - 0xe3u, cb = b[0] - 0xe3u;
    if (ca < 7 && cb < 7 && (jp ? !ca == !cb : ca && cb)) goto stock;
    if (!(a = name_key(ra)) || !(b = name_key(rb))) goto stock;
    while (i < NEAR && a[i] == b[i] && a[i] && !DIGIT(a[i])) ++i;
    if (i == NEAR) goto stock;
    if (i && DIGIT(a[i]) && DIGIT(b[i])) {
        /* the same text up to a number in each: by the numbers, "Track 2" before "Track 10" */
        int na = name_number(a + i), nb = name_number(b + i);
        if (na != nb) {
            *less = na < nb;
            return;
        }
    } else {
        unsigned pa = place(a[0], jp), pb = place(b[0], jp);
        if ((pa ^ pb) >> 2) {
            *less = pa < pb;
            return;
        }
        if ((pa | pb) & BY_STOCK) goto stock;
        if (pa & AS_IS) {
            *less = 0;
            return;
        }
    }
    /* strcasecmp(a, b) < 0, from where the names first differ */
    for (const int *lower = *__ctype_tolower_loc(); i < NEAR; ++i) {
        int x = lower[a[i]], y = lower[b[i]];
        if (x != y || !a[i]) {
            *less = x < y;
            return;
        }
    }
stock:
    (jp ? stock_name_cmp_trampoline : stock_name_cmp_pinyin_trampoline)(ra, rb, less);
}

/* libcstl's bool_t is size_t, a 32-bit word on the Q2. Both stock comparators have this ABI. */
void ringnav_name_cmp_pinyin(void *a, void *b, unsigned *out) {
    if (!sort_decided(a, b, out)) name_less(a, b, out, 0);
}
void ringnav_name_cmp(void *a, void *b, unsigned *out) {
    if (!sort_decided(a, b, out)) name_less(a, b, out, 1);
}
