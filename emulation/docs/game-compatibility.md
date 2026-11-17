# Generic built-in game discovery and runtime contract

## What the simulator actually executes

The desktop simulator is **not a universal Shanling Q2 machine emulator**.
It can load supported firmware assets and preview the user interface, but
its legacy arcade runner builds the C game rules **from the checked-out
repository**, not from the firmware package opened with `--firmware`.

Thus, opening an arbitrary firmware does **not** verify or execute the
original game's binary from that firmware. The simulator now labels this
distinction and explicitly reports when a firmware-listed game has no
compatible desktop runtime. Do not use an arcade preview as proof that a
different vendor's firmware implements a game in the same way.

## Generic discovery, without hardcoded game names

A Q2 Pod firmware may provide this UTF-8 JSON file inside its SquashFS
root filesystem at:

`release/assets/default/raw/q2pod-games.json`

Example:

```json
{
  "schema_version": 1,
  "games": [
    {"id": "sudoku", "name": "Sudoku"},
    {"id": "vortex", "name": "Vortex"},
    {"id": "minesweeper", "name": "Minesweeper"}
  ]
}
```

The simulator reads the manifest and enumerates all titles in their declared
order, without Python modifications for each new title. IDs must match
`[a-z][a-z0-9_-]{0,63}`; names must be 1–80 printable characters.
The parser checks unique IDs/names, schema version, count and file size.

This manifest is **metadata only**. A new game appears in the menu but is
not automatically executable merely because it is listed.

An **experimental standalone MIPS game ABI** now exists at
`emulation/abi/q2_game_abi.h`, with a generic Unicorn runner in
`emulation/universal_game.py`. A compliant guest exports
`q2g_version`, `q2g_name`, `q2g_init`, `q2g_input`, `q2g_step`,
and `q2g_render`, which returns a bounded host-neutral drawing-command
list. A new compliant game ELF can run **without adding Python gameplay
or rendering adapters**. This standalone ABI is not yet the firmware's
`game_framework` contract, and a firmware image does not yet embed or
export these guest ELFs.

For older firmware that does not contain the manifest, the simulator retains
legacy detection: the predefined game list plus a best-effort Breakout
signature test. This cannot discover an arbitrary new game and is not
a guaranteed inventory of the loaded firmware.

## Try the generic game runner

From the repository root on Linux with clang, ld.lld, Unicorn and Pillow:

```sh
clang --target=mipsel-linux-gnu -march=mips32r2 -mabi=32 -mfp64 -mno-abicalls -fno-pic -G0 -ffreestanding -fno-builtin -Oz -c emulation/abi/example_game.c -o /tmp/q2-example.o
ld.lld -m elf32ltsmip -static -Ttext=0x100000 -e q2g_version /tmp/q2-example.o -o /tmp/q2-example.elf
python3 emulation/universal_game.py --elf /tmp/q2-example.elf --self-test
python3 emulation/universal_game.py --elf /tmp/q2-example.elf
```

For a new standalone game, implement the six exported functions in one
C source file using the public ABI header. The host forwards button/wheel
events and fixed update steps and renders a list of generic drawing commands.
No new Python game-type checks, `ctypes` state layouts, custom rendering,
or explicit game-name dispatch should be necessary.

## Contributor contract (remaining work)

A universal runtime should be driven by an API version and a registry,
not by game names. A future implementation needs:

1. **Extend and stabilize the experimental ABI**: touch input, persistence,
   asset access, error reporting and firmware integration.
2. **Source registration and packaging**: build emits the manifest and
   game entry point table together, so the manifest cannot list missing code.
3. **Integrate runtime with firmware packages**: the generic runner already
   resolves compliant standalone ELFs, but the firmware loader must also
   securely locate and verify packaged game payloads.
4. **Compatibility checks**: unsupported API versions, missing exports or
   unavailable firmware services yield explicit errors rather than silently
   executing local checkout code.
5. **Tests**: one contract test suite should apply to every registered game.

Until full firmware integration is complete, the emulator remains a **partial simulator**, not a universal arbitrary-firmware emulator.
The `desktop-simulator` branch owns emulator-specific code; the
`new-builtin-games` branch owns firmware game rules and the portable C
framework.

## Testing discovery

```sh
python3 -m unittest discover -s emulation/tests -p 'test_game_catalog.py' -v
```
