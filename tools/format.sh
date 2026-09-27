#!/bin/sh
# Format patch/ringnav.c and the Markdown docs. patch/trampoline.S, patch/link.ld and
# patch/contexts.inc have no usable formatter and are deliberately absent.
set -eu
cd "$(dirname "$0")/.."

clang-format -i patch/ringnav.c
prettier --write "*.md" "docs/*.md"
