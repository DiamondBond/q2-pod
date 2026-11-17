"""Desktop input and rendering for the firmware Sudoku and Solitaire rules."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PUZZLE_GAMES = ("sudoku", "solitaire")
FONT_PATH = Path(__file__).resolve().parents[1] / "assets/fonts/LiberationSans-Bold.ttf"
FONT = ImageFont.truetype(str(FONT_PATH), 18)
SMALL = ImageFont.truetype(str(FONT_PATH), 13)
CLUE, FACE_UP, TABLEAU = 16, 64, 6
COLUMNS = (0, 1, 3, 4, 5, 6, 0, 1, 2, 3, 4, 5, 6)
RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")


class Puzzle:
    def __init__(self, machine, game, seed):
        self.machine, self.game = machine, game
        self.restart(seed)

    def restart(self, seed):
        self.machine.puzzle_init(self.game, seed)
        self.cursor, self.pick, self.confirm = 0, None, False

    def move(self, steps, vertical=False):
        if self.confirm:
            return
        if self.game == "sudoku":
            if self.pick is not None:
                if not vertical:
                    self.pick = (self.pick + steps) % 10
            else:
                self.cursor = (self.cursor + (9 if vertical else 1) * steps) % 81
        elif vertical:
            c = self.cursor
            if c < TABLEAU:
                self.cursor = TABLEAU + COLUMNS[c]
            else:
                column = COLUMNS[c]
                self.cursor = column if column < 2 else max(1, column - 1)
        else:
            self.cursor = (self.cursor + steps) % 13

    def back(self):
        if self.confirm or self.pick is not None:
            self.confirm, self.pick = False, None
            return False
        return True

    def new_game(self, seed):
        if self.game == "sudoku":
            cells = self.machine.sudoku().cell
            in_progress = any(value and not value & CLUE for value in cells)
            in_progress = in_progress and not self.machine.sudoku_action("sud_done")
        else:
            in_progress = not self.machine.solitaire_action("sol_won")
        if in_progress:
            self.confirm = True
        else:
            self.restart(seed)

    def select(self, seed):
        if self.confirm:
            self.restart(seed)
        elif self.game == "sudoku":
            if self.pick is not None:
                self.machine.sudoku_action("sud_set", self.cursor, self.pick)
                self.pick = None
            else:
                value = self.machine.sudoku().cell[self.cursor]
                if not value & CLUE and not self.machine.sudoku_action("sud_done"):
                    self.pick = value
        else:
            self.select_pile()

    def select_pile(self):
        cards = self.machine.solitaire()
        action = self.machine.solitaire_action
        cursor, held = self.cursor, self.pick
        moved = False
        if cursor == 0:
            self.pick = None
            moved = action("sol_draw")
        elif held == cursor:
            self.pick = None
            if cursor == 1 or cursor >= TABLEAU:
                moved = action("sol_home", cursor)
        elif held is not None:
            moved = action("sol_move", held, cursor)
            if moved:
                self.pick = None
            elif cards.len[cursor]:
                self.pick = cursor
        elif cards.len[cursor] and not action("sol_won"):
            self.pick = cursor
        if moved:
            action("sol_finish")

    def render(self, classic):
        if self.game == "sudoku":
            image = Image.new("RGB", (375, 320), "#e9eaee" if classic else "#161719")
            draw = ImageDraw.Draw(image)
            caption = self.draw_sudoku(draw)
        else:
            image = Image.new("RGB", (375, 320), "#2b7437" if classic else "#182b26")
            draw = ImageDraw.Draw(image)
            caption = self.draw_solitaire(draw)
        if self.confirm or caption:
            title = ("New game?", "Enter to confirm  ·  Esc to cancel") if self.confirm else caption
            draw.rounded_rectangle((60, 119, 315, 193), 8, "#222831", "#8f9da9")
            draw.text((187, 141), title[0], "#ffffff", FONT, anchor="mm")
            draw.text((187, 170), title[1], "#e2e7ed", SMALL, anchor="mm")
        return image

    def draw_sudoku(self, draw):
        board = self.machine.sudoku().cell
        for i, cell in enumerate(board):
            x, y = 57 + i % 9 * 29, 25 + i // 9 * 29
            clue = bool(cell & CLUE)
            draw.rectangle((x, y, x + 28, y + 28),
                           fill="#d3d6da" if clue else "#f9fafb", outline="#aeb4ba")
            if cell:
                ink = "#22303b"
                if not clue and self.machine.sudoku_action("sud_conflict", i):
                    ink = "#a71d22"
                draw.text((x + 14, y + 14), str(cell & 15), ink, FONT, anchor="mm")
        for section in range(4):
            n = section * 87
            draw.line((57 + n, 25, 57 + n, 286), "#3b424a", width=2)
            draw.line((57, 25 + n, 318, 25 + n), "#3b424a", width=2)
        x, y = 57 + self.cursor % 9 * 29, 25 + self.cursor // 9 * 29
        draw.rectangle((x + 1, y + 1, x + 27, y + 27), outline="#2473cd", width=3)
        if self.pick is not None:
            return ("Choose a digit", f"◀   {self.pick or 'Clear'}   ▶")
        if self.machine.sudoku_action("sud_done"):
            return ("Solved!", "Space for a new puzzle")
        return None

    def draw_solitaire(self, draw):
        state = self.machine.solitaire()
        suits = ("♠", "♥", "♦", "♣")
        for pile in range(13):
            x = 18 + 49 * COLUMNS[pile]
            y = 18 if pile < TABLEAU else 80
            count = state.len[pile]
            if not count:
                draw.rounded_rectangle((x, y, x + 43, y + 45), 4, outline="#a8c2b4")
            elif pile == 0:
                draw.rounded_rectangle((x, y, x + 43, y + 45), 4, "#28548f", "#f4f4f4")
            else:
                first = count - 1 if pile < TABLEAU else 0
                gap = min(17, 151 // max(1, count - 1))
                for i in range(first, count):
                    card = state.card[pile][i]
                    row_y = y + (i - first) * gap
                    face_up = bool(card & FACE_UP)
                    draw.rounded_rectangle((x, row_y, x + 43, row_y + 45), 4,
                                           "#f4f4f4" if face_up else "#28548f", "#acb5be")
                    if face_up:
                        suit, rank = divmod(card & ~FACE_UP, 13)
                        ink = "#a02531" if suit in (1, 2) else "#181818"
                        draw.text((x + 4, row_y + 2), RANKS[rank] + suits[suit], ink, SMALL)
                y += (count - 1 - first) * gap
            if pile == self.cursor or pile == self.pick:
                outline = "#ffd23c" if pile == self.pick else "#ffffff"
                draw.rounded_rectangle((x - 2, y - 2, x + 45, y + 47), 6, outline=outline, width=2)
        if self.machine.solitaire_action("sol_won"):
            return ("You won!", "Space for a new deal")
        return None
