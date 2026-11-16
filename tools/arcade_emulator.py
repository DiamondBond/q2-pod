#!/usr/bin/env python3
"""Playable Q2-style device using the real MIPS arcade rules through Unicorn.

This is a userspace CPU emulation harness, NOT an X2000 SoC or firmware emulator.
Q2 device enclosure and touch-wheel geometry reuse desktop-simulator code.
"""
from __future__ import annotations
import argparse
import math
import pathlib
import sys
import time

from PIL import Image, ImageDraw, ImageFont
from simulator_device import (DEVICE_SIZE, DEFAULT_SHELL, SCREEN_AT, WHEEL,
                              device_frame, wheel_angle, wheel_button, wheel_delta)

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "test"))
from arcade_mips import MipsArcade, self_test as mips_self_test

SCREEN = (375, 320)
COLORS = ["#30c8e8", "#e8d030", "#ac70d8", "#48bc76",
          "#e85e60", "#5387db", "#ef9b3a"]
SHAPES = [0x00f0, 0x0660, 0x0270, 0x0360, 0x0630, 0x0710, 0x0740]


def draw_label(d, pos, text, color="#e8e8e8", anchor=None):
    d.text(pos, text, fill=color, anchor=anchor, font=ImageFont.load_default())


class ArcadeWindow:
    def __init__(self, shell=DEFAULT_SHELL, game=None):
        import tkinter as tk
        from PIL import ImageTk
        self.tk = tk
        self.ImageTk = ImageTk
        self.machine = MipsArcade()
        self.root = tk.Tk()
        self.root.title("Q2 Pod — MIPS Unicorn game emulator")
        self.root.resizable(False, False)
        self.canvas = tk.Canvas(self.root, width=DEVICE_SIZE[0],
                                height=DEVICE_SIZE[1], highlightthickness=0)
        self.canvas.pack()
        self.photo = None
        self.shell = shell
        self.scene = "games"
        self.selection = 0
        self.game = None
        self.paused = False
        self.menu = False
        self.quit_selected = False
        self.last = time.monotonic()
        self.grav_ms = 0
        self.pong_ms = 0
        self.wheel_acc = 0.0
        self.drag_angle = None
        self.canvas.bind("<ButtonPress-1>", self.mouse_down)
        self.canvas.bind("<B1-Motion>", self.mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.mouse_up)
        self.canvas.bind("<MouseWheel>", self.mouse_scroll)
        self.canvas.bind("<Button-4>", lambda _: self.scroll(-1))
        self.canvas.bind("<Button-5>", lambda _: self.scroll(1))
        self.root.bind("<Key>", self.key)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        if game in ('pong', 'blocks'):
            self.start(game)
        self.update()

    def close(self):
        self.machine.close()
        self.root.destroy()

    def start(self, which):
        self.game = which
        self.scene = "play"
        self.paused = self.menu = False
        self.pong_ms = self.grav_ms = 0
        if which == "pong":
            self.machine.pong_init()
        else:
            self.machine.blocks_init(int(time.time()) & 0xffffffff)
        self.last = time.monotonic()

    def is_over(self):
        if self.game == "pong":
            p = self.machine.pong()
            return max(p.player_score, p.cpu_score) >= 7
        return bool(self.machine.blocks().game_over)

    def scroll(self, steps):
        if self.scene == "games":
            self.selection = (self.selection + (1 if steps > 0 else -1)) % 2
        elif self.menu:
            self.quit_selected = not self.quit_selected
        elif self.scene == "play" and not self.paused and not self.is_over():
            if self.game == "pong":
                self.machine.pong_move(steps * 12)
            else:
                self.machine.blocks_move(1 if steps > 0 else -1)

    def on_wheel(self, rad):
        units = rad * 200 / math.tau
        if self.scene == "play" and self.game == "pong" and not self.paused and not self.menu:
            self.machine.pong_move(int(-units * 2))
            return
        self.wheel_acc += units
        while abs(self.wheel_acc) >= 10:
            step = 1 if self.wheel_acc > 0 else -1
            self.wheel_acc -= step * 10
            self.scroll(step)

    def mouse_down(self, ev):
        x, y = ev.x, ev.y
        if y < SCREEN_AT[1] + SCREEN[1] and x >= SCREEN_AT[0]:
            return
        button = wheel_button(x, y)
        if button == "center":
            self.center()
        elif button in ("up", "down", "left", "right"):
            # A drag must begin in the outer wheel ring, not the physical buttons.
            self.drag_angle = wheel_angle(x, y)
            self.drag_origin = (x, y)
            self.drag_button = button

    def mouse_drag(self, ev):
        if self.drag_angle is None:
            return
        a = wheel_angle(ev.x, ev.y)
        self.on_wheel(wheel_delta(self.drag_angle, a))
        self.drag_angle = a

    def mouse_up(self, ev):
        if self.drag_angle is not None:
            start = self.drag_origin
            moved = math.hypot(ev.x - start[0], ev.y - start[1])
            if moved < 9:
                self.button(self.drag_button)
        self.drag_angle = None

    def mouse_scroll(self, ev):
        self.scroll(-1 if ev.delta > 0 else 1)

    def center(self):
        if self.scene == "games":
            self.start(("pong", "blocks")[self.selection])
        elif self.menu:
            if self.quit_selected:
                self.scene = "games"
                self.game = None
                self.menu = False
            else:
                self.menu = False
                self.paused = False
                self.last = time.monotonic()
        elif self.is_over():
            self.start(self.game)
        elif self.paused:
            self.paused = False
            self.last = time.monotonic()
        elif self.game == "blocks":
            self.machine.blocks_rotate()

    def back(self):
        if self.scene == "games":
            return
        if self.menu:
            self.menu = False
            self.paused = False
        else:
            self.menu = True
            self.quit_selected = False

    def button(self, name):
        if name == "up":
            self.back()
        elif name == "down":
            if self.scene == "play" and not self.menu:
                self.paused = not self.paused
                self.last = time.monotonic()
        elif self.menu:
            self.quit_selected = not self.quit_selected
        elif self.scene == "games":
            self.scroll(-1 if name == "left" else 1)
        elif self.scene == "play" and not self.paused and not self.is_over():
            if self.game == "blocks":
                if name == "left": self.machine.blocks_tick()
                else: self.machine.blocks_drop()
            else:
                self.machine.pong_move(-12 if name == "left" else 12)

    def key(self, ev):
        k = ev.keysym
        if k in ("Escape", "BackSpace"):
            self.back()
        elif k in ("Return", "KP_Enter"):
            self.center()
        elif k in ("space", "p"):
            self.button("down")
        elif k in ("Up", "a", "Left"):
            self.scroll(-1)
        elif k in ("d", "Right"):
            self.scroll(1)
        elif k in ("Down", "s"):
            self.button("left")
        elif k in ("Shift_L", "Shift_R"):
            self.button("right")
        elif k == "1":
            self.start("pong")
        elif k == "2":
            self.start("blocks")

    def advance(self, delta_ms):
        if self.scene != "play" or self.paused or self.menu or self.is_over():
            return
        if self.game == "pong":
            self.pong_ms += min(delta_ms, 100)
            for _ in range(6):
                if self.pong_ms < 17: break
                self.pong_ms -= 17
                self.machine.pong_tick()
        else:
            b = self.machine.blocks()
            speed = max(85, 650 - min(b.level - 1, 12) * 45)
            self.grav_ms += min(delta_ms, 100)
            if self.grav_ms >= speed:
                self.grav_ms %= speed
                self.machine.blocks_tick()

    def render_screen(self):
        screen = Image.new("RGB", SCREEN, "#10141c")
        d = ImageDraw.Draw(screen)
        d.rectangle((0, 0, 374, 31), fill="#222833")
        draw_label(d, (14, 16), "Q2 POD", "#efefef", "lm")
        draw_label(d, (363, 16), "GAMES", "#9cabbc", "rm")
        if self.scene == "games":
            draw_label(d, (188, 58), "Games", anchor="mt")
            for idx, name in enumerate(("Pong", "Blocks")):
                y = 103 + idx * 55
                if idx == self.selection:
                    d.rounded_rectangle((20, y, 355, y + 45), radius=7, fill="#6686b3")
                draw_label(d, (42, y + 23), name, "#ffffff", "lm")
                draw_label(d, (335, y + 23), ">", "#ffffff", "rm")
            draw_label(d, (188, 277), "Wheel: select  |  Center: open", "#abb5c0", "mt")
            return screen
        if self.game == "pong":
            p = self.machine.pong()
            draw_label(d, (20, 42), f"You  {p.player_score}", anchor="lt")
            draw_label(d, (355, 42), f"CPU  {p.cpu_score}", anchor="rt")
            d.rectangle((18, 65, 357, 284), fill="#111722", outline="#526074")
            for y in range(75, 277, 23):
                d.rectangle((186, y, 189, y + 10), fill="#687587")
            def sy(y): return 65 + y * 216 // 240
            d.rectangle((27, sy(p.player_y), 35, sy(p.player_y + 48)), fill="#5fd7b1")
            d.rectangle((341, sy(p.cpu_y), 349, sy(p.cpu_y + 48)), fill="#eeeeee")
            bx, by = 18 + p.ball_x * 339 // 320, sy(p.ball_y)
            d.ellipse((bx - 4, by - 4, bx + 4, by + 4), fill="#ffffff")
        else:
            b = self.machine.blocks()
            draw_label(d, (20, 42), f"Score {b.score}", anchor="lt")
            draw_label(d, (355, 42), f"Lv {b.level}", anchor="rt")
            size, x0, y0 = 10, 137, 65
            d.rectangle((x0 - 2, y0 - 2, x0 + 102, y0 + 202), fill="#526074")
            for y in range(20):
                for x in range(10):
                    value = b.board[y][x]
                    if value:
                        d.rectangle((x0 + x * size, y0 + y * size,
                                     x0 + x * size + 9, y0 + y * size + 9),
                                    fill=COLORS[value - 1])
                    else:
                        d.rectangle((x0 + x * size, y0 + y * size,
                                     x0 + x * size + 9, y0 + y * size + 9),
                                    fill="#202a38", outline="#131b27")
            shape = SHAPES[b.piece]
            for y in range(4):
                for x in range(4):
                    col, row = x, y
                    if b.piece != 1:
                        for _ in range(b.rotation % 4):
                            col, row = row, 3 - col
                    if not (shape >> (row * 4 + col)) & 1:
                        continue
                    gx, gy = b.x + x, b.y + y
                    if 0 <= gx < 10 and 0 <= gy < 20:
                        d.rectangle((x0 + gx * size, y0 + gy * size,
                                     x0 + gx * size + 9, y0 + gy * size + 9),
                                    fill=COLORS[b.piece])
            draw_label(d, (187, 279), "Center: rotate  |  Right: drop", "#abb5c0", "mt")
        if self.menu or self.paused or self.is_over():
            d.rounded_rectangle((58, 108, 317, 216), 12, fill="#303744", outline="#8394a9")
            title = "Game Over" if self.is_over() else "Paused"
            draw_label(d, (187, 130), title, "#ffffff", "mt")
            if self.menu:
                draw_label(d, (187, 166), "> Quit" if self.quit_selected else "> Continue",
                           "#dce8fa", "mt")
                draw_label(d, (187, 194), "Wheel: choose   Center: OK", "#c7ced5", "mt")
            elif self.is_over():
                draw_label(d, (187, 180), "Center: play again", "#c7ced5", "mt")
            else:
                draw_label(d, (187, 180), "Play/Pause: resume", "#c7ced5", "mt")
        return screen

    def update(self):
        now = time.monotonic()
        delta = (now - self.last) * 1000
        self.last = now
        self.advance(delta)
        image = device_frame(self.render_screen(), self.shell)
        self.photo = self.ImageTk.PhotoImage(image)
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw", tags="screen")
        self.canvas.delete("old")
        self.canvas.itemconfigure("screen", tags="old")
        self.root.after(33, self.update)

    def run(self):
        self.root.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="run headless MIPS smoke test")
    parser.add_argument("--shell", choices=("Orange", "Silver", "Black", "Champagne Gold"),
                        default=DEFAULT_SHELL)
    parser.add_argument("--game", choices=("pong", "blocks"),
                        help="open directly into one game")
    args = parser.parse_args()
    if args.self_test:
        mips_self_test()
        return
    ArcadeWindow(args.shell, args.game).run()


if __name__ == "__main__":
    main()
