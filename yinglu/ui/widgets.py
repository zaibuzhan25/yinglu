"""自绘控件：按钮、分段选择、开关、滑块。全部基于 Canvas + PIL 圆角图。"""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from typing import Callable, Optional, Sequence

from PIL import ImageTk

from . import paint
from .paint import (ACCENT, ACCENT_HI, ACCENT_LO, BG_TOP, BORDER, CARD_HI, DIM,
                    MUTED, PILL, TEXT, render_round_rect)

FONT_FAMILY = "Microsoft YaHei UI"


def ui_font(size: int, bold: bool = False) -> tuple:
    px = max(6, int(round(size)))
    return (FONT_FAMILY, -px, "bold" if bold else "normal")


def _mix(c1, c2, t: float):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def draw_icon(cv: tk.Canvas, cx: float, cy: float, kind: str, color: str,
              size: float = 16, tag: str = "icon") -> None:
    """在 Canvas 上画简洁的线性/实心图标。"""
    h = size / 2
    if kind == "record":
        r = size * 0.36
        cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill=color, outline="", tags=tag)
    elif kind == "stop":
        r = size * 0.30
        cv.create_rectangle(cx - r, cy - r, cx + r, cy + r, fill=color, outline="",
                            tags=tag)
    elif kind == "pause":
        w = size * 0.17
        gap = size * 0.11
        cv.create_rectangle(cx - gap - w, cy - h * 0.72, cx - gap, cy + h * 0.72,
                            fill=color, outline="", tags=tag)
        cv.create_rectangle(cx + gap, cy - h * 0.72, cx + gap + w, cy + h * 0.72,
                            fill=color, outline="", tags=tag)
    elif kind == "play":
        cv.create_polygon(cx - h * 0.5, cy - h * 0.72, cx - h * 0.5, cy + h * 0.72,
                          cx + h * 0.78, cy, fill=color, outline="", tags=tag)
    elif kind == "expand":
        d = size * 0.28
        for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            cv.create_line(cx + sx * h * 0.8, cy + sy * h * 0.8,
                           cx + sx * (h * 0.8 - d), cy + sy * h * 0.8,
                           fill=color, width=2, capstyle="round", tags=tag)
            cv.create_line(cx + sx * h * 0.8, cy + sy * h * 0.8,
                           cx + sx * h * 0.8, cy + sy * (h * 0.8 - d),
                           fill=color, width=2, capstyle="round", tags=tag)
    elif kind == "folder":
        cv.create_line(cx - h * 0.9, cy - h * 0.5, cx - h * 0.15, cy - h * 0.5,
                       fill=color, width=2, tags=tag)
        cv.create_rectangle(cx - h * 0.9, cy - h * 0.55, cx + h * 0.9, cy + h * 0.6,
                            outline=color, width=1.5, tags=tag)
    elif kind == "monitor":
        cv.create_rectangle(cx - h * 0.9, cy - h * 0.8, cx + h * 0.9, cy + h * 0.35,
                            outline=color, width=1.6, tags=tag)
        cv.create_line(cx, cy + h * 0.35, cx, cy + h * 0.65, fill=color, width=1.6,
                       tags=tag)
        cv.create_line(cx - h * 0.4, cy + h * 0.72, cx + h * 0.4, cy + h * 0.72,
                       fill=color, width=1.8, tags=tag)
    elif kind == "speaker":
        cv.create_polygon(cx - h * 0.85, cy - h * 0.28, cx - h * 0.35, cy - h * 0.28,
                          cx + h * 0.1, cy - h * 0.72, cx + h * 0.1, cy + h * 0.72,
                          cx - h * 0.35, cy + h * 0.28, cx - h * 0.85, cy + h * 0.28,
                          fill=color, outline="", tags=tag)
        cv.create_arc(cx + h * 0.05, cy - h * 0.55, cx + h * 0.95, cy + h * 0.55,
                      start=-55, extent=110, style="arc", outline=color, width=1.6,
                      tags=tag)
    elif kind == "mic":
        cv.create_rectangle(cx - h * 0.28, cy - h * 0.8, cx + h * 0.28, cy + h * 0.2,
                            outline=color, width=1.6, tags=tag)
        cv.create_arc(cx - h * 0.55, cy - h * 0.35, cx + h * 0.55, cy + h * 0.7,
                      start=180, extent=180, style="arc", outline=color, width=1.6,
                      tags=tag)
        cv.create_line(cx, cy + h * 0.7, cx, cy + h * 0.85, fill=color, width=1.6,
                       tags=tag)
    elif kind == "chevron":
        cv.create_line(cx - h * 0.3, cy - h * 0.25, cx + h * 0.2, cy + h * 0.25,
                       cx - h * 0.3, cy + h * 0.75, fill=color, width=2,
                       capstyle="round", joinstyle="round", tags=tag)
    elif kind == "refresh":
        cv.create_arc(cx - h * 0.75, cy - h * 0.75, cx + h * 0.75, cy + h * 0.75,
                      start=40, extent=280, style="arc", outline=color, width=1.8,
                      tags=tag)
        cv.create_polygon(cx + h * 0.55, cy - h * 0.85, cx + h * 0.95, cy - h * 0.35,
                          cx + h * 0.35, cy - h * 0.25, fill=color, outline="", tags=tag)
    elif kind == "close":
        cv.create_line(cx - h * 0.5, cy - h * 0.5, cx + h * 0.5, cy + h * 0.5,
                       fill=color, width=2, capstyle="round", tags=tag)
        cv.create_line(cx - h * 0.5, cy + h * 0.5, cx + h * 0.5, cy - h * 0.5,
                       fill=color, width=2, capstyle="round", tags=tag)


class Button(tk.Canvas):
    """圆角按钮，支持渐变、图标、悬停/按下/禁用。"""

    def __init__(self, master, width: int, height: int, text: str,
                 command: Optional[Callable] = None, *, bg: str = paint.hexc(paint.CARD),
                 fill=None, fg=TEXT, hover_fill=None, press_fill=None,
                 radius: int = 10, font_size: int = 13, bold: bool = True,
                 icon: Optional[str] = None, icon_color=None, gradient=None,
                 outline=None, disabled: bool = False, pad: int = 0):
        super().__init__(master, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0, takefocus=0)
        self._cw, self._ch = width, height
        self._text = text
        self._command = command
        self._fill = fill or CARD_HI
        self._fg = fg
        self._radius = radius
        self._font_size = font_size
        self._bold = bold
        self._icon = icon
        self._icon_color = icon_color or fg
        self._gradient = gradient
        self._outline = outline
        self._pad = pad
        self._enabled = not disabled
        self._state = "normal"
        self._bg = bg
        self._hover_fill = hover_fill or _mix(self._fill, (255, 255, 255), 0.08)
        self._press_fill = press_fill or _mix(self._fill, (0, 0, 0), 0.12)
        self._images: dict[str, ImageTk.PhotoImage] = {}
        self._make_images()
        self._img_id = self.create_image(0, 0, anchor="nw", image=self._images["normal"])
        self._font = ui_font(font_size, bold)
        self._text_id = self.create_text(width // 2, height // 2, text=text,
                                         fill=paint.hexc(fg), font=self._font,
                                         anchor="center")
        self._icon_ids: list[int] = []
        self._layout_text_icon()
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    # ------------------------------------------------------------ render
    def _make_images(self) -> None:
        radius = self._radius
        w, h = self._cw, self._ch
        if self._gradient:
            states = {
                "normal": self._gradient,
                "hover": (_mix(self._gradient[0], (255, 255, 255), 0.12),
                          _mix(self._gradient[1], (255, 255, 255), 0.08)),
                "press": (_mix(self._gradient[0], (0, 0, 0), 0.10),
                          _mix(self._gradient[1], (0, 0, 0), 0.14)),
                "disabled": (_mix(self._gradient[0], (12, 14, 20), 0.55),
                             _mix(self._gradient[1], (12, 14, 20), 0.60)),
            }
            for name, grad in states.items():
                img = render_round_rect(w, h, radius, None, self._bg,
                                        outline=self._outline, gradient=grad)
                self._images[name] = ImageTk.PhotoImage(img)
        else:
            for name, fill in (("normal", self._fill), ("hover", self._hover_fill),
                               ("press", self._press_fill), ("disabled", (30, 34, 44))):
                img = render_round_rect(w, h, radius, fill, self._bg,
                                        outline=self._outline)
                self._images[name] = ImageTk.PhotoImage(img)

    def _layout_text_icon(self) -> None:
        for item in self._icon_ids:
            self.delete(item)
        self._icon_ids = []
        for item in self.find_withtag("icon"):
            self.delete(item)
        raw = self._icon_color if self._enabled else (
            (250, 225, 225) if self._gradient else DIM)
        color = raw if isinstance(raw, str) else paint.hexc(raw)
        if not self._text and self._icon:
            icon_size = min(self._cw, self._ch) * 0.48
            draw_icon(self, self._cw / 2, self._ch / 2, self._icon, color, icon_size)
            return
        if not self._icon:
            return
        font = tkfont.Font(font=self._font)
        tw = font.measure(self._text)
        icon_size = max(8, self._font_size * 1.3)
        gap = icon_size * 0.52
        total = icon_size + gap + tw
        x = self._cw / 2 - total / 2
        draw_icon(self, x + icon_size / 2, self._ch / 2, self._icon, color, icon_size)
        self.coords(self._text_id, x + icon_size + gap + tw / 2, self._ch / 2)

    def _apply(self) -> None:
        if not self._enabled:
            self.itemconfigure(self._img_id, image=self._images.get("disabled",
                                                                    self._images["normal"]))
            self.itemconfigure(self._text_id,
                               fill=paint.hexc((250, 225, 225) if self._gradient else DIM))
        else:
            self.itemconfigure(self._img_id, image=self._images[self._state])
            self.itemconfigure(self._text_id, fill=paint.hexc(self._fg))
        self._layout_text_icon()
        self.tag_raise(self._text_id)

    # ------------------------------------------------------------ events
    def _on_enter(self, _):
        if self._enabled:
            self._state = "hover"
            self._apply()
            self.configure(cursor="hand2")

    def _on_leave(self, _):
        if self._enabled:
            self._state = "normal"
            self._apply()
            self.configure(cursor="")

    def _on_press(self, _):
        if self._enabled:
            self._state = "press"
            self._apply()

    def _on_release(self, event):
        if not self._enabled:
            return
        inside = 0 <= event.x <= self._cw and 0 <= event.y <= self._ch
        self._state = "normal"
        self._apply()
        if inside and self._command:
            self._command()

    # ------------------------------------------------------------ api
    def set_text(self, text: str) -> None:
        self._text = text
        self.itemconfigure(self._text_id, text=text)
        self._layout_text_icon()
        self.tag_raise(self._text_id)

    def set_icon(self, kind: Optional[str]) -> None:
        self._icon = kind
        self._layout_text_icon()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self._apply()

    @property
    def enabled(self) -> bool:
        return self._enabled


class Segmented(tk.Canvas):
    """分段选择器，选中项用强调色。"""

    def __init__(self, master, width: int, height: int, options: Sequence[str],
                 index: int, command: Callable[[int], None], *,
                 bg: str, active_fill=ACCENT, active_fg=(255, 255, 255),
                 idle_fg=MUTED, radius: int = 9, gap: int = 6, font_size: int = 12):
        super().__init__(master, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0, takefocus=0)
        self._cw, self._ch = width, height
        self._values = list(options)
        self._index = index
        self._command = command
        self._bg = bg
        self._radius = radius
        self._gap = gap
        self._font = ui_font(font_size, True)
        self._active_fill = active_fill
        self._active_fg = active_fg
        self._idle_fg = idle_fg
        self._hover = -1
        self._imgs: list[dict[str, ImageTk.PhotoImage]] = []
        self._text_ids: list[int] = []
        self._build()
        self.bind("<Button-1>", self._click)
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", self._leave)

    def _cell_width(self) -> float:
        n = len(self._values)
        return (self._cw - self._gap * (n - 1)) / n

    def _build(self) -> None:
        cw = self._cell_width()
        for i, opt in enumerate(self._values):
            x = i * (cw + self._gap)
            imgs = {
                "idle": ImageTk.PhotoImage(render_round_rect(
                    int(cw), self._ch, self._radius, PILL, self._bg,
                    outline=BORDER if self._bg == paint.hexc(paint.CARD) else None)),
                "hover": ImageTk.PhotoImage(render_round_rect(
                    int(cw), self._ch, self._radius, (30, 36, 47), self._bg)),
                "active": ImageTk.PhotoImage(render_round_rect(
                    int(cw), self._ch, self._radius, self._active_fill, self._bg)),
            }
            self._imgs.append(imgs)
            self.create_image(int(x), 0, anchor="nw", image=imgs["idle"])
            tid = self.create_text(int(x + cw / 2), self._ch // 2, text=opt,
                                   fill=paint.hexc(self._idle_fg), font=self._font)
            self._text_ids.append(tid)
        self._refresh()

    def _refresh(self) -> None:
        items = [i for i in self.find_all() if self.type(i) == "image"]
        cw = self._cell_width()
        for i, (imgs, tid) in enumerate(zip(self._imgs, self._text_ids)):
            state = "active" if i == self._index else ("hover" if i == self._hover else "idle")
            # 第 i 个 image 对应第 i 个 image 项
            if i < len(items):
                self.itemconfigure(items[i], image=imgs[state])
            self.itemconfigure(tid, fill=paint.hexc(self._active_fg if i == self._index
                                                    else self._idle_fg))
            self.coords(tid, int(i * (cw + self._gap) + cw / 2), self._ch // 2)

    def _index_at(self, x: int) -> int:
        cw = self._cell_width()
        for i in range(len(self._values)):
            if i * (cw + self._gap) <= x <= i * (cw + self._gap) + cw:
                return i
        return -1

    def _click(self, event) -> None:
        idx = self._index_at(event.x)
        if idx >= 0 and idx != self._index:
            self.set_index(idx, notify=True)

    def _motion(self, event) -> None:
        idx = self._index_at(event.x)
        if idx != self._hover:
            self._hover = idx
            self._refresh()
            self.configure(cursor="hand2" if idx >= 0 else "")

    def _leave(self, _) -> None:
        self._hover = -1
        self._refresh()
        self.configure(cursor="")

    def set_index(self, index: int, notify: bool = False) -> None:
        self._index = max(0, min(len(self._values) - 1, index))
        self._refresh()
        if notify and self._command:
            self._command(self._index)

    @property
    def index(self) -> int:
        return self._index


class Toggle(tk.Canvas):
    def __init__(self, master, width: int = 46, height: int = 26, value: bool = True,
                 command: Optional[Callable[[bool], None]] = None, *, bg: str):
        super().__init__(master, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0, takefocus=0)
        self._cw, self._ch = width, height
        self._value = value
        self._command = command
        self._bg = bg
        self._on = ImageTk.PhotoImage(self._render(True))
        self._off = ImageTk.PhotoImage(self._render(False))
        self._img_id = self.create_image(0, 0, anchor="nw",
                                         image=self._on if value else self._off)
        self.bind("<Button-1>", self._toggle)
        self.configure(cursor="hand2")

    def _render(self, on: bool):
        from PIL import Image, ImageDraw

        S = 2
        w, h = self._cw * S, self._ch * S
        img = Image.new("RGB", (w, h), self._bg)
        d = ImageDraw.Draw(img)
        track = (255, 77, 94) if on else (40, 46, 59)
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2, fill=track)
        r = h * 0.36
        cx = w - h / 2 if on else h / 2
        d.ellipse([cx - r, h / 2 - r, cx + r, h / 2 + r], fill=(255, 255, 255))
        return img.resize((self._cw, self._ch), Image.Resampling.LANCZOS)

    def _toggle(self, _) -> None:
        self.set(not self._value, notify=True)

    def set(self, value: bool, notify: bool = False) -> None:
        self._value = bool(value)
        self.itemconfigure(self._img_id, image=self._on if self._value else self._off)
        if notify and self._command:
            self._command(self._value)

    @property
    def value(self) -> bool:
        return self._value


class Slider(tk.Canvas):
    """0~1 滑块，右侧显示百分比。"""

    def __init__(self, master, width: int, height: int = 22, value: float = 1.0,
                 command: Optional[Callable[[float], None]] = None, *, bg: str,
                 accent=ACCENT):
        super().__init__(master, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0, takefocus=0)
        self._cw, self._ch = width, height
        self._value = max(0.0, min(1.0, value))
        self._command = command
        self._accent = paint.hexc(accent)
        self._enabled = True
        self._x0 = max(4, int(height * 0.32))
        self._x1 = width - max(28, int(height * 2.36))
        self._tw = max(3, int(height * 0.23))
        self._track = self.create_line(self._x0, height // 2, self._x1, height // 2,
                                       fill=paint.hexc(BORDER), width=self._tw,
                                       capstyle="round")
        self._fill = self.create_line(self._x0, height // 2, self._x0, height // 2,
                                      fill=self._accent, width=self._tw,
                                      capstyle="round")
        self._knob = self.create_oval(0, 0, 0, 0, fill="#ffffff", outline="")
        self._label = self.create_text(width - 2, height // 2, text="100%",
                                       fill=paint.hexc(MUTED),
                                       font=ui_font(max(8, int(height * 0.5))),
                                       anchor="e")
        self._knob_r = max(5, int(height * 0.32))
        self._draw()
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", lambda e: self._on_drag(e))
        self.configure(cursor="hand2")

    def _draw(self) -> None:
        x0, x1 = self._x0, self._x1
        x = x0 + (x1 - x0) * self._value
        self.coords(self._track, x0, self._ch // 2, x1, self._ch // 2)
        self.coords(self._fill, x0, self._ch // 2, max(x0, x), self._ch // 2)
        r = self._knob_r
        self.coords(self._knob, x - r, self._ch // 2 - r, x + r, self._ch // 2 + r)
        self.itemconfigure(self._label, text=f"{int(round(self._value * 100))}%")
        color = self._accent if self._enabled else paint.hexc(BORDER)
        self.itemconfigure(self._track, fill=paint.hexc(BORDER))
        self.itemconfigure(self._fill, fill=color)
        self.itemconfigure(self._knob, fill="#ffffff" if self._enabled else "#5a6272")
        self.itemconfigure(self._label, fill=paint.hexc(MUTED if self._enabled else DIM))

    def _update_from_x(self, x: float) -> None:
        x0, x1 = self._x0, self._x1
        value = (x - x0) / max(1, x1 - x0)
        value = max(0.0, min(1.0, value))
        if abs(value - self._value) > 0.001:
            self._value = value
            self._draw()
            if self._command:
                self._command(value)

    def _on_press(self, event) -> None:
        if self._enabled:
            self._update_from_x(event.x)

    def _on_drag(self, event) -> None:
        if self._enabled:
            self._update_from_x(event.x)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.configure(cursor="hand2" if enabled else "")
        self._draw()

    def set_value(self, value: float, notify: bool = False) -> None:
        self._value = max(0.0, min(1.0, value))
        self._draw()
        if notify and self._command:
            self._command(self._value)

    @property
    def value(self) -> float:
        return self._value
