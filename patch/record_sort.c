/* The name sorts' moves (tools/build.py RECORD_SORTS): stock's three library queries hand their
 * list to libcstl's algo_sort_if, which moves every stSongInfo by the type's copy: each move frees
 * the strings it lands on and duplicates the ones it takes, and each swap allocates and frees a
 * spare row. A row owns its strings and nothing points into it (REC_SIZE), so its 88 bytes moved
 * whole are the same row. This is libcstl 2.2.0's algo_sort_if step for step: the same questions of
 * the same rows in the same order, the same moves, each a copy of the bytes, and nothing allocated
 * or freed. Stock's scans and its insertion sort's walk stop only on the comparator's answers (a
 * pivot not before itself, answers that repeat); here they also stop at the list's ends, which only
 * a comparator that has stock read outside the list reaches. Anything else (another type, a part of
 * a deque) is stock's, untouched. */
#include "navigation.h"

typedef void (*row_less)(const void *, const void *, unsigned *);
typedef struct {
    void *w[7]; /* libcstl's iterator by value: the element, its block, the block's end, its map
                   slot, the deque, ... */
} row_it;

#define SPARE (~0u) /* the row an insertion places, or the pivot: libcstl's spare */
struct rows {
    void *deque;
    row_less less;
    unsigned n;
    unsigned spare[REC_SIZE / 4],
        swap[REC_SIZE / 4]; /* and a swap's, which libcstl's algo_iter_swap allocates */
};

static void *row(struct rows *s, unsigned i) {
    return i == SPARE ? (void *)s->spare : deque_at(s->deque, i);
}
/* Whether row a comes before row b. r is the asking routine's answer word, cleared once on its
 * entry, as libcstl's: a comparator that leaves it alone answers what it last held. */
__attribute__((noinline)) static int before(struct rows *s, unsigned a, unsigned b, unsigned *r) {
    s->less(row(s, a), row(s, b), r);
    return *r != 0;
}
__attribute__((noinline)) static void move(struct rows *s, unsigned to, unsigned from) {
    memcpy(row(s, to), row(s, from), REC_SIZE);
}
/* algo_iter_swap: nothing for one row */
static void swap(struct rows *s, unsigned a, unsigned b) {
    if (a == b) return;
    void *x = row(s, a), *y = row(s, b);
    memcpy(s->swap, x, REC_SIZE);
    memcpy(x, y, REC_SIZE);
    memcpy(y, s->swap, REC_SIZE);
}

/* _algo_insertion_sort_if, for 200 rows or fewer */
static void insertion(struct rows *s, unsigned n) {
    unsigned r = 0;
    for (unsigned b = 1; b < n; ++b) {
        move(s, SPARE, b);
        if (before(s, SPARE, 0, &r)) {
            for (unsigned k = b; k; --k) move(s, k, k - 1);
            move(s, 0, SPARE);
            continue;
        }
        unsigned at = b;
        /* the first row said not before: reached only by an answer that changed when asked again */
        while (before(s, SPARE, at - 1, &r)) {
            move(s, at, at - 1);
            if (!--at) break;
        }
        move(s, at, SPARE);
    }
}

/* _algo_median_of_three_if: one of the three */
static unsigned median(struct rows *s, unsigned a, unsigned b, unsigned c) {
    unsigned r = 0;
    if (before(s, a, b, &r)) return before(s, b, c, &r) ? b : before(s, a, c, &r) ? c : a;
    return before(s, a, c, &r) ? a : before(s, b, c, &r) ? c : b;
}

/* _algo_adjust_heap: the row at i, of the heap of n rows at from, sifts down by swaps */
static void sift(struct rows *s, unsigned from, unsigned n, unsigned i) {
    unsigned r = 0;
    for (unsigned l = 2 * i + 1; l < n; l = 2 * i + 1) {
        unsigned c = l + 1 < n && !before(s, from + l + 1, from + l, &r) ? l + 1 : l;
        if (before(s, from + c, from + i, &r)) return;
        swap(s, from + i, from + c);
        i = c;
    }
}
/* algo_partial_sort_if(first, last, last): algo_make_heap_if, then algo_sort_heap_if */
static void heap(struct rows *s, unsigned from, unsigned to) {
    unsigned n = to - from;
    for (unsigned p = n >= 2 ? n / 2 : 0; p--;) sift(s, from, n, p);
    for (; n; --n) swap(s, from, from + n - 1), sift(s, from, n - 1, 0);
}

/* _algo_intro_sort_if: down to one row, the depth limit's heap sort below it; stock's second call,
 * for the right part, is the loop. A range's size is signed, as iterator_distance's: a scan that
 * passed its range's end (answers that did not repeat) leaves an empty right part, as in stock. */
static void intro(struct rows *s, unsigned first, unsigned last, unsigned depth) {
    while ((int)(last - first) >= 2) {
        unsigned r = 0, b = first, e = last;
        if (!depth) {
            heap(s, first, last);
            return;
        }
        --depth;
        /* the pivot: its row's bytes, compared and never written back, so its strings stay that
         * row's */
        move(s, SPARE, median(s, first, first + (last - first) / 2, last - 1));
        for (;;) {
            while (b < s->n && before(s, b, SPARE, &r)) ++b;
            do --e;
            while (before(s, SPARE, e, &r) && e);
            if (b >= e) break;
            swap(s, b, e);
            ++b;
        }
        intro(s, first, b, depth);
        first = b;
    }
}

static unsigned lg(unsigned n) { /* _algo_lg: floor(log2 n) */
    unsigned k = 0;
    while (n >>= 1) ++k;
    return k;
}

/* Called as stock's algo_sort_if, at its three name-sorting calls. */
void ringnav_record_sort(row_it first, row_it last, row_less less) {
    struct rows s; /* its two rows are written before they are read */
    _Static_assert(sizeof s.spare == REC_SIZE && sizeof s.swap == REC_SIZE, "a whole row each");
    row_it b, e;
    const char *type;
    s.deque = first.w[4], s.less = less;
    if (!less || !s.deque || !(type = P(s.deque, DEQUE_TYPE))) goto stock;
    s.n = deque_size(s.deque), deque_begin(&b, s.deque), deque_end(&e, s.deque);
    if (I(type, 0) != REC_SIZE || strcmp(type + 4, "stSongInfo") || first.w[0] != b.w[0] ||
        first.w[3] != b.w[3] || last.w[0] != e.w[0] || last.w[3] != e.w[3])
        goto stock;
    if (s.n < 2) return;
    if (s.n <= 200)
        insertion(&s, s.n);
    else
        intro(&s, 0, s.n, 2 * lg(s.n));
    return;
stock: /* as stock calls it: nothing has moved */
    algo_sort_if(first.w[0], first.w[1], first.w[2], first.w[3], first.w[4], first.w[5], first.w[6],
                 last.w[0], last.w[1], last.w[2], last.w[3], last.w[4], last.w[5], last.w[6], less);
}
