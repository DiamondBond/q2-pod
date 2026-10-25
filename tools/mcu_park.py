#!/usr/bin/env python3
"""Pinned prototype MCU patch for cooperative PWM clock gating.

No device access. patch_image() rejects every image except the exact captured
stock file. It preserves the buzzer PCM/configuration and all stock bytes except
the two idle-wait hook instructions. The extra region occupies otherwise unused
TCSM above the stock initial stack. This does not itself disable any clock.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

STOCK_SHA256 = "c1dd1fb1099cf8335af11c83464031918e216b04c546e84c9549c60af7538943"
STOCK_SIZE = 0x3F88
HOOK_OFFSET = 0xF98
HOOK_WORDS = (0x8E423F8C, 0x1040FFFE)
RETURN_OFFSET = 0xFA0
HELPER_OFFSET = 0x6C00
PROTOCOL_OFFSET = 0x7F00
MCU_BASE = 0xF4000000
LINUX_BASE = 0xB3422000
MAGIC = 0x51505731
VERSION = 1
IMAGE_SIZE = PROTOCOL_OFFSET + 16
# Exact stock data descriptors begin at0x3cc8; do not compare mutable data/BSS.
STOCK_IMMUTABLE_END = 0x3CC8
SOURCE = Path(__file__).with_suffix(".S")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compile_helper() -> tuple[bytes, dict[str, int]]:
    """Build original assembly, returning actual instruction bytes and symbols."""
    commands = ["clang-18", "ld.lld-18", "llvm-objcopy-18", "llvm-nm-18"]
    missing = [name for name in commands if shutil.which(name) is None]
    if missing:
        raise RuntimeError("Missing assembler tools: " + ", ".join(missing))
    with tempfile.TemporaryDirectory(prefix="q2-mcu-park-") as directory:
        out = Path(directory)
        obj, elf, binary = (out / name for name in ("park.o", "park.elf", "park.bin"))
        subprocess.run([
            "clang-18", "--target=mipsel-none-elf", "-march=mips32r2",
            "-msoft-float", "-mno-abicalls", "-fno-pic",
            "-c", str(SOURCE), "-o", str(obj),
        ], check=True, capture_output=True)
        subprocess.run([
            "ld.lld-18", "-m", "elf32ltsmip", "-Ttext=0xf4006c00",
            "-e", "q2_pwm_idle", str(obj), "-o", str(elf),
        ], check=True, capture_output=True)
        subprocess.run([
            "llvm-objcopy-18", "-O", "binary", "--only-section=.text",
            str(elf), str(binary),
        ], check=True, capture_output=True)
        result = subprocess.run(["llvm-nm-18", "--defined-only", str(elf)],
                                check=True, capture_output=True, text=True)
        symbols = {}
        for line in result.stdout.splitlines():
            value, kind, name = line.split()
            if name.startswith("q2_pwm_"):
                symbols[name] = int(value, 16)
        data = binary.read_bytes()
    if not data or len(data) % 4 or HELPER_OFFSET + len(data) > PROTOCOL_OFFSET:
        raise ValueError("Helper exceeds reserved executable TCSM region")
    if symbols.get("q2_pwm_idle") != MCU_BASE + HELPER_OFFSET:
        raise ValueError("Unexpected helper link address")
    return data, symbols


def patch_image(stock: bytes, helper: bytes | None = None) -> bytes:
    """Return a patched image, failing closed on input/hash/pin mismatches."""
    if len(stock) != STOCK_SIZE or sha256(stock) != STOCK_SHA256:
        raise ValueError("Unsupported MCU image: exact stock length/hash required")
    if struct.unpack_from("<II", stock, HOOK_OFFSET) != HOOK_WORDS:
        raise ValueError("MCU idle hook instruction mismatch")
    if helper is None:
        helper, _ = compile_helper()
    if not helper or len(helper) % 4 or HELPER_OFFSET + len(helper) > PROTOCOL_OFFSET:
        raise ValueError("Invalid helper length")
    output = bytearray(stock)
    output.extend(bytes(IMAGE_SIZE - len(output)))
    jump = 0x08000000 | (((MCU_BASE + HELPER_OFFSET) >> 2) & 0x03FFFFFF)
    struct.pack_into("<II", output, HOOK_OFFSET, jump, 0)
    output[HELPER_OFFSET:HELPER_OFFSET + len(helper)] = helper
    struct.pack_into("<IIII", output, PROTOCOL_OFFSET, 0, 0, MAGIC, VERSION)
    return bytes(output)


def make_manifest(stock: bytes, patched: bytes, helper: bytes,
                  symbols: dict[str, int]) -> dict:
    immutable = [(0, STOCK_IMMUTABLE_END),
                 (HELPER_OFFSET, HELPER_OFFSET + len(helper)),
                 (PROTOCOL_OFFSET + 8, PROTOCOL_OFFSET + 16)]
    return {
        "purpose": "Prototype only; cooperative PWM park permission, no clock writes",
        "stock": {"sha256": sha256(stock), "size": len(stock)},
        "patched": {"sha256": sha256(patched), "size": len(patched)},
        "assembly": {"path": str(SOURCE), "sha256": sha256(SOURCE.read_bytes())},
        "helper": {"offset": HELPER_OFFSET, "size": len(helper),
                   "sha256": sha256(helper), "symbols": symbols},
        "hook": {"offset": HOOK_OFFSET, "stock_words": list(HOOK_WORDS),
                 "patched_words": list(struct.unpack_from("<II", patched, HOOK_OFFSET)),
                 "resume_offset": RETURN_OFFSET},
        "protocol": {
            "mcu_req": MCU_BASE + PROTOCOL_OFFSET,
            "mcu_ack": MCU_BASE + PROTOCOL_OFFSET + 4,
            "linux_req": LINUX_BASE + PROTOCOL_OFFSET,
            "linux_ack": LINUX_BASE + PROTOCOL_OFFSET + 4,
            "magic": MAGIC, "version": VERSION,
            "request_run": 0, "request_park": 1,
            "ack_run": 0, "ack_park": 1,
            "host_requirement": "Initialize REQ/ACK while reset asserted; serialize all MCU operations; acquire clocks before REQ=0; publish ring+doorbell before REQ=1; timeout retains clocks",
        },
        "immutable_ranges": [
            {"start": start, "end_exclusive": end,
             "sha256": sha256(patched[start:end])} for start, end in immutable
        ],
        "preserved_stock_ranges": [
            [0, HOOK_OFFSET], [HOOK_OFFSET + 8, STOCK_SIZE]
        ],
        "runtime_layout": {
            "stock_bss": [0x3F88, 0x4BA8],
            "initial_stack_offset": 0x6BA8,
            "helper_stack_bytes": 32,
            "ring_writer_offset": 0x3CE8,
            "ring_reader_offset": 0x3CEC,
            "mailbox_flag_offset": 0x3F8C,
            "irq_mask_address": 0x10001038,
            "pwm_irq_mask_bit": 6,
        },
        "limits": [
            "No physical clock or current measurements",
            "Requires paired Linux policy; unsafe to gate based only on a sampled idle flag",
            "Does not stop pre-existing PWM/DMA left active by reset or unsupported firmware",
            "No actual-device validation is implied by building this artifact",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stock", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    stock = args.stock.read_bytes()
    helper, symbols = compile_helper()
    patched = patch_image(stock, helper)
    args.output.write_bytes(patched)
    manifest = make_manifest(stock, patched, helper, symbols)
    manifest_path = args.manifest or args.output.with_suffix(".json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "manifest": str(manifest_path),
                      "sha256": sha256(patched), "bytes": len(patched),
                      "helper_bytes": len(helper)}, sort_keys=True))


if __name__ == "__main__":
    main()
