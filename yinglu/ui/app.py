"""主程序：窗口、交互、录制流程。"""
from __future__ import annotations

import os
import ctypes
import queue
import subprocess
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageOps, ImageTk
from tkinter import filedialog, messagebox

from .. import audio, config, ffmpeg, hotkeys, winutil
from ..capture import CaptureSource
from ..engine import AudioOptions, RecordOptions, RecordingEngine, State, VideoOptions
from ..winutil import Rect, WindowInfo
from . import background, paint
from .background import H, LEFT_W, LEFT_X, RIGHT_W, RIGHT_X, W
from .floating import FloatingBar
from .paint import ACCENT, ACCENT_HI, ACCENT_LO, BORDER, CARD, CARD_HI, DIM, MUTED, TEXT
from .preview import Previewer
from .region import RegionSelector
from .toast import Toast
from .widgets import Button, Segmented, Slider, Toggle, draw_icon, ui_font
from .window_picker import WindowPicker

APP_NAME = "映录"
SCALES = (0.9, 1.0, 1.1, 1.25, 1.5)


def ensure_icon() -> Path:
    assets = config.APP_DIR / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    png = assets / "icon.png"
    if png.exists():
        return png
    size = 256
    S = 4
    n = size * S
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle([6 * S, 6 * S, n - 6 * S, n - 6 * S],
                                           radius=58 * S, fill=255)
    grad = Image.new("RGB", (1, n))
    px = grad.load()
    top, bottom = ACCENT_HI, (226, 32, 74)
    for y in range(n):
        t = y / (n - 1)
        px[0, y] = (int(top[0] + (bottom[0] - top[0]) * t),
                    int(top[1] + (bottom[1] - top[1]) * t),
                    int(top[2] + (bottom[2] - top[2]) * t))
    grad = grad.resize((n, n))
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    cx = cy = n / 2
    r = n * 0.22
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 255))
    r2 = r * 0.45
    d.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], fill=(255, 77, 94, 255))
    img = img.resize((size, size), Image.Resampling.LANCZOS)
    img.save(png)
    try:
        img.save(assets / "icon.ico",
                 sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    except Exception:
        pass
    return png


class App:
    def __init__(self):
        from .. import single_instance
        if not single_instance.acquire():
            ctypes.windll.user32.MessageBoxW(
                0, "映录已经在运行。\n请在任务栏或悬浮条中操作。", "映录", 0x40040)
            raise SystemExit(0)
        winutil.enable_dpi_awareness()
        self.cfg = config.Config()
        self.events: queue.Queue = queue.Queue()
        self.hotkey_queue: queue.Queue = queue.Queue()
        self.engine = RecordingEngine(self.events.put)
        self.previewer = Previewer()
        self.ui_state = "idle"
        self._modal = False
        self._quit_after_save = False
        self._closing = False
        self._poll_job = None
        self._preview_job = None
        self._countdown_job = None
        self._startup_jobs: list = []
        self._countdown = 0
        self._last_preview_photo = None
        self._preview_img_item = None
        self._rec_photo = None
        self._preview_mask = None
        self._status_extra = ""
        self._backend_label = ""
        self.scale = 1.0
        self.encoder = ffmpeg.X264
        self.source_kind = self.cfg.get("source_kind") or "screen"
        region = self.cfg.get("region")
        self.region: Optional[Rect] = None
        if isinstance(region, (list, tuple)) and len(region) == 4:
            try:
                self.region = Rect(*[int(v) for v in region])
            except Exception:
                self.region = None
        self.window_info: Optional[WindowInfo] = None
        hwnd = int(self.cfg.get("window_hwnd") or 0)
        title = self.cfg.get("window_title") or ""
        if hwnd and self._window_alive(hwnd):
            self.window_info = WindowInfo(hwnd, title, "", winutil.get_window_rect(hwnd))
        self.system_device = self._resolve_device("system", self.cfg.get("system_device") or "")
        self.mic_device = self._resolve_device("mic", self.cfg.get("mic_device") or "")
        if self.source_kind == "screen":
            self.source_kind = "screen"
        self._build()
        self.previewer.start()
        self.previewer.set_source(self._current_source())
        self.toast = Toast(self.root, scale=self.scale)
        self.floating = FloatingBar(self.root, self._from_floating_pause,
                                    self._from_floating_stop, self._show_window,
                                    scale=self.scale)
        self.hotkeys = hotkeys.HotkeyManager(self._on_hotkey)
        self.hotkeys.start()
        self._refresh_source_ui()
        self._refresh_audio_ui()
        self._apply_state()
        self._update_recent_ui()
        threading.Thread(target=self._detect_encoder, daemon=True, name="enc").start()
        self._poll_job = self.root.after(100, self._poll)
        self._preview_job = self.root.after(120, self._preview_tick)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._startup_jobs = [
            self.root.after(300, lambda: self._status(
                f"就绪 · 编码器 {self.encoder.label}")),
            self.root.after(1100, self._check_hotkeys),
        ]

    # ------------------------------------------------------------ build
    def _build(self) -> None:
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} · 屏幕录制")
        self.root.resizable(False, False)
        self.root.configure(bg=paint.hexc(paint.BG_TOP))
        try:
            icon_path = ensure_icon()
            self._icon = tk.PhotoImage(file=str(icon_path))
            self.root.iconphoto(True, self._icon)
        except Exception:
            self._icon = None
        self._build_ui()
        self.root.update_idletasks()
        try:
            winutil.set_dark_titlebar(int(self.root.wm_frame(), 16))
        except Exception:
            pass

    def _build_ui(self) -> None:
        self.scale = self._fit_scale(float(self.cfg.get("ui_scale") or 1.0))
        self.cfg.set("ui_scale", self.scale)
        self.root.geometry(f"{self.px(W)}x{self.px(H)}")
        for child in list(self.root.winfo_children()):
            if not isinstance(child, tk.Toplevel):
                child.destroy()
        self.bg_image = ImageTk.PhotoImage(background.build(self.scale))
        self.canvas = tk.Canvas(self.root, width=self.px(W), height=self.px(H),
                                highlightthickness=0, bd=0)
        self.canvas.place(x=0, y=0)
        self.canvas.create_image(0, 0, anchor="nw", image=self.bg_image)
        self._build_source()
        self._build_audio()
        self._build_output()
        self._build_recent()
        self._build_settings()
        self._build_record()
        self._build_preview()
        self._build_scale()

    # ------------------------------------------------------------ scale helpers
    def px(self, value: float) -> int:
        return int(round(value * self.scale))

    def fp(self, value: float) -> float:
        return value * self.scale

    @staticmethod
    def _clamp_scale(value: float) -> float:
        return min(SCALES, key=lambda p: abs(p - value))

    def _fit_scale(self, value: float) -> float:
        """只允许窗口能完整落在当前屏幕内的档位。"""
        value = self._clamp_scale(value)
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        for preset in reversed(SCALES):
            if preset <= value and W * preset <= sw - 24 and H * preset <= sh - 88:
                return preset
        return SCALES[0]

    def _build_scale(self) -> None:
        self.btn_zoom_out = Button(
            self.root, self.px(32), self.px(28), "A−", lambda: self._change_scale(-1),
            bg=paint.hexc(paint.BG_TOP), fill=(30, 35, 46), radius=self.px(8),
            font_size=self.px(11), bold=False)
        self.btn_zoom_out.place(x=self.px(738), y=self.px(25))
        self.lbl_zoom = tk.Label(self.root, text=f"{int(round(self.scale * 100))}%",
                                 bg=paint.hexc(paint.BG_TOP), fg=paint.hexc(TEXT),
                                 font=ui_font(self.fp(9.5)), anchor="center")
        self.lbl_zoom.place(x=self.px(774), y=self.px(25), width=self.px(46),
                            height=self.px(28))
        self.btn_zoom_in = Button(
            self.root, self.px(32), self.px(28), "A+", lambda: self._change_scale(1),
            bg=paint.hexc(paint.BG_TOP), fill=(30, 35, 46), radius=self.px(8),
            font_size=self.px(11), bold=False)
        self.btn_zoom_in.place(x=self.px(824), y=self.px(25))

    def _change_scale(self, delta: int) -> None:
        if self.ui_state != "idle":
            self.toast.show("录制中不能调整界面大小")
            return
        presets = list(SCALES)
        idx = presets.index(self._clamp_scale(self.scale))
        new = presets[max(0, min(len(presets) - 1, idx + delta))]
        if new != self.scale:
            self.root.after(10, lambda: self._apply_scale(new))

    def _apply_scale(self, scale: float) -> None:
        if self.ui_state != "idle":
            return
        scale = self._fit_scale(scale)
        self.cfg.set("ui_scale", scale)
        self.cfg.save()
        for overlay in (getattr(self, "toast", None), getattr(self, "floating", None)):
            if overlay is not None:
                try:
                    overlay.hide()
                except Exception:
                    pass
                try:
                    overlay.win.destroy()
                except Exception:
                    pass
        self._build_ui()
        self.toast = Toast(self.root, scale=self.scale)
        self.floating = FloatingBar(self.root, self._from_floating_pause,
                                    self._from_floating_stop, self._show_window,
                                    scale=self.scale)
        self._refresh_source_ui()
        self._refresh_audio_ui()
        self._update_output_ui()
        self._update_recent_ui()
        self._apply_state()
        self._status(f"就绪 · 编码器 {self.encoder.label}")
        self.previewer.set_source(self._current_source())

    # ------------------------------------------------------------ source
    def _build_source(self) -> None:
        self.seg_source = Segmented(
            self.root, self.px(364), self.px(40), ["全屏", "区域", "窗口"],
            {"screen": 0, "region": 1, "window": 2}.get(self.source_kind, 0),
            self._on_source_change, bg=paint.hexc(CARD), font_size=self.px(12))
        self.seg_source.place(x=self.px(44), y=self.px(134))

        self.source_info = tk.Label(self.root, text="", bg=paint.hexc(CARD),
                                    fg=paint.hexc(TEXT), font=ui_font(self.fp(10.5)),
                                    anchor="w")
        self.source_info.place(x=self.px(46), y=self.px(184))

        self.source_hint = tk.Label(self.root, text="", bg=paint.hexc(CARD),
                                    fg=paint.hexc(DIM), font=ui_font(self.fp(9)), anchor="w")
        self.source_hint.place(x=self.px(46), y=self.px(218))

        self.btn_source = Button(self.root, self.px(96), self.px(32), "选择区域",
                                 self._on_source_action, bg=paint.hexc(CARD),
                                 fill=(32, 37, 49), radius=self.px(9),
                                 font_size=self.px(10))
        self.btn_source.place(x=self.px(312), y=self.px(180))

    def _on_source_change(self, index: int) -> None:
        if self.ui_state != "idle":
            return
        kind = ["screen", "region", "window"][index]
        self.source_kind = kind
        self.cfg.set("source_kind", kind)
        if kind == "region" and self.region is None:
            self._pick_region()
            return
        if kind == "window" and self.window_info is None:
            self._pick_window()
            return
        self._refresh_source_ui()

    def _on_source_action(self) -> None:
        if self.ui_state != "idle":
            return
        if self.source_kind == "region":
            self._pick_region()
        elif self.source_kind == "window":
            self._pick_window()

    def _pick_region(self) -> None:
        if self._modal:
            return
        self._modal = True

        def done(rect):
            self._modal = False
            if rect is not None:
                self.region = rect
                self.cfg.set("region", list(rect.as_tuple()))
                self.cfg.set("source_kind", "region")
                self.source_kind = "region"
                self.seg_source.set_index(1)
            self._refresh_source_ui()

        RegionSelector(self.root, done, scale=self.scale).show()

    def _pick_window(self) -> None:
        if self._modal:
            return
        self._modal = True

        def done(info):
            self._modal = False
            if info is not None:
                self.window_info = info
                self.cfg.set("window_hwnd", info.hwnd)
                self.cfg.set("window_title", info.title)
                self.cfg.set("source_kind", "window")
                self.source_kind = "window"
                self.seg_source.set_index(2)
            self._refresh_source_ui()

        WindowPicker(self.root, done, scale=self.scale).show()

    def _window_alive(self, hwnd: int) -> bool:
        try:
            import ctypes
            return bool(ctypes.windll.user32.IsWindow(hwnd))
        except Exception:
            return False

    def _current_source(self) -> Optional[CaptureSource]:
        if self.source_kind == "region":
            if self.region is None:
                return None
            return CaptureSource("region", rect=self.region, label="区域")
        if self.source_kind == "window":
            if self.window_info is None:
                return None
            if not self._window_alive(self.window_info.hwnd):
                return None
            r = winutil.get_window_rect(self.window_info.hwnd)
            return CaptureSource("window", hwnd=self.window_info.hwnd,
                                 label=self.window_info.title, rect=r)
        return CaptureSource("screen", rect=winutil.primary_screen(), label="全屏")

    def _refresh_source_ui(self) -> None:
        if self.source_kind == "region":
            if self.region:
                text = f"{self.region.w} × {self.region.h}"
                hint = "拖动框选屏幕上的任意区域"
            else:
                text = "尚未选择区域"
                hint = "点击右侧按钮框选录制区域"
            self.btn_source.set_text("重新选择")
            self.btn_source.place(x=self.px(312), y=self.px(180))
        elif self.source_kind == "window":
            if self.window_info:
                r = winutil.get_window_rect(self.window_info.hwnd)
                text = self._elide(self.window_info.title, self.px(240),
                                   self.fp(10.5)) + f"  ·  {r.w} × {r.h}"
                hint = "只录制所选窗口，窗口移动时自动跟随"
            else:
                text = "尚未选择窗口"
                hint = "点击右侧按钮选择一个窗口"
            self.btn_source.set_text("重新选择")
            self.btn_source.place(x=self.px(312), y=self.px(180))
        else:
            r = winutil.primary_screen()
            text = f"主显示器  ·  {r.w} × {r.h}"
            hint = "录制主显示器的完整画面"
            self.btn_source.place_forget()
        self.source_info.configure(text=text)
        self.source_hint.configure(text=hint)
        if self.ui_state == "idle":
            self.previewer.set_source(self._current_source())

    # ------------------------------------------------------------ audio
    def _build_audio(self) -> None:
        self.icon_system = tk.Canvas(self.root, width=self.px(22), height=self.px(22),
                                     bg=paint.hexc(CARD), highlightthickness=0, bd=0)
        self.icon_system.place(x=self.px(40), y=self.px(305))
        self.icon_mic = tk.Canvas(self.root, width=self.px(22), height=self.px(22),
                                  bg=paint.hexc(CARD), highlightthickness=0, bd=0)
        self.icon_mic.place(x=self.px(40), y=self.px(379))

        self.lbl_system = tk.Label(self.root, text="系统声音", bg=paint.hexc(CARD),
                                   fg=paint.hexc(TEXT), font=ui_font(self.fp(10.5)),
                                   anchor="w")
        self.lbl_system.place(x=self.px(78), y=self.px(300))
        self.lbl_system_sub = tk.Label(self.root, text="", bg=paint.hexc(CARD),
                                       fg=paint.hexc(DIM), font=ui_font(self.fp(8.5)),
                                       anchor="w", cursor="hand2")
        self.lbl_system_sub.place(x=self.px(78), y=self.px(319))
        self.lbl_system_sub.bind("<Button-1>", lambda e: self._choose_device("system"))

        self.lbl_mic = tk.Label(self.root, text="麦克风", bg=paint.hexc(CARD),
                                fg=paint.hexc(TEXT), font=ui_font(self.fp(10.5)),
                                anchor="w")
        self.lbl_mic.place(x=self.px(78), y=self.px(374))
        self.lbl_mic_sub = tk.Label(self.root, text="", bg=paint.hexc(CARD),
                                    fg=paint.hexc(DIM), font=ui_font(self.fp(8.5)),
                                    anchor="w", cursor="hand2")
        self.lbl_mic_sub.place(x=self.px(78), y=self.px(393))
        self.lbl_mic_sub.bind("<Button-1>", lambda e: self._choose_device("mic"))

        self.tog_system = Toggle(self.root, self.px(46), self.px(26),
                                 bool(self.cfg.get("system_audio")),
                                 self._on_system_toggle, bg=paint.hexc(CARD))
        self.tog_system.place(x=self.px(356), y=self.px(306))
        self.tog_mic = Toggle(self.root, self.px(46), self.px(26),
                              bool(self.cfg.get("mic")),
                              self._on_mic_toggle, bg=paint.hexc(CARD))
        self.tog_mic.place(x=self.px(356), y=self.px(380))

        self.sld_system = Slider(self.root, self.px(320), self.px(22),
                                 float(self.cfg.get("system_volume") or 0.0),
                                 self._on_system_volume, bg=paint.hexc(CARD))
        self.sld_system.place(x=self.px(68), y=self.px(344))
        self.sld_mic = Slider(self.root, self.px(320), self.px(22),
                              float(self.cfg.get("mic_volume") or 0.0),
                              self._on_mic_volume, bg=paint.hexc(CARD))
        self.sld_mic.place(x=self.px(68), y=self.px(418))

    def _render_audio_icons(self) -> None:
        for canvas, kind, on in ((self.icon_system, "speaker", self.tog_system.value),
                                 (self.icon_mic, "mic", self.tog_mic.value)):
            canvas.delete("all")
            draw_icon(canvas, self.px(11), self.px(11), kind,
                      paint.hexc(TEXT if on else DIM), self.px(18))

    def _refresh_audio_ui(self) -> None:
        sys_name = self.system_device.name if self.system_device else "未找到输出设备"
        mic_name = self.mic_device.name if self.mic_device else "未找到麦克风"
        self.lbl_system_sub.configure(
            text=self._elide(sys_name, self.px(270), self.fp(8.5)))
        self.lbl_mic_sub.configure(
            text=self._elide(mic_name, self.px(270), self.fp(8.5)))
        self.sld_system.set_enabled(self.tog_system.value)
        self.sld_mic.set_enabled(self.tog_mic.value)
        self._render_audio_icons()

    def _resolve_device(self, kind: str, name: str):
        devices = audio.list_system_devices() if kind == "system" else audio.list_mic_devices()
        for d in devices:
            if d.name == name:
                return d
        return devices[0] if devices else None

    def _choose_device(self, kind: str) -> None:
        if self.ui_state != "idle":
            return
        devices = audio.list_system_devices() if kind == "system" else audio.list_mic_devices()
        if not devices:
            self.toast.show("没有找到可用的音频设备")
            return
        menu = tk.Menu(self.root, tearoff=0, bg="#1a1f2a", fg=paint.hexc(TEXT),
                       activebackground="#2b3342", activeforeground=paint.hexc(TEXT),
                       bd=0, font=ui_font(self.fp(9)))
        for dev in devices:
            label = ("● " if dev.is_default else "   ") + dev.name
            menu.add_command(label=label,
                             command=lambda d=dev: self._set_device(kind, d))
        if kind == "mic" and self.mic_device is None:
            menu.add_separator()
        menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        menu.grab_release()

    def _set_device(self, kind: str, device: audio.AudioDevice) -> None:
        if kind == "system":
            self.system_device = device
            self.cfg.set("system_device", device.name)
        else:
            self.mic_device = device
            self.cfg.set("mic_device", device.name)
        self._refresh_audio_ui()

    def _on_system_toggle(self, value: bool) -> None:
        self.cfg.set("system_audio", value)
        self.sld_system.set_enabled(value)
        self._render_audio_icons()

    def _on_mic_toggle(self, value: bool) -> None:
        self.cfg.set("mic", value)
        self.sld_mic.set_enabled(value)
        self._render_audio_icons()

    def _on_system_volume(self, value: float) -> None:
        self.cfg.set("system_volume", round(value, 3))

    def _on_mic_volume(self, value: float) -> None:
        self.cfg.set("mic_volume", round(value, 3))

    # ------------------------------------------------------------ output / recent
    def _build_output(self) -> None:
        self.lbl_output = tk.Label(self.root, text="", bg=paint.hexc(CARD),
                                   fg=paint.hexc(MUTED), font=ui_font(self.fp(9.5)),
                                   anchor="w")
        self.lbl_output.place(x=self.px(28), y=self.px(500))
        self.btn_output = Button(self.root, self.px(80), self.px(30), "更改",
                                 self._change_output_dir, bg=paint.hexc(paint.BG_TOP),
                                 fill=(30, 35, 46), radius=self.px(9),
                                 font_size=self.px(10))
        self.btn_output.place(x=self.px(344), y=self.px(480))
        self._update_output_ui()

    def _update_output_ui(self) -> None:
        path = str(self.cfg.get("output_dir") or "")
        self.lbl_output.configure(text=self._elide(path, self.px(300), self.fp(9.5)))
        self.lbl_output.configure(fg=paint.hexc(MUTED))

    def _change_output_dir(self) -> None:
        if self.ui_state != "idle":
            return
        current = str(self.cfg.get("output_dir") or "")
        try:
            chosen = filedialog.askdirectory(initialdir=current, title="选择保存位置",
                                             mustexist=True)
        except Exception:
            chosen = ""
        if chosen:
            self.cfg.set("output_dir", chosen)
            self._update_output_ui()

    def _build_recent(self) -> None:
        self.lbl_recent = tk.Label(self.root, text="还没有录制文件",
                                   bg=paint.hexc(paint.BG_TOP), fg=paint.hexc(TEXT),
                                   font=ui_font(self.fp(9.5)), anchor="w")
        self.lbl_recent.place(x=self.px(28), y=self.px(560))
        self.lbl_recent_meta = tk.Label(self.root, text="",
                                        bg=paint.hexc(paint.BG_TOP),
                                        fg=paint.hexc(DIM), font=ui_font(self.fp(8.5)),
                                        anchor="w")
        self.lbl_recent_meta.place(x=self.px(28), y=self.px(580))
        self.btn_open_folder = Button(self.root, self.px(84), self.px(28), "打开",
                                      self._open_output_dir,
                                      bg=paint.hexc(paint.BG_TOP), fill=(30, 35, 46),
                                      radius=self.px(8), font_size=self.px(9),
                                      icon="folder", icon_color=paint.MUTED)
        self.btn_open_folder.place(x=self.px(340), y=self.px(552))
        self.btn_open_folder.place_forget()

    def _update_recent_ui(self) -> None:
        path = self.cfg.get("last_file") or ""
        duration = float(self.cfg.get("last_duration") or 0)
        size = int(self.cfg.get("last_size") or 0)
        if path and os.path.isfile(path):
            self.lbl_recent.configure(
                text=self._elide(os.path.basename(path), self.px(300), self.fp(9.5)),
                fg=paint.hexc(TEXT))
            minutes, seconds = divmod(int(duration), 60)
            self.lbl_recent_meta.configure(
                text=f"{minutes:02d}:{seconds:02d}   ·   {size / 1024 / 1024:.1f} MB")
            self.btn_open_folder.place(x=self.px(340), y=self.px(552))
            self._last_file = path
        else:
            self.lbl_recent.configure(text="还没有录制文件", fg=paint.hexc(DIM))
            self.lbl_recent_meta.configure(text="录制完成后会显示在这里")
            self.btn_open_folder.place_forget()
            self._last_file = ""

    def _open_output_dir(self) -> None:
        folder = os.path.dirname(self._last_file) if getattr(self, "_last_file", "") else \
            str(self.cfg.get("output_dir") or "")
        try:
            os.startfile(folder)
        except Exception:
            self.toast.show("无法打开文件夹")

    # ------------------------------------------------------------ settings
    def _build_settings(self) -> None:
        fps_index = 0 if int(self.cfg.get("fps") or 30) == 30 else 1
        self.seg_fps = Segmented(self.root, self.px(88), self.px(32), ["30", "60"],
                                 fps_index, self._on_fps, bg=paint.hexc(CARD),
                                 font_size=self.px(11))
        self.seg_fps.place(x=self.px(514), y=self.px(388))

        quality = {"standard": 0, "high": 1, "ultra": 2}.get(str(self.cfg.get("quality")), 1)
        self.seg_quality = Segmented(self.root, self.px(182), self.px(32),
                                     ["标准", "高清", "超清"], quality,
                                     self._on_quality, bg=paint.hexc(CARD),
                                     font_size=self.px(11))
        self.seg_quality.place(x=self.px(674), y=self.px(388))

        countdown = {0: 0, 3: 1, 5: 2}.get(int(self.cfg.get("countdown") or 0), 0)
        self.seg_countdown = Segmented(self.root, self.px(120), self.px(32),
                                       ["关", "3 秒", "5 秒"], countdown,
                                       self._on_countdown, bg=paint.hexc(CARD),
                                       font_size=self.px(11))
        self.seg_countdown.place(x=self.px(530), y=self.px(442))

        self.tog_cursor = Toggle(self.root, self.px(46), self.px(26),
                                 bool(self.cfg.get("cursor")),
                                 self._on_cursor, bg=paint.hexc(CARD))
        self.tog_cursor.place(x=self.px(736), y=self.px(445))

    def _on_fps(self, index: int) -> None:
        self.cfg.set("fps", 30 if index == 0 else 60)

    def _on_quality(self, index: int) -> None:
        self.cfg.set("quality", ["standard", "high", "ultra"][index])

    def _on_countdown(self, index: int) -> None:
        self.cfg.set("countdown", [0, 3, 5][index])

    def _on_cursor(self, value: bool) -> None:
        self.cfg.set("cursor", value)

    # ------------------------------------------------------------ record button
    def _build_record(self) -> None:
        self.btn_record = Button(
            self.root, self.px(424), self.px(64), "开始录制", self._toggle_record,
            bg=paint.hexc(paint.BG_TOP), gradient=(ACCENT_HI, ACCENT_LO),
            radius=self.px(16), font_size=self.px(15), icon="record",
            icon_color="#ffffff")
        self.btn_record.place(x=self.px(448), y=self.px(528))

        self.btn_pause = Button(self.root, self.px(130), self.px(64), "暂停",
                                self._toggle_pause, bg=paint.hexc(paint.BG_TOP),
                                fill=(32, 37, 49), radius=self.px(16),
                                font_size=self.px(12), icon="pause",
                                icon_color=paint.TEXT)
        self.btn_stop = Button(self.root, self.px(282), self.px(64), "停止录制",
                               self.stop_recording, bg=paint.hexc(paint.BG_TOP),
                               gradient=(ACCENT_HI, ACCENT_LO), radius=self.px(16),
                               font_size=self.px(14), icon="stop", icon_color="#ffffff")
        self.status_label = tk.Label(self.root, text="", bg=paint.hexc(paint.BG_TOP),
                                     fg=paint.hexc(DIM), font=ui_font(self.fp(9)),
                                     anchor="e")
        self.status_label.place(x=self.px(448), y=self.px(602),
                                width=self.px(424))

    # ------------------------------------------------------------ preview
    def _build_preview(self) -> None:
        self.pw = self.px(400)
        self.ph = self.px(225)
        self.preview_canvas = tk.Canvas(self.root, width=self.pw, height=self.ph,
                                        bg=paint.hexc(CARD), highlightthickness=0,
                                        bd=0)
        self.preview_canvas.place(x=self.px(460), y=self.px(108))
        self._preview_img_item = self.preview_canvas.create_image(
            0, 0, anchor="nw", image=self._blank_preview())
        self._placeholder_photo = ImageTk.PhotoImage(self._make_placeholder())
        placeholder = self.preview_canvas.create_image(0, 0, anchor="nw",
                                                       image=self._placeholder_photo)
        self._placeholder_items = [placeholder]

        # 录制角标
        self._rec_photo = ImageTk.PhotoImage(self._make_badge())
        self._rec_img = self.preview_canvas.create_image(
            self.px(12), self.px(12), anchor="nw", image=self._rec_photo, state="hidden")
        self._rec_dot = self.preview_canvas.create_oval(
            self.px(24), self.px(25), self.px(34), self.px(35),
            fill=paint.hexc(ACCENT), outline="", state="hidden")
        self._rec_text = self.preview_canvas.create_text(
            self.px(42), self.px(30), text="REC  00:00", anchor="w", fill="#ffffff",
            font=("Consolas", -max(9, int(13 * self.scale)), "bold"), state="hidden")
        # 倒计时遮罩
        self._count_rect = self.preview_canvas.create_rectangle(
            0, 0, self.pw, self.ph, fill="#05070b", stipple="gray75", outline="",
            state="hidden")
        self._count_text = self.preview_canvas.create_text(
            self.pw // 2, self.px(104), text="3", fill="#ffffff",
            font=("Microsoft YaHei UI", -max(24, int(64 * self.scale)), "bold"),
            state="hidden")
        self._count_sub = self.preview_canvas.create_text(
            self.pw // 2, self.px(162), text="即将开始录制",
            fill=paint.hexc((214, 220, 232)), font=ui_font(self.fp(10)), state="hidden")

    def _make_placeholder(self) -> Image.Image:
        w, h = self.pw, self.ph
        img = Image.new("RGB", (w, h), CARD)
        d = ImageDraw.Draw(img)
        k = self.scale
        line = (42, 48, 62)
        d.rounded_rectangle([152 * k, 62 * k, 248 * k, 130 * k],
                            radius=max(3, 8 * k), outline=line, width=max(1, int(2 * k)))
        d.line([200 * k, 130 * k, 200 * k, 146 * k], fill=line, width=max(1, int(2 * k)))
        d.line([181 * k, 148 * k, 219 * k, 148 * k], fill=line, width=max(1, int(2 * k)))
        d.text((w // 2, 178 * k), "实时预览",
               font=paint.pil_font(max(8, int(11 * k))), fill=DIM, anchor="mm")
        return img

    def _make_badge(self) -> Image.Image:
        S = 2
        w, h = self.px(152), self.px(30)
        img = Image.new("RGBA", (w * S, h * S), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, w * S - 1, h * S - 1],
                            radius=max(4, int(10 * self.scale)) * S,
                            fill=(10, 12, 17, 215), outline=(58, 66, 84, 220), width=S)
        return img.resize((w, h), Image.Resampling.LANCZOS)

    def _blank_preview(self) -> ImageTk.PhotoImage:
        w, h = self.pw, self.ph
        img = Image.new("RGB", (w, h), CARD)
        photo = ImageTk.PhotoImage(img)
        self._blank_photo = photo
        return photo

    def _round_mask(self, w: int, h: int, radius: int) -> Image.Image:
        if self._preview_mask is None or self._preview_mask.size != (w, h):
            S = 2
            m = Image.new("L", (w * S, h * S), 0)
            ImageDraw.Draw(m).rounded_rectangle([0, 0, w * S - 1, h * S - 1],
                                                radius=radius * S, fill=255)
            self._preview_mask = m.resize((w, h), Image.Resampling.LANCZOS)
        return self._preview_mask

    def _draw_preview(self, img: Image.Image) -> None:
        w, h = self.pw, self.ph
        fitted = ImageOps.contain(img, (w - 2, h - 2), Image.Resampling.BILINEAR)
        base = Image.new("RGB", (w, h), (10, 12, 17))
        base.paste(fitted, ((w - fitted.width) // 2, (h - fitted.height) // 2))
        rounded = Image.composite(base, Image.new("RGB", (w, h), CARD),
                                  self._round_mask(w, h, self.px(12)))
        photo = ImageTk.PhotoImage(rounded)
        self._last_preview_photo = photo
        self.preview_canvas.itemconfigure(self._preview_img_item, image=photo)
        for item in self._placeholder_items:
            self.preview_canvas.itemconfigure(item, state="hidden")

    def _preview_tick(self) -> None:
        if getattr(self, "_closing", False):
            return
        try:
            img = None
            if self.ui_state in ("recording", "paused"):
                data = self.engine.get_preview()
                if data:
                    raw, size = data
                    try:
                        img = Image.frombytes("RGB", size, raw)
                    except Exception:
                        img = None
            elif self.ui_state in ("idle", "countdown"):
                img = self.previewer.latest()
            if img is not None:
                self._draw_preview(img)
        except Exception:
            pass
        if not self._closing:
            self._preview_job = self.root.after(180, self._preview_tick)

    def _set_rec_badge(self, visible: bool, paused: bool = False, text: str = "REC  00:00") -> None:
        state = "normal" if visible else "hidden"
        for item in (self._rec_img, self._rec_dot, self._rec_text):
            self.preview_canvas.itemconfigure(item, state=state)
        if visible:
            self.preview_canvas.itemconfigure(self._rec_text, text=text)
            self.preview_canvas.itemconfigure(
                self._rec_dot, fill=paint.hexc((240, 178, 60) if paused else ACCENT))

    def _show_countdown(self, n: int) -> None:
        for item in (self._count_rect, self._count_text, self._count_sub):
            self.preview_canvas.itemconfigure(item, state="normal")
        self.preview_canvas.itemconfigure(self._count_text, text=str(n))

    def _hide_countdown(self) -> None:
        for item in (self._count_rect, self._count_text, self._count_sub):
            self.preview_canvas.itemconfigure(item, state="hidden")

    # ------------------------------------------------------------ state
    def _apply_state(self) -> None:
        s = self.ui_state
        if s == "idle":
            self.btn_record.place(x=self.px(448), y=self.px(528))
            self.btn_record.set_text("开始录制")
            self.btn_record.set_icon("record")
            self.btn_record.set_enabled(True)
            self.btn_pause.place_forget()
            self.btn_stop.place_forget()
            self._set_rec_badge(False)
            self._hide_countdown()
            self.status_label.configure(fg=paint.hexc(DIM))
        elif s == "countdown":
            self.btn_record.place(x=self.px(448), y=self.px(528))
            self.btn_record.set_text("准备中…")
            self.btn_record.set_icon(None)
            self.btn_record.set_enabled(False)
            self.btn_pause.place_forget()
            self.btn_stop.place_forget()
        elif s in ("recording", "paused"):
            self.btn_record.place_forget()
            self.btn_pause.place_forget()
            self.btn_stop.place_forget()
            self.btn_pause.place(x=self.px(448), y=self.px(528))
            self.btn_stop.place(x=self.px(590), y=self.px(528))
            if s == "paused":
                self.btn_pause.set_text("继续")
                self.btn_pause.set_icon("play")
                self._set_rec_badge(True, True, "已暂停")
            else:
                self.btn_pause.set_text("暂停")
                self.btn_pause.set_icon("pause")
                self._set_rec_badge(True, False, "REC  00:00")
            self.btn_pause.set_enabled(True)
            self.btn_stop.set_enabled(True)
        elif s == "saving":
            self.btn_pause.place_forget()
            self.btn_stop.place_forget()
            self.btn_record.place(x=self.px(448), y=self.px(528))
            self.btn_record.set_text("正在保存…")
            self.btn_record.set_icon(None)
            self.btn_record.set_enabled(False)
            self._set_rec_badge(False)
            self._hide_countdown()

    def _status(self, text: str) -> None:
        self.status_label.configure(text=text)

    def _toggle_record(self) -> None:
        if self.ui_state == "idle":
            self.start_recording()
        elif self.ui_state == "countdown":
            self._cancel_countdown()
        elif self.ui_state in ("recording", "paused"):
            self.stop_recording()

    def _cancel_countdown(self) -> None:
        if self.ui_state != "countdown":
            return
        self._countdown = 0
        self.ui_state = "idle"
        self._hide_countdown()
        self._apply_state()
        self._status("已取消录制")

    def start_recording(self) -> None:
        if self.ui_state != "idle" or self._modal:
            return
        source = self._current_source()
        if source is None:
            if self.source_kind == "region":
                self.toast.show("请先选择录制区域")
                self._pick_region()
            elif self.source_kind == "window":
                self.toast.show("请先选择录制窗口")
                self._pick_window()
            return
        if source.kind == "window":
            title = self.window_info.title if self.window_info else ""
            if not title or not self._window_alive(self.window_info.hwnd):
                self.toast.show("窗口已关闭，请重新选择")
                self._pick_window()
                return
        out_dir = str(self.cfg.get("output_dir") or "")
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception:
            self.toast.show("保存目录不可用，请在设置中更改")
            return
        self._pending_source = source
        filename = f"录屏 {time.strftime('%Y-%m-%d %H-%M-%S')}.mp4"
        self._pending_path = os.path.join(out_dir, filename)

        countdown = int(self.cfg.get("countdown") or 0)
        if countdown > 0:
            self.ui_state = "countdown"
            self._countdown = countdown
            self._apply_state()
            self._show_window()
            self._status(f"{countdown} 秒后开始录制")
            self._tick_countdown()
        else:
            self._do_start()

    def _tick_countdown(self) -> None:
        if self._closing or self.ui_state != "countdown":
            return
        if self._countdown <= 0:
            self._hide_countdown()
            self._do_start()
            return
        self._show_countdown(self._countdown)
        self._countdown -= 1
        self._countdown_job = self.root.after(1000, self._tick_countdown)

    def _do_start(self) -> None:
        if self._closing:
            return
        source = getattr(self, "_pending_source", None)
        path = getattr(self, "_pending_path", None)
        if source is None or path is None:
            self.ui_state = "idle"
            self._apply_state()
            return
        options = RecordOptions(
            source=source,
            video=VideoOptions(fps=int(self.cfg.get("fps") or 30),
                               quality=str(self.cfg.get("quality") or "high"),
                               encoder=self.encoder),
            audio=AudioOptions(
                system=bool(self.cfg.get("system_audio")),
                mic=bool(self.cfg.get("mic")),
                system_device=self.system_device,
                mic_device=self.mic_device,
                system_volume=float(self.cfg.get("system_volume") or 0.0),
                mic_volume=float(self.cfg.get("mic_volume") or 0.0)),
            out_path=path,
            draw_cursor=bool(self.cfg.get("cursor")),
        )
        # 先隐藏主窗口再开录，避免把界面录进开头
        self.root.withdraw()
        try:
            self.root.update_idletasks()
        except Exception:
            pass
        time.sleep(0.12)
        ok, err = self.engine.start(options)
        if not ok:
            self.ui_state = "idle"
            self._apply_state()
            self._show_window()
            messagebox.showerror("无法开始录制", err, parent=self.root)
            return
        self.ui_state = "recording"
        self._hide_countdown()
        self._apply_state()
        self.previewer.set_paused(True)
        self._status("录制中 · F9 停止")
        self.floating.show(False)

    def _autohide_window(self) -> None:
        if self.ui_state in ("recording", "paused") and not self._modal:
            self.root.withdraw()

    def _autohide_window(self) -> None:
        if self.ui_state in ("recording", "paused") and not self._modal:
            self.root.withdraw()

    def stop_recording(self) -> None:
        if self.ui_state not in ("recording", "paused"):
            return
        self.engine.stop()
        self.ui_state = "saving"
        self._apply_state()
        self._status("正在保存…")
        self._show_window()
        self.floating.hide()
        self.previewer.set_paused(False)

    def _toggle_pause(self) -> None:
        if self.ui_state == "recording":
            self.engine.pause()
        elif self.ui_state == "paused":
            self.engine.resume()

    def _from_floating_pause(self, paused: bool) -> None:
        if paused:
            self.engine.pause()
        else:
            self.engine.resume()

    def _from_floating_stop(self) -> None:
        self.stop_recording()

    def _show_window(self) -> None:
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except Exception:
            pass

    # ------------------------------------------------------------ events
    def _handle_event(self, ev: dict) -> None:
        kind = ev.get("type")
        if kind == "warning":
            self.toast.show(str(ev.get("message") or "录制出现问题"))
            return
        if kind == "encoder":
            enc = ev.get("encoder")
            if enc is not None:
                self.encoder = enc
                if self.ui_state == "idle":
                    self._status(f"就绪 · 编码器 {enc.label}")
            return
        if kind == "backend":
            label = "DXGI" if ev.get("backend") == "dxgi" else "GDI"
            self._backend_label = label
            if self.ui_state in ("recording", "paused"):
                self._status(f"录制中 · {label} 抓屏 · F9 停止")
            return
        if kind != "state":
            return
        state = ev.get("state")
        if state == "recording":
            self.ui_state = "recording"
            self._apply_state()
            self.floating.set_paused(False)
        elif state == "paused":
            self.ui_state = "paused"
            self._apply_state()
            self.floating.set_paused(True)
        elif state == "saving":
            self.ui_state = "saving"
            self._apply_state()
            self.floating.hide()
        elif state == "idle":
            error = ev.get("error")
            saved = ev.get("saved")
            self.ui_state = "idle"
            self._apply_state()
            self._show_window()
            self.floating.hide()
            self.previewer.set_paused(False)
            self.previewer.set_source(self._current_source())
            if error:
                self._status("录制失败")
                messagebox.showerror("录制失败", str(error), parent=self.root)
            elif saved:
                size = int(ev.get("size") or 0)
                duration = float(ev.get("duration") or 0)
                self.cfg.set("last_file", saved)
                self.cfg.set("last_duration", duration)
                self.cfg.set("last_size", size)
                self.cfg.set("last_backend", self._backend_label or "GDI")
                self.cfg.save()
                self._update_recent_ui()
                self._status(f"已保存 · {os.path.basename(saved)}")
                self.toast.show(f"已保存  {os.path.basename(saved)}")
            if self._quit_after_save:
                self._shutdown(destroy=True)
                return
        self._refresh_source_ui()

    def _check_hotkeys(self) -> None:
        try:
            if not any(self.hotkeys.registered.values()):
                self.toast.show("F9 / F10 热键被其他程序占用，可用界面按钮操作")
        except Exception:
            pass

    def _on_hotkey(self, hid: int) -> None:
        self.hotkey_queue.put(hid)

    def _poll(self) -> None:
        if getattr(self, "_closing", False):
            return
        try:
            while True:
                self._handle_event(self.events.get_nowait())
        except queue.Empty:
            pass
        try:
            while True:
                hid = self.hotkey_queue.get_nowait()
                if self._modal:
                    continue
                if hid == hotkeys.HOTKEY_TOGGLE:
                    self._toggle_record()
                elif hid == hotkeys.HOTKEY_PAUSE:
                    self._toggle_pause()
        except queue.Empty:
            pass

        if self.ui_state in ("recording", "paused"):
            elapsed = self.engine.elapsed()
            self.floating.update(elapsed, self.engine.file_size())
            h, rem = divmod(int(elapsed), 3600)
            m, sec = divmod(rem, 60)
            text = f"{h:d}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"
            if self.ui_state == "paused":
                self._set_rec_badge(True, True, "已暂停")
            else:
                self._set_rec_badge(True, False, f"REC  {text}")
        if not self._closing:
            self._poll_job = self.root.after(100, self._poll)

    # ------------------------------------------------------------ misc
    def _detect_encoder(self) -> None:
        try:
            enc = ffmpeg.detect_encoder(True)
            self.events.put({"type": "encoder", "encoder": enc})
        except Exception:
            pass

    def _elide(self, text: str, max_px: int, size: float) -> str:
        try:
            font = tkfont.Font(font=ui_font(size))
            if font.measure(text) <= max_px:
                return text
            while text and font.measure(text + "…") > max_px:
                text = text[:-1]
            return text + "…"
        except Exception:
            return text

    def _on_close(self) -> None:
        if self.ui_state == "countdown":
            self._cancel_countdown()
            self._shutdown(destroy=True)
            return
        if self.ui_state in ("recording", "paused"):
            if not messagebox.askyesno("正在录制", "正在录制，退出将停止并保存这段视频。继续吗？",
                                       parent=self.root):
                return
            self._quit_after_save = True
            self.stop_recording()
            return
        if self.ui_state == "saving":
            self.toast.show("正在保存，请稍候…")
            return
        self._shutdown(destroy=True)

    def _shutdown(self, destroy: bool = False) -> None:
        self._closing = True
        for job in (self._poll_job, self._preview_job, self._countdown_job,
                    *self._startup_jobs):
            if job:
                try:
                    self.root.after_cancel(job)
                except Exception:
                    pass
        self._poll_job = self._preview_job = self._countdown_job = None
        self._startup_jobs = []
        try:
            self.cfg.save()
        except Exception:
            pass
        try:
            self.previewer.stop()
        except Exception:
            pass
        try:
            self.hotkeys.stop()
        except Exception:
            pass
        if destroy:
            try:
                self.root.destroy()
            except Exception:
                pass
