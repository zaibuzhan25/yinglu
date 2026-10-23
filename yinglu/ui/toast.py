"""轻量提示条：屏幕底部弹出，自动淡出。"""
from __future__ import annotations

import tkinter as tk

from PIL import ImageTk

from . import paint
from .paint import TEXT, render_round_rect
from .widgets import ui_font

KEY = "#010204"


class Toast:
    def __init__(self, root: tk.Tk, scale: float = 1.0):
        self.root = root
        self.scale = float(scale)
        self.W = int(round(420 * self.scale))
        self.H = int(round(56 * self.scale))
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=KEY)
        try:
            self.win.wm_attributes("-transparentcolor", KEY)
        except tk.TclError:
            pass
        self.canvas = tk.Canvas(self.win, width=self.W, height=self.H, bg=KEY,
                                highlightthickness=0, bd=0)
        self.canvas.pack()
        self._bg = ImageTk.PhotoImage(render_round_rect(
            self.W - self._px(8), self.H - self._px(8), max(4, self._px(16)),
            (24, 28, 38), KEY, outline=(52, 60, 78), width=1))
        self.canvas.create_image(self._px(4), self._px(4), anchor="nw", image=self._bg)
        self.text = self.canvas.create_text(self.W // 2, self.H // 2, text="",
                                            fill=paint.hexc(TEXT),
                                            font=ui_font(self._px(10)), anchor="center")
        self._dot = self.canvas.create_oval(0, 0, 0, 0, fill=paint.hexc(paint.GREEN),
                                            outline="")
        self._timer = None
        self.win.withdraw()

    def _px(self, value: float) -> int:
        return int(round(value * self.scale))

    def show(self, message: str, ms: int = 2800) -> None:
        self.canvas.itemconfigure(self.text, text=message)
        self.win.update_idletasks()
        bbox = self.canvas.bbox(self.text)
        tw = (bbox[2] - bbox[0]) if bbox else 0
        cx = self.W // 2 + self._px(8)
        self.canvas.coords(self.text, cx, self.H // 2)
        dot_x = cx - tw / 2 - self._px(16)
        r = max(3, self._px(5))
        self.canvas.coords(self._dot, dot_x - r, self.H / 2 - r, dot_x + r, self.H / 2 + r)
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        self.win.geometry(f"{self.W}x{self.H}+{sw // 2 - self.W // 2}+{sh - self._px(150)}")
        self.win.deiconify()
        self.win.lift()
        if self._timer:
            try:
                self.root.after_cancel(self._timer)
            except Exception:
                pass
        self._timer = self.root.after(ms, self.hide)

    def hide(self) -> None:
        self.win.withdraw()
        if self._timer:
            try:
                self.root.after_cancel(self._timer)
            except Exception:
                pass
        self._timer = None
