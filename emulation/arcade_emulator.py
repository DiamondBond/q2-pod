#!/usr/bin/env python3
"""Playable Q2-style device using the real MIPS arcade rules through Unicorn.

This is a userspace CPU emulation harness, NOT an X2000 SoC or firmware emulator.
Q2 device enclosure and touch-wheel geometry reuse desktop-simulator code.
"""
from __future__ import annotations
import argparse
import math
import pathlib
import time

from PIL import Image, ImageDraw, ImageFont
from arcade_classic import draw_snake, draw_vortex
from arcade_puzzles import PUZZLE_GAMES, Puzzle
from simulator_device import (DEVICE_SIZE, DEFAULT_SHELL, SCREEN_AT, WHEEL,
                              device_frame, wheel_angle, wheel_button, wheel_delta)

from arcade_mips import MipsArcade, self_test as mips_self_test  # type: ignore[import-not-found]

SCREEN = (375, 320)
GAMES = ('pong', 'blocks', 'vortex', 'snake', *PUZZLE_GAMES, 'breakout')
FIRMWARE_GAMES = ('vortex', 'snake')
OVER = 2
GAME_FONT = ImageFont.load_default()
COLORS = ["#30c8e8", "#e8d030", "#ac70d8", "#48bc76",
          "#e85e60", "#5387db", "#ef9b3a"]
SHAPES = [0x00f0, 0x0660, 0x0270, 0x0360, 0x0630, 0x0710, 0x0740]


def draw_label(d, pos, text, color="#e8e8e8", anchor=None):
    d.text(pos, text, fill=color, anchor=anchor, font=GAME_FONT)


class ArcadeWindow:
    def __init__(self, shell=DEFAULT_SHELL, game=None, theme='modern'):
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
        self.theme = theme
        self.scene = "games"
        self.selection = 0
        self.game = None
        self.paused = False
        self.menu = False
        self.quit_selected = False
        self.last = time.monotonic()
        self.grav_ms = 0.0
        self.pong_ms = 0.0
        self.wheel_acc = 0.0
        self.best_scores = {}
        self.menu_wheel_acc = 0.0
        self.drag_angle = None
        self.canvas.bind("<ButtonPress-1>", self.mouse_down)
        self.canvas.bind("<B1-Motion>", self.mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.mouse_up)
        self.canvas.bind("<MouseWheel>", self.mouse_scroll)
        self.canvas.bind("<Button-4>", lambda _: self.scroll(-1))
        self.canvas.bind("<Button-5>", lambda _: self.scroll(1))
        self.root.bind("<Key>", self.key)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        if game in GAMES:
            self.start(game)
        self.update()

    def close(self):
        self.machine.close()
        self.root.destroy()

    def start(self, which):
        self.game = which
        self.scene = "play"
        self.paused = self.menu = False
        self.pong_ms = self.grav_ms = self.firmware_ms = self.wheel_acc = 0.0
        self.menu_wheel_acc = 0.0
        self.new_best = False
        seed = time.time_ns() & 0xffffffff
        if which in PUZZLE_GAMES:
            self.puzzle = Puzzle(self.machine, which, seed)
        elif which == "pong":
            self.machine.pong_init()
        elif which == "blocks":
            self.machine.blocks_init(seed)
        elif which == "breakout":
            self.machine.breakout_init()
        elif which == "snake":
            self.machine.snake_init(seed)
        else:
            self.machine.vortex_init()
        self.last = time.monotonic()

    def is_over(self):
        if self.game == "pong":
            p = self.machine.pong()
            return max(p.player_score, p.cpu_score) >= 7
        if self.game == "blocks":
            return bool(self.machine.blocks().game_over)
        if self.game == "breakout":
            return bool(self.machine.breakout().game_over)
        return self.firmware_state().state == OVER

    def firmware_state(self):
        return self.machine.snake() if self.game == "snake" else self.machine.vortex()

    def scroll(self, steps):
        if self.scene == "games":
            self.selection = (self.selection + (1 if steps > 0 else -1)) % len(GAMES)
        elif self.game in PUZZLE_GAMES:
            self.puzzle.move(steps)
        elif self.menu:
            self.quit_selected = not self.quit_selected
        elif self.scene == "play" and not self.paused and not self.is_over():
            if self.game == "pong":
                self.machine.pong_move(steps * 12)
            elif self.game == "blocks":
                self.machine.blocks_move(1 if steps > 0 else -1)
            elif self.game == "breakout":
                self.machine.breakout_move(steps * 14)
            elif self.game == "vortex":
                self.wheel_acc += steps * 32

    def on_wheel(self, rad):
        units = rad * 200 / math.tau
        if self.scene == "play" and self.game == "pong" and not self.paused and not self.menu:
            self.machine.pong_move(int(-units * 2))
            return
        if self.scene == "play" and self.game == "breakout" and not self.paused and not self.menu:
            self.wheel_acc += units * 2
            travel = math.trunc(self.wheel_acc)
            if travel:
                self.wheel_acc -= travel
                self.machine.breakout_move(travel)
            return
        if self.scene == "play" and self.game in FIRMWARE_GAMES and not self.menu:
            if self.game == "vortex" and not self.paused:
                self.wheel_acc += rad * 1024 / math.tau
            return
        self.menu_wheel_acc += units
        while abs(self.menu_wheel_acc) >= 10:
            step = 1 if self.menu_wheel_acc > 0 else -1
            self.menu_wheel_acc -= step * 10
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
            self.start(GAMES[self.selection])
        elif self.game in PUZZLE_GAMES:
            self.puzzle.select(time.time_ns() & 0xffffffff)
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
        elif self.game == "vortex":
            self.machine.vortex_launch()
        elif self.game == "breakout":
            self.machine.breakout_launch()

    def back(self):
        if self.scene == "games":
            return
        if self.game in PUZZLE_GAMES:
            if self.puzzle.back():
                self.scene, self.game = "games", None
        elif self.menu:
            self.menu = False
            self.paused = False
        elif self.game in FIRMWARE_GAMES and self.is_over():
            self.scene = "games"
            self.game = None
        else:
            self.menu = True
            self.quit_selected = False

    def button(self, name):
        if name == "up":
            self.back()
        elif name == "center":
            self.center()
        elif self.game in PUZZLE_GAMES:
            if name == "down":
                self.puzzle.new_game(time.time_ns() & 0xffffffff)
            elif name in ("left", "right"):
                self.puzzle.move(-1 if name == "left" else 1, vertical=True)
        elif name == "down":
            if self.menu:
                self.menu = self.paused = False
            elif self.scene == "play" and not self.is_over():
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
            elif self.game == "pong":
                self.machine.pong_move(-12 if name == "left" else 12)
            elif self.game == "snake":
                self.machine.snake_turn(-1 if name == "left" else 1)
            elif self.game in ("vortex", "breakout"):
                self.scroll(-1 if name == "left" else 1)

    def key(self, ev):
        k = ev.keysym
        if k in ("Escape", "BackSpace"):
            self.back()
        elif k in ("Return", "KP_Enter"):
            self.center()
        elif k in ("space", "p"):
            self.button("down")
        elif k in ("Up", "Down") and self.game in PUZZLE_GAMES:
            self.puzzle.move(-1 if k == "Up" else 1, vertical=True)
        elif k in ("Left", "Right") and self.game == "snake":
            self.button(k.lower())
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
        if (self.scene != "play" or self.game in PUZZLE_GAMES or self.paused
                or self.menu or self.is_over()):
            return
        if self.game in FIRMWARE_GAMES:
            self.advance_firmware(delta_ms)
        elif self.game == "pong":
            self.pong_ms += min(delta_ms, 100)
            for _ in range(6):
                if self.pong_ms < 17: break
                self.pong_ms -= 17
                self.machine.pong_tick()
        elif self.game == "breakout":
            self.firmware_ms += min(delta_ms, 100) * 60
            while self.firmware_ms >= 1000:
                self.firmware_ms -= 1000
                self.machine.breakout_tick()
        else:
            b = self.machine.blocks()
            speed = max(85, 650 - min(b.level - 1, 12) * 45)
            self.grav_ms += min(delta_ms, 100)
            if self.grav_ms >= speed:
                self.grav_ms %= speed
                self.machine.blocks_tick()

    def advance_firmware(self, delta_ms):
        self.firmware_ms += min(delta_ms, 100)
        if self.game == "snake":
            for _ in range(2):
                period = self.machine.snake_ms()
                if self.firmware_ms < period or self.is_over():
                    break
                self.firmware_ms -= period
                self.machine.snake_tick()
        else:
            for _ in range(4):
                if self.firmware_ms < 1000 / 60 or self.is_over():
                    break
                self.firmware_ms -= 1000 / 60
                turn = math.trunc(self.wheel_acc)
                self.wheel_acc -= turn
                self.machine.vortex_tick(turn)
            if self.firmware_ms >= 1000 / 60:
                self.firmware_ms = 0
        score = self.firmware_state().score
        if self.is_over() and score > self.best_scores.get(self.game, 0):
            self.best_scores[self.game] = score
            self.new_best = True

    def render_firmware_game(self):
        state = self.firmware_state()
        classic = self.theme == "classic-light"
        if self.game == "snake":
            screen = draw_snake(state, classic)
        else:
            screen = draw_vortex(state, classic)
        draw = ImageDraw.Draw(screen)
        draw_label(draw, (24, 6), f"Score  {state.score}", anchor="lt")
        draw_label(draw, (351, 6), f"Best  {self.best_scores.get(self.game, 0)}", anchor="rt")
        if self.game == "vortex":
            draw_label(draw, (48, 290), f"Level  {state.level + 1}", anchor="lt")
            if state.state == 0 and not self.paused and not self.menu:
                draw_label(draw, (187, 160), "Centre", "#e1e8fa", "mm")
        return screen

    def render_screen(self):
        light = self.theme == "classic-light"
        if self.scene == "play" and self.game in PUZZLE_GAMES:
            return self.puzzle.render(light)
        paper, text, bar = ("#f3f3f0", "#161616", "#d8dade") if light else (
            "#10141c", "#e9e9ed", "#222833")
        screen = Image.new("RGB", SCREEN, paper)
        d = ImageDraw.Draw(screen)
        d.rectangle((0, 0, 374, 31), fill=bar)
        draw_label(d, (14, 16), "Q2 POD", text, "lm")
        draw_label(d, (363, 16), "GAMES", "#82909d" if light else "#9cabbc", "rm")
        if self.scene == "games":
            draw_label(d, (188, 58), "Games", anchor="mt")
            for idx, game in enumerate(GAMES):
                name = game.title()
                y = 68 + idx * 29
                if idx == self.selection:
                    d.rounded_rectangle((20, y, 355, y + 27), radius=7, fill="#6686b3")
                draw_label(d, (42, y + 15), name, "#ffffff", "lm")
                draw_label(d, (335, y + 15), ">", "#ffffff", "rm")
            draw_label(d, (188, 282), "Wheel: select  |  Center: open", "#abb5c0", "mt")
            return screen
        if self.game in FIRMWARE_GAMES:
            screen = self.render_firmware_game()
            d = ImageDraw.Draw(screen)
        elif self.game == "pong":
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
        elif self.game == "breakout":
            self.draw_breakout(d, text)
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
            draw_label(d, (260, 86), "Next", "#abb5c0", "lt")
            for row in range(4):
                for col in range(4):
                    cell = self.machine.blocks_preview_cell(col, row)
                    if cell:
                        x, y = 263 + col * 11, 105 + row * 11
                        d.rectangle((x, y, x + 9, y + 9), fill=COLORS[cell - 1])
            draw_label(d, (187, 279), "Center: rotate  |  Right: drop", "#abb5c0", "mt")
        if self.menu or self.paused or self.is_over():
            d.rounded_rectangle((58, 108, 317, 216), 12, fill="#303744", outline="#8394a9")
            title = "Paused"
            if self.is_over():
                title = "New best!" if self.game in FIRMWARE_GAMES and self.new_best else "Game over"
            draw_label(d, (187, 130), title, "#ffffff", "mt")
            if self.menu:
                draw_label(d, (120, 168), ("  " if self.quit_selected else "> ") + "Continue",
                           "#dce8fa", "mm")
                draw_label(d, (254, 168), ("> " if self.quit_selected else "  ") + "Quit",
                           "#dce8fa", "mm")
                draw_label(d, (187, 194), "Wheel: choose   Center: OK", "#c7ced5", "mt")
            elif self.is_over():
                draw_label(d, (187, 180), "Center: play again", "#c7ced5", "mt")
            else:
                draw_label(d, (187, 180), "Play/Pause: resume", "#c7ced5", "mt")
        return screen

    def draw_breakout(self, draw, text):
        state = self.machine.breakout()
        left, top = 27, 58
        draw_label(draw, (left, 44), f"Score {state.score}", text, "lm")
        draw_label(draw, (347, 44), f"Level {state.level}   Lives {state.lives}", text, "rm")
        draw.rectangle((left, top, left + 319, top + 239), fill="#111722", outline="#526074")
        for row, bricks in enumerate(state.bricks):
            for column, brick in enumerate(bricks):
                if brick:
                    x, y = left + 16 + column * 36, top + 27 + row * 16
                    draw.rectangle((x, y, x + 32, y + 12), fill=COLORS[brick - 1])
        paddle = left + state.paddle_x
        draw.rectangle((paddle, top + 220, paddle + 47, top + 225), fill="#5fd7b1")
        x, y = left + state.ball_x, top + state.ball_y
        draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill="#ffffff")
        if state.waiting:
            draw_label(draw, (187, 214), "Center: launch", "#e8e8e8", "mm")

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
        self.root.after(16 if self.game == "vortex" else 33, self.update)

    def run(self):
        self.root.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="run headless MIPS smoke test")
    parser.add_argument("--theme", choices=("classic-light", "modern", "minimal"),
                        default="modern")
    parser.add_argument("--shell", choices=("Orange", "Silver", "Black", "Champagne Gold"),
                        default=DEFAULT_SHELL)
    parser.add_argument("--snapshot", type=pathlib.Path, help="save Q2 screenshot without a desktop display")
    parser.add_argument("--game", choices=GAMES,
                        help="open directly into one game")
    args = parser.parse_args()
    if args.self_test:
        mips_self_test()
        return
    if args.snapshot:
        machine = MipsArcade()
        try:
            view = object.__new__(ArcadeWindow)
            view.machine = machine
            view.scene = "games"
            view.theme = args.theme
            view.selection = 0
            view.game = None
            view.paused = view.menu = False
            view.quit_selected = False
            view.best_scores = {}
            if args.game:
                view.start(args.game)
            device_frame(view.render_screen(), args.shell).save(args.snapshot)
            print(f"Wrote {args.snapshot} (MIPS Unicorn gameplay state)")
        finally:
            machine.close()
        return
    ArcadeWindow(args.shell, args.game, args.theme).run()


if __name__ == "__main__":
    main()
