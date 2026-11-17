"""Versioned, data-driven built-in game metadata for Q2 firmware previews.

This module is deliberately independent of the game runtime. A firmware manifest
can describe arbitrary titles; that does NOT make their code executable.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

MANIFEST_VERSION = 1
MAX_GAMES = 128
MAX_BYTES = 65536
GAME_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
LEGACY_NAMES = ("Sudoku", "Vortex", "Solitaire", "Snake", "Pong", "Blocks")
KNOWN_CHECKOUT_GAMES = frozenset((*LEGACY_NAMES, "Breakout"))


@dataclass(frozen=True)
class GameInfo:
    id: str
    name: str


def parse_game_manifest(data: bytes) -> tuple[GameInfo, ...]:
    """Validate a firmware-supplied game list; never infer executable support."""
    if len(data) > MAX_BYTES:
        raise ValueError("Game manifest is too large")
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Game manifest is not valid UTF-8 JSON") from exc
    if not isinstance(doc, dict) or type(doc.get("schema_version")) is not int:
        raise ValueError("Game manifest needs schema_version")
    if doc["schema_version"] != MANIFEST_VERSION:
        raise ValueError("Unsupported game manifest schema version")
    items = doc.get("games")
    if not isinstance(items, list) or len(items) > MAX_GAMES:
        raise ValueError("Game manifest needs a bounded games list")
    result = []
    ids, names = set(), set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Each game must be an object")
        game_id, name = item.get("id"), item.get("name")
        if not isinstance(game_id, str) or not GAME_ID.fullmatch(game_id):
            raise ValueError("Invalid game identifier")
        if not isinstance(name, str) or not (1 <= len(name) <= 80) or any(ord(c) < 32 for c in name):
            raise ValueError("Invalid game display name")
        if game_id in ids or name.casefold() in names:
            raise ValueError("Duplicate game")
        ids.add(game_id)
        names.add(name.casefold())
        result.append(GameInfo(game_id, name))
    return tuple(result)


def manifest_names(data: bytes) -> tuple[str, ...]:
    return tuple(game.name for game in parse_game_manifest(data))


def checkout_can_preview(name: str) -> bool:
    """Legacy checkout-backed arcade renderer; NOT loaded firmware execution."""
    return name in KNOWN_CHECKOUT_GAMES
