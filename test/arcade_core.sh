#!/bin/sh
# Portable, host-only tests; does not require stock firmware or MIPS tools.
set -eu
cd "$(dirname "$0")/.."
out="${TMPDIR:-/tmp}/q2-arcade-test-$$"
trap 'rm -f "$out"' EXIT HUP INT TERM
cc -std=c11 -O2 -Wall -Wextra -Werror -pedantic patch/arcade_core.c test/arcade_core_test.c -o "$out"
"$out"
