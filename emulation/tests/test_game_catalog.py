"""Portable catalog regression tests (no Unicorn, GUI or firmware image needed)."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from game_catalog import parse_game_manifest, manifest_names, checkout_can_preview


class GameCatalogTests(unittest.TestCase):
    def test_arbitrary_future_titles_are_discovered(self):
        blob = json.dumps({"schema_version": 1, "games": [
            {"id": "minesweeper", "name": "Minesweeper"},
            {"id": "my-game", "name": "A New Team Game"}
        ]}).encode()
        self.assertEqual(manifest_names(blob), ("Minesweeper", "A New Team Game"))
        self.assertFalse(checkout_can_preview("Minesweeper"))
        self.assertTrue(checkout_can_preview("Breakout"))

    def test_rejects_bad_manifest(self):
        for bad in (
            b'{', b'{"schema_version":2,"games":[]}',
            b'{"schema_version":1,"games":[{"id":"../bad","name":"Oops"}]}',
            b'{"schema_version":1,"games":[{"id":"a","name":"A"},{"id":"a","name":"B"}]}',
            b'{"schema_version":1,"games":[{"id":"x","name":"Bad\\u0000Name"}]}',
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_game_manifest(bad)

    def test_empty_manifest(self):
        self.assertEqual(parse_game_manifest(b'{"schema_version":1,"games":[]}'), ())


if __name__ == "__main__":
    unittest.main()
