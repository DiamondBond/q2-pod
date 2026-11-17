#!/usr/bin/env python3
"""Host audio synchronization tests (do not launch ffplay or play sound)."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from simulator_audio import FFplayAudio


class FakeProc:
    def __init__(self):
        self.stopped = False
    def poll(self):
        return 0 if self.stopped else None
    def terminate(self):
        self.stopped = True
    def kill(self):
        self.stopped = True
    def wait(self, timeout):
        return 0


def main():
    with tempfile.TemporaryDirectory() as directory:
        music = Path(directory) / "test.flac"
        music.write_bytes(b"fake audio data: ffplay is mocked")
        ui = SimpleNamespace(tracks=[SimpleNamespace(path=music)],
                             current=0, paused=True, elapsed=0.0)
        calls = []
        def fake_popen(args, **kwargs):
            calls.append((args, kwargs))
            return FakeProc()
        with patch("simulator_audio.subprocess.Popen", side_effect=fake_popen):
            a = FFplayAudio("ffplay")
            a.sync(ui)
            assert not calls, "paused UI should never start audio"
            ui.paused = False
            a.sync(ui)
            assert len(calls) == 1 and calls[0][0][-1] == str(music)
            a.sync(ui)
            assert len(calls) == 1, "continuous playback should not spawn more processes"
            ui.paused = True
            a.sync(ui)
            assert a.process is None
            ui.paused = False
            ui.elapsed = 12.5
            a.sync(ui)
            assert len(calls) == 2 and "12.500" in calls[1][0]
            a.close()
            assert a.process is None
    print("host FFmpeg playback: synchronization checks passed")


if __name__ == "__main__":
    main()
