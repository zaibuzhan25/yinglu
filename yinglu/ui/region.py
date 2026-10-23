"""全屏框选区域：截图变暗 → 拖动出高亮选区。"""
from __future__ import annotations

import time
import tkinter as tk
from typing import Callable, Optional

import mss
from PIL import Image, ImageEnhance, ImageTk

from .. import winutil
from ..winutil import Rect
from . import paint
from .paint import TEXT
from .widgets import ui_font


class RegionSelector:
    def __init__(self, root: tk.Tk, on_done: Callable[[Optional[Rect]], None],
                 scale: float = 1.0):
        self.root = root
        self.on_done = on_done
        self.k = float(scale)
        self.win: Optional[tk.Toplevel] = None
        self.canvas: Optional[tk.Canvas] = None
        self._vrect = winutil.virtual_screen()
        self._start: Optional[tuple[int, int]] = None
        self._cur: Optional[tuple[int, int]] = None
        self._selection: Optional[tuple[int, int, int, int]] = None
        self._crop_photo = None
        self._last_crop = 0.0
        self._bright: Optional[Image.Image] = None
        self._dark_photo = None
        self._hint_ids: list[int] = []
        self._size_id = None
        self._size_bg = None

    # ------------------------------------------------------------ show
    def show(self) -> None:
        self.root.withdraw()
        self.root.after(140, self._open)

    def _open(self) -> None:
        with mss.MSS() as sct:
            shot = sct.grab({"left": self._vrect.x, "top": self._vrect.y,
                             "width": self._vrect.w, "height": self._vrect.h})
            img = Image.frombuffer("RGBA", (shot.width, shot.height), shot.bgra,
                                   "raw", "BGRA", 0, 1).convert("RGB")
        self._bright = img
        dark = ImageEnhance.Brightness(img).enhance(0.35)
        self._dark_photo = ImageTk.PhotoImage(dark)

        self.win = tk.Toplevel(self.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.geometry(f"{self._vrect.w}x{self._vrect.h}+{self._vrect.x}+{self._vrect.y}")
        self.win.configure(bg="#000000")
        self.canvas = tk.Canvas(self.win, width=self._vrect.w, height=self._vrect.h,
                                highlightthickness=0, bd=0, bg="#000000",
                                cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_image(0, 0, anchor="nw", image=self._dark_photo)
        self._create_hint()

        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Motion>", self._motion)
        self.win.bind("<Escape>", lambda e: self._finish(None))
        self.win.bind("<Return>", lambda e: self._confirm())
        self.win.bind("<KP_Enter>", lambda e: self._confirm())
        self.win.focus_force()
        try:
            self.win.grab_set()
        except tk.TclError:
            pass

    def _create_hint(self) -> None:
        if not self.canvas:
            return
        text = "拖动鼠标框选录制区域    Enter 确认    Esc 取消"
        font = ui_font(12 * self.k, True)
        pad_x = max(14, int(22 * self.k))
        pad_y = max(12, int(20 * self.k))
        tmp = self.canvas.create_text(-1000, -1000, text=text, font=font)
        bbox = self.canvas.bbox(tmp)
        self.canvas.delete(tmp)
        tw = (bbox[2] - bbox[0]) if bbox else 320
        x = self._vrect.w // 2
        y = max(30, int(44 * self.k))
        self._hint_bg = self.canvas.create_rectangle(
            x - tw // 2 - pad_x, y - pad_y, x + tw // 2 + pad_x, y + pad_y,
            fill="#0b0d12", outline="#2a3140")
        self.canvas.create_text(x, y, text=text, fill=paint.hexc(TEXT), font=font)

    # ------------------------------------------------------------ mouse
    def _clamp(self, x: int, y: int) -> tuple[int, int]:
        return (max(0, min(self._vrect.w - 1, x)),
                max(0, min(self._vrect.h - 1, y)))

    def _press(self, event) -> None:
        self._start = self._clamp(event.x, event.y)
        self._cur = self._start

    def _drag(self, event) -> None:
        if not self._start or not self.canvas:
            return
        self._cur = self._clamp(event.x, event.y)
        self._draw_selection()

    def _motion(self, event) -> None:
        if self._start:
            return
        self._draw_badge(event.x, event.y, "点击并拖动")

    def _release(self, event) -> None:
        if not self._start:
            return
        self._cur = self._clamp(event.x, event.y)
        x1, y1 = self._start
        x2, y2 = self._cur
        x, y = min(x1, x2), min(y1, y2)
        w, h = abs(x2 - x1), abs(y2 - y1)
        if w < 24 or h < 24:
            self._start = None
            self._cur = None
            self._clear_selection()
            self._draw_badge(event.x, event.y, "选区太小，请重新拖动")
            return
        self._selection = (x, y, w, h)
        self._draw_selection()
        self._draw_size_badge()

    # ------------------------------------------------------------ draw
    def _clear_selection(self) -> None:
        if not self.canvas:
            return
        self.canvas.delete("sel")
        self.canvas.delete("badge")
        if self._crop_photo:
            for item in self.canvas.find_withtag("crop"):
                self.canvas.delete(item)
            self._crop_photo = None

    def _draw_selection(self) -> None:
        if not self._start or not self._cur or not self.canvas:
            return
        x1, y1 = self._start
        x2, y2 = self._cur
        x, y = min(x1, x2), min(y1, y2)
        w, h = abs(x2 - x1), abs(y2 - y1)
        if w < 2 or h < 2:
            return

        now = time.perf_counter()
        if self._bright is not None and now - self._last_crop > 0.025:
            self._last_crop = now
            crop = self._bright.crop((x, y, x + w, y + h))
            self._crop_photo = ImageTk.PhotoImage(crop)
            for item in self.canvas.find_withtag("crop"):
                self.canvas.delete(item)
            self.canvas.create_image(x, y, anchor="nw", image=self._crop_photo,
                                     tags="crop")

        self.canvas.delete("sel")
        self.canvas.create_rectangle(x, y, x + w, y + h, outline="#ffffff", width=2,
                                     tags="sel")
        for cx, cy in ((x, y), (x + w, y), (x, y + h), (x + w, y + h)):
            self.canvas.create_rectangle(cx - 4, cy - 4, cx + 4, cy + 4,
                                         fill="#ffffff", outline="", tags="sel")
        self.canvas.create_text(x + w / 2, y + h / 2,
                                text=f"{w} × {h}", fill="#ffffff",
                                font=ui_font(20 * self.k, True), tags="sel")
        self.canvas.delete("badge")

    def _draw_size_badge(self) -> None:
        if not self.canvas or not self._selection:
            return
        x, y, w, h = self._selection
        text = f"{w} × {h}   ·   Enter 确认"
        pad = max(9, int(14 * self.k))
        bx, by = x + w, y + h + pad
        if by > self._vrect.h - 50:
            by = y + h - max(24, int(34 * self.k))
        if bx > self._vrect.w - 40:
            bx = self._vrect.w - 40
        self.canvas.delete("badge")
        tmp = self.canvas.create_text(bx, by, text=text,
                                      font=ui_font(12 * self.k, True),
                                      fill="#ffffff", anchor="ne", tags="badge")
        bbox = self.canvas.bbox(tmp)
        if bbox:
            bg = self.canvas.create_rectangle(bbox[0] - 12, bbox[1] - 7,
                                              bbox[2] + 12, bbox[3] + 7,
                                              fill="#0b0d12", outline="#3a4254",
                                              tags="badge")
            self.canvas.tag_raise(tmp, bg)

    def _draw_badge(self, x: int, y: int, text: str) -> None:
        if not self.canvas:
            return
        self.canvas.delete("badge")
        off = max(10, int(16 * self.k))
        self.canvas.create_text(x + off, y + off, text=text, anchor="nw",
                                fill="#dfe5f0", font=ui_font(11 * self.k),
                                tags="badge")

    # ------------------------------------------------------------ finish
    def _confirm(self) -> None:
        if not self._selection:
            return
        x, y, w, h = self._selection
        rect = Rect(self._vrect.x + x, self._vrect.y + y, w, h)
        self._finish(rect)

    def _finish(self, rect: Optional[Rect]) -> None:
        if self.win is not None:
            try:
                self.win.grab_release()
            except Exception:
                pass
            self.win.destroy()
            self.win = None
        self.root.deiconify()
        self.root.lift()
        self.on_done(rect)
