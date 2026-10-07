#!/usr/bin/env python3
"""Native check of the actual Xing parser, including seek bounds and CRC frames."""
from pathlib import Path
import subprocess
import tempfile

source = (Path(__file__).resolve().parents[1] / 'patch/peq_player.c').read_text()
start = source.index('int mp3_toc(')
parser = source[start:source.index('\n}\n', start) + 2]
check = r'''
#include <assert.h>
#include <math.h>
#include <string.h>
int main(void) {
    unsigned char h[192] = {0xff, 0xfb, 0x90, 0};
    memcpy(h + 36, "Xing\0\0\0\x07", 8);
    h[46] = 0x10; /* 4096 frames */
    for (int i = 0; i < 100; i++) h[52+i] = i * 2;
    double frac, length;
    assert(mp3_toc(h, sizeof h, 0, &frac, &length) && frac == 0);
    assert(mp3_toc(h, sizeof h, -1, &frac, &length) && frac == 0);
    assert(mp3_toc(h, sizeof h, length * 2, &frac, &length) && frac == 1);
    assert(!mp3_toc(h, sizeof h, NAN, &frac, &length));
    assert(!mp3_toc(h, sizeof h, INFINITY, &frac, &length));
    assert(mp3_toc(h, sizeof h, length / 2, &frac, &length));
    double half = frac;
    memmove(h + 38, h + 36, 116);
    h[1] &= ~1; /* CRC after the MPEG header */
    assert(mp3_toc(h, sizeof h, length / 2, &frac, &length) && frac == half);
    for (unsigned n = 0; n < 154; n++)
        assert(!mp3_toc(h, n, 0, &frac, &length));
    return 0;
}
'''
with tempfile.TemporaryDirectory() as tmp:
    src, exe = Path(tmp) / 'mp3.c', Path(tmp) / 'mp3'
    src.write_text('#include <string.h>\n' + parser + check)
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-fsanitize=undefined',
                    str(src), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('Xing seek bounds, nonfinite input, CRC and truncated headers: OK')
