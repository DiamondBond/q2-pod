#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
out="${TMPDIR:-/tmp}/q2-framework-test-$$"
trap 'rm -f "$out"' EXIT HUP INT TERM
cc -std=c11 -O2 -Wall -Wextra -Werror -pedantic patch/game_framework.c test/game_framework_test.c -o "$out"
"$out"
