#!/usr/bin/env python3
"""Check Windows-hosted MIPS compiler command construction on Linux CI."""
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import arcade_mips

obj = Path("C:/Temp/arcade.o")
elf = Path("C:/Temp/arcade.elf")
with patch.object(arcade_mips, "use_wsl_compiler", return_value=True), \
     patch.object(arcade_mips, "wsl_path", side_effect=(
         "/mnt/c/Github/q2-pod/emulation/arcade_payload.c",
         "/mnt/c/Temp/arcade.o", "/mnt/c/Temp/arcade.elf")):
    compile_cmd, link_cmd = arcade_mips.compiler_commands(obj, elf, ["--target=mipsel-linux-gnu"])
assert compile_cmd[:3] == ["wsl.exe", "--exec", "clang"]
assert compile_cmd[-2:] == ["-o", "/mnt/c/Temp/arcade.o"]
assert link_cmd[:3] == ["wsl.exe", "--exec", "ld.lld"]
assert link_cmd[-2:] == ["-o", "/mnt/c/Temp/arcade.elf"]
print("Windows MIPS WSL compiler routing passed")
