"""窗口选择器：列出可见窗口，点选后只录制该窗口。"""
from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

from PIL import ImageTk

from .. import winutil
from ..winutil import WindowInfo
from . import paint
from .paint import CARD, CARD_HI, TEXT, render_round_rect
from .widgets import Button, draw_icon, ui_font

W = 620
LIST_TOP = 104
ROW_H = 62
MAX_ROWS = 5


class WindowPicker:
    def __init__(self, root: tk.Tk, on_select: Callable[[Optional[WindowInfo]], None],
                 scale: float = 1.0):
        self.root = root
        self.on_select = on_select
        self.scale = float(scale)
        self.W = self._px(W)
        self.list_top = self._px(LIST_TOP)
        self.row_h = self._px(ROW_H)
        self.win: Optional[tk.Toplevel] = None
        self.canvas: Optional[tk.Canvas] = None
        self.rows: list[WindowInfo] = []
        self._offset = 0
        self._hover = -1
        self.h = self._px(300)
        self._row_photos: dict = {}

    def _px(self, value: float) -> int:
        return int(round(value * self.scale))

    def show(self) -> None:
        self.rows = winutil.list_windows()
        self._offset = 0
        self._hover = -1
        visible = max(1, min(MAX_ROWS, len(self.rows)))
        self.h = self._px(max(300, LIST_TOP + visible * ROW_H + 78))
        self.win = tk.Toplevel(self.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=paint.hexc(CARD))
        px = self.root.winfo_rootx() + (self.root.winfo_width() - self.W) // 2
        py = self.root.winfo_rooty() + (self.root.winfo_height() - self.h) // 2
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        px = max(8, min(sw - self.W - 8, px))
        py = max(8, min(sh - self.h - 48, py))
        self.win.geometry(f"{self.W}x{self.h}+{px}+{py}")

        self.canvas = tk.Canvas(self.win, width=self.W, height=self.h,
                                bg=paint.hexc(CARD), highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_rectangle(0, 0, self.W - 1, self.h - 1,
                                     outline=paint.hexc(paint.BORDER), width=1)
        self.canvas.create_text(self._px(28), self._px(28), text="选择录制窗口",
                                anchor="nw", fill=paint.hexc(TEXT),
                                font=ui_font(self._px(17), True))
        self.canvas.create_text(self._px(28), self._px(58),
                                text="只录制这个窗口的画面，窗口移动时会自动跟随",
                                anchor="nw", fill=paint.hexc(paint.MUTED),
                                font=ui_font(self._px(10)))

        self.btn_close = Button(self.win, self._px(34), self._px(30), "",
                                command=self._cancel, bg=paint.hexc(CARD),
                                fill=(28, 32, 41), radius=self._px(9),
                                icon="close", icon_color=paint.MUTED)
        self.btn_close.place(x=self.W - self._px(58), y=self._px(20))
        self.btn_refresh = Button(self.win, self._px(92), self._px(34), "刷新",
                                  command=self._refresh, bg=paint.hexc(CARD),
                                  fill=CARD_HI, radius=self._px(9),
                                  font_size=self._px(11), icon="refresh",
                                  icon_color=paint.MUTED)
        self.btn_refresh.place(x=self.W - self._px(28 + 92 + 12 + 92),
                               y=self.h - self._px(60))
        self.btn_cancel = Button(self.win, self._px(92), self._px(34), "取消",
                                 command=self._cancel, bg=paint.hexc(CARD),
                                 fill=(36, 41, 53), radius=self._px(9),
                                 font_size=self._px(11))
        self.btn_cancel.place(x=self.W - self._px(28 + 92), y=self.h - self._px(60))

        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.win.bind("<Escape>", lambda e: self._cancel())
        self.win.focus_force()
        try:
            self.win.grab_set()
        except tk.TclError:
            pass
        self._redraw()

    # ------------------------------------------------------------ draw
    def _visible_rows(self) -> list[WindowInfo]:
        return self.rows[self._offset:self._offset + MAX_ROWS]

    def _row_images(self) -> dict:
        if self._row_photos:
            return self._row_photos
        w = self.W - self._px(56)
        h = self.row_h - self._px(8)
        images = {
            "idle": ImageTk.PhotoImage(render_round_rect(
                w, h, max(4, self._px(10)), (23, 27, 36), paint.hexc(CARD))),
            "hover": ImageTk.PhotoImage(render_round_rect(
                w, h, max(4, self._px(10)), (31, 37, 50), paint.hexc(CARD))),
        }
        self._row_photos = images
        return images

    def _redraw(self) -> None:
        if not self.canvas:
            return
        self.canvas.delete("row")
        images = self._row_images()
        visible = self._visible_rows()
        for i, item in enumerate(visible):
            y = self.list_top + i * self.row_h
            self.canvas.create_image(
                self._px(28), y, anchor="nw",
                image=images["hover" if i == self._hover else "idle"],
                tags=("row", f"row{i}"))
            draw_icon(self.canvas, self._px(50), y + self._px(27), "monitor",
                      paint.hexc(paint.MUTED), self._px(20), tag="rowicon")
            title = item.title if len(item.title) <= 52 else item.title[:51] + "…"
            self.canvas.create_text(self._px(70), y + self._px(18), text=title,
                                    anchor="w", fill=paint.hexc(TEXT),
                                    font=ui_font(self._px(12), True),
                                    tags=("row", f"row{i}"))
            sub = item.app or "应用窗口"
            self.canvas.create_text(
                self._px(70), y + self._px(38),
                text=f"{sub}   ·   {item.rect.w} × {item.rect.h}",
                anchor="w", fill=paint.hexc(paint.DIM),
                font=ui_font(self._px(9)), tags=("row", f"row{i}"))
        if not visible:
            self.canvas.create_text(self.W // 2, self.list_top + self._px(80),
                                    text="没有找到可录制的窗口",
                                    fill=paint.hexc(paint.MUTED),
                                    font=ui_font(self._px(12)), tags="row")
        if len(self.rows) > MAX_ROWS:
            self.canvas.create_text(
                self.W - self._px(30), self.list_top - self._px(14),
                text=f"{self._offset + 1}-{min(len(self.rows), self._offset + MAX_ROWS)} / {len(self.rows)}",
                anchor="e", fill=paint.hexc(paint.DIM),
                font=ui_font(self._px(9)), tags="row")
        self.canvas.tag_raise("rowicon")

    # ------------------------------------------------------------ events
    def _row_at(self, y: int) -> int:
        if y < self.list_top or y > self.list_top + self.row_h * MAX_ROWS:
            return -1
        idx = (y - self.list_top) // self.row_h
        if idx >= len(self._visible_rows()):
            return -1
        return int(idx)

    def _motion(self, event) -> None:
        idx = self._row_at(event.y)
        if idx != self._hover:
            self._hover = idx
            self._redraw()
            self.canvas.configure(cursor="hand2" if idx >= 0 else "")

    def _click(self, event) -> None:
        idx = self._row_at(event.y)
        if 0 <= idx < len(self._visible_rows()):
            self._finish(self._visible_rows()[idx])

    def _wheel(self, event) -> None:
        if len(self.rows) <= MAX_ROWS:
            return
        delta = -1 if event.delta > 0 else 1
        self._offset = max(0, min(len(self.rows) - MAX_ROWS, self._offset + delta))
        self._hover = -1
        self._redraw()

    def _refresh(self) -> None:
        self.rows = winutil.list_windows()
        self._offset = 0
        self._hover = -1
        self._redraw()

    def _cancel(self) -> None:
        self._finish(None)

    def _finish(self, item: Optional[WindowInfo]) -> None:
        if self.win is not None:
            try:
                self.win.grab_release()
            except Exception:
                pass
            self.win.destroy()
            self.win = None
        self.on_select(item)
