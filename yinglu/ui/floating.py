"""录制中的悬浮控制条（置顶、可拖动、尽量不被录进画面）。"""
from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

from PIL import ImageTk

from . import paint
from .paint import ACCENT, CARD, CARD_HI, TEXT, render_round_rect
from .widgets import Button, ui_font

KEY = "#010203"  # 透明色键


class FloatingBar:
    def __init__(self, root: tk.Tk, on_pause: Callable, on_stop: Callable,
                 on_expand: Callable, scale: float = 1.0):
        self.root = root
        self.on_pause = on_pause
        self.on_stop = on_stop
        self.on_expand = on_expand
        self.scale = float(scale)
        self.W = self._px(338)
        self.H = self._px(76)
        self._paused = False
        self._pulse = False
        self._drag = None
        self._pulse_job: Optional[str] = None

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=KEY)
        try:
            self.win.wm_attributes("-transparentcolor", KEY)
        except tk.TclError:
            pass

        sw = root.winfo_screenwidth()
        x = sw // 2 - self.W // 2
        self.win.geometry(f"{self.W}x{self.H}+{x}+{self._px(18)}")

        self.canvas = tk.Canvas(self.win, width=self.W, height=self.H, bg=KEY,
                                highlightthickness=0, bd=0)
        self.canvas.pack()
        self._bg_img = ImageTk.PhotoImage(render_round_rect(
            self.W - self._px(8), self.H - self._px(8), max(6, self._px(18)),
            (20, 23, 31), KEY, outline=(48, 55, 70), width=1))
        self.canvas.create_image(self._px(4), self._px(4), anchor="nw",
                                 image=self._bg_img)

        self.dot = self.canvas.create_oval(self._px(20), self._px(32), self._px(32),
                                           self._px(44), fill=paint.hexc(ACCENT),
                                           outline="")
        self.timer = self.canvas.create_text(
            self._px(42), self._px(38), text="00:00", anchor="w", fill=paint.hexc(TEXT),
            font=("Consolas", -max(12, self._px(22)), "bold"))
        self.size = self.canvas.create_text(
            self._px(42), self._px(56), text="0.0 MB", anchor="w",
            fill=paint.hexc(paint.DIM), font=ui_font(self._px(9)))

        self.btn_pause = Button(self.win, self._px(38), self._px(38), "",
                                command=self._pause, bg=paint.hexc(CARD),
                                fill=CARD_HI, radius=self._px(12), icon="pause",
                                icon_color=TEXT)
        self.btn_stop = Button(self.win, self._px(38), self._px(38), "",
                               command=self._stop, bg=paint.hexc(CARD),
                               fill=(214, 46, 66), radius=self._px(12), icon="stop",
                               icon_color=(255, 255, 255))
        self.btn_expand = Button(self.win, self._px(30), self._px(30), "",
                                 command=self.on_expand, bg=paint.hexc(CARD),
                                 fill=(28, 33, 43), radius=self._px(10),
                                 icon="expand", icon_color=(160, 170, 190))
        self.btn_pause.place(x=self._px(214), y=self._px(19))
        self.btn_stop.place(x=self._px(258), y=self._px(19))
        self.btn_expand.place(x=self._px(300), y=self._px(23))

        for widget in (self.canvas,):
            widget.bind("<ButtonPress-1>", self._press)
            widget.bind("<B1-Motion>", self._motion)
        self.win.bind("<ButtonPress-1>", self._press)
        self.win.bind("<B1-Motion>", self._motion)
        self.win.withdraw()

    def _px(self, value: float) -> int:
        return int(round(value * self.scale))

    # ------------------------------------------------------------ drag
    def _press(self, event) -> None:
        self._drag = (event.x_root - self.win.winfo_x(),
                      event.y_root - self.win.winfo_y())

    def _motion(self, event) -> None:
        if not self._drag:
            return
        x = event.x_root - self._drag[0]
        y = event.y_root - self._drag[1]
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        x = max(0, min(sw - self.W, x))
        y = max(0, min(sh - self.H, y))
        self.win.geometry(f"+{x}+{y}")

    # ------------------------------------------------------------ update
    def show(self, paused: bool = False) -> None:
        self._paused = paused
        self.win.deiconify()
        self.win.attributes("-topmost", True)
        try:
            self.win.update_idletasks()
        except Exception:
            pass
        self._apply_exclusion()
        if not self._pulse_job:
            self._pulse_tick()
        self.win.after(250, self._apply_exclusion)

    def _apply_exclusion(self) -> None:
        from .. import winutil
        try:
            winutil.exclude_from_capture(int(self.win.wm_frame(), 16))
        except Exception:
            pass

    def hide(self) -> None:
        self.win.withdraw()
        if self._pulse_job:
            try:
                self.win.after_cancel(self._pulse_job)
            except Exception:
                pass
            self._pulse_job = None

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self.btn_pause.set_icon("play" if paused else "pause")

    def update(self, seconds: float, size_bytes: int) -> None:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        text = f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
        self.canvas.itemconfigure(self.timer, text=text)
        self.canvas.itemconfigure(self.size, text=f"{size_bytes / 1024 / 1024:.1f} MB")

    def _pulse_tick(self) -> None:
        if not self.win.winfo_viewable():
            self._pulse_job = None
            return
        self._pulse = not self._pulse
        color = ACCENT if self._pulse else (255, 140, 150)
        self.canvas.itemconfigure(self.dot, fill=paint.hexc(color))
        self._pulse_job = self.win.after(700, self._pulse_tick)

    def _pause(self) -> None:
        self._paused = not self._paused
        self.set_paused(self._paused)
        self.on_pause(self._paused)

    def _stop(self) -> None:
        self.on_stop()

    def set_enabled(self, enabled: bool) -> None:
        self.btn_pause.set_enabled(enabled)
        self.btn_stop.set_enabled(enabled)
