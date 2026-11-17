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

This is **metadata only**, not an executable game ABI. A new game will
appear in the menu but may report that it has no compatible runtime. To
make an arbitrary firmware title playable, a stable C ABI (with callback
entry points, input protocol, graphics-command buffer, memory allocation
and asset access) must be implemented in both the firmware build and the
desktop runner. That ABI is *not yet implemented*.

For older firmware that does not contain the manifest, the simulator retains
legacy detection: the predefined game list plus a best-effort Breakout
signature test. This cannot discover an arbitrary new game and is not
a guaranteed inventory of the loaded firmware.

## Contributor contract (planned)

A universal runtime should be driven by an API version and a registry,
not by game names. A future implementation needs:

1. **Stable versioned game ABI**: lifecycle, fixed-step tick, normalized
   wheel/buttons/touch, save requests and a draw-command stream.
2. **Source registration and packaging**: build emits the manifest and
   game entry point table together, so the manifest cannot list missing code.
3. **Generic runtime**: compiler or firmware loader resolves the published
   entry points and uses the same graphics/input adapter for every title.
4. **Compatibility checks**: unsupported API versions, missing exports or
   unavailable firmware services yield explicit errors rather than silently
   executing local checkout code.
5. **Tests**: one contract test suite should apply to every registered game.

Until this work is complete, the emulator remains a **partial simulator**.
The `desktop-simulator` branch owns emulator-specific code; the
`new-builtin-games` branch owns firmware game rules and the portable C
framework.

## Testing discovery

```sh
python3 -m unittest discover -s emulation/tests -p 'test_game_catalog.py' -v
```
