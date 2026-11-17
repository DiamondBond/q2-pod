#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
out="$(mktemp)"
trap 'rm -f "$out"' EXIT HUP INT TERM
cc -std=c11 -O1 -g -Wall -Wextra -Werror -pedantic -fsanitize=undefined \
    patch/tile2048.c test/tile2048_test.c -o "$out"
"$out"
