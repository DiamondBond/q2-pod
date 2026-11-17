"""Optional host-side audio backend for the Q2 desktop UI preview.

Uses ffplay (part of FFmpeg). This deliberately does not emulate the Q2 DAC,
ALSA pipeline, hardware timing, or the original firmware's MIPS decoder.
"""
from __future__ import annotations
import shutil
import subprocess
import time


class FFplayAudio:
    def __init__(self, executable=None):
        self.binary = executable or shutil.which("ffplay")
        self.process = None
        self.track_key = None
        self.started_at = 0.0
        self.offset = 0.0
        self.notice = "" if self.binary else "ffplay not found; install FFmpeg for audio"

    def stop(self):
        proc = self.process
        self.process = None
        self.track_key = None
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=0.15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=0.15)

    def sync(self, ui):
        if not ui.tracks or ui.paused:
            self.stop()
            return
        track = ui.tracks[ui.current]
        if not track.path or not track.path.is_file():
            self.stop()
            return
        if not self.binary:
            return
        key = (str(track.path), ui.current)
        now = time.monotonic()
        expected = self.offset + (now - self.started_at)
        if self.process is not None and self.process.poll() is not None:
            # Don't spin-launch an unsupported or finished file repeatedly.
            self.process = None
            self.track_key = key
            return
        if self.process is not None and self.track_key == key and abs(ui.elapsed - expected) < 2.0:
            return
        if self.process is None and self.track_key == key:
            return
        self.stop()
        seek = max(0, float(ui.elapsed))
        try:
            self.process = subprocess.Popen(
                [self.binary, "-hide_banner", "-nodisp", "-autoexit",
                 "-loglevel", "error", "-vn", "-ss", f"{seek:.3f}", str(track.path)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
            self.track_key = key
            self.offset = seek
            self.started_at = now
            self.notice = ""
        except OSError as exc:
            self.notice = f"Unable to start ffplay: {exc}"
            self.track_key = key

    def close(self):
        self.stop()
