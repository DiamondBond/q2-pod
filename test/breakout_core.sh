#!/bin/sh
set -eu
tmp="${TMPDIR:-/tmp}/q2-breakout-$$"
trap 'rm -f "$tmp"' EXIT HUP INT TERM
cc -std=c11 -O2 -Wall -Wextra -Werror -pedantic \
    patch/breakout_core.c test/breakout_core_test.c -o "$tmp"
"$tmp"
