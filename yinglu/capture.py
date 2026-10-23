"""屏幕抓取：优先 DXGI 桌面复制（dxcam），失败自动退回 mss/GDI。

DXGI 摄像头必须在使用它的线程里创建（comtypes 初始化 COM），因此后端采用
惰性初始化：open() 只计算尺寸，真正的采集后端在采集线程的第一次 frame() 建立。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import mss
import numpy as np

from . import winutil
from .winutil import Rect


@dataclass
class CaptureSource:
    kind: str                      # screen | region | window
    rect: Optional[Rect] = None    # screen / region
    hwnd: int = 0                  # window
    label: str = ""

    def describe(self) -> str:
        if self.kind == "screen":
            r = self.rect or winutil.primary_screen()
            return f"全屏 · {r.w} × {r.h}"
        if self.kind == "region":
            r = self.rect or Rect(0, 0, 0, 0)
            return f"区域 · {r.w} × {r.h}"
        base = self.label or "窗口"
        if self.rect is not None:
            return f"{base} · {self.rect.w} × {self.rect.h}"
        return base


class Grabber:
    """在单个录制线程内使用；每次 frame() 返回固定尺寸的 BGRA 缓冲。"""

    def __init__(self, source: CaptureSource, draw_cursor: bool = True, fps: int = 30):
        self.source = source
        self.draw_cursor = draw_cursor
        self.fps = max(1, min(240, int(fps)))
        self.backend = "pending"
        self._ready = False
        self._sct: Optional[mss.MSS] = None
        self._camera = None
        self._crop: Optional[tuple[int, int, int, int]] = None
        self._rect = Rect(0, 0, 0, 0)
        self._canvas: Optional[np.ndarray] = None
        self.width = 0
        self.height = 0
        self.origin = (0, 0)

    # ------------------------------------------------------------ lifecycle
    def open(self) -> None:
        if self.source.kind == "window":
            self._rect = winutil.get_window_rect(self.source.hwnd)
            if self._rect.w < 8 or self._rect.h < 8:
                raise RuntimeError("窗口不可见或已被最小化")
        elif self.source.rect is not None:
            self._rect = self.source.rect
        else:
            self._rect = winutil.primary_screen()
        self._rect = self._rect.intersect(winutil.virtual_screen())
        self.width = max(2, self._rect.w - (self._rect.w % 2))
        self.height = max(2, self._rect.h - (self._rect.h % 2))
        self.origin = (self._rect.x, self._rect.y)
        if self.source.kind == "window":
            self._canvas = np.zeros((self.height, self.width, 4), dtype=np.uint8)
            self._canvas[:, :, 3] = 255

    def _init_backend(self) -> None:
        if self.source.kind == "window":
            self._sct = mss.MSS()
            self.backend = "gdi"
            self._ready = True
            return
        if self._open_dxgi():
            self._ready = True
            return
        self._sct = mss.MSS()
        self.backend = "gdi"
        self._ready = True

    def _open_dxgi(self) -> bool:
        """只在“整块区域落在主显示器内”时启用 DXGI；其余情况用 mss。"""
        primary = winutil.primary_screen()
        if not (self._rect.x >= primary.x and self._rect.y >= primary.y and
                self._rect.right <= primary.right and self._rect.bottom <= primary.bottom):
            return False
        dx = self._rect.x - primary.x
        dy = self._rect.y - primary.y
        camera = None
        try:
            import dxcam  # 在采集线程内初始化，避免与 soundcard 的 COM 线程模型冲突
            camera = dxcam.create(output_idx=0, output_color="BGRA")
            if camera is None:
                return False
            camera.start(target_fps=self.fps, video_mode=True)
            img = camera.get_latest_frame()
            if img is None:
                time.sleep(0.05)
                img = camera.get_latest_frame()
            if img is None:
                raise RuntimeError("DXGI 无首帧")
            if img.ndim != 3 or img.shape[2] != 4:
                raise RuntimeError("DXGI 帧格式异常")
            if img.shape[1] < dx + self.width or img.shape[0] < dy + self.height:
                raise RuntimeError("DXGI 帧尺寸不足")
        except Exception:
            try:
                if camera is not None:
                    camera.stop()
                    camera.release()
            except Exception:
                pass
            return False
        self._camera = camera
        self._crop = (dx, dy, self.width, self.height)
        self.backend = "dxgi"
        return True

    def close(self) -> None:
        if self._camera is not None:
            try:
                self._camera.stop()
            except Exception:
                pass
            try:
                self._camera.release()
            except Exception:
                pass
            self._camera = None
        if self._sct is not None:
            try:
                self._sct.close()
            except Exception:
                pass
            self._sct = None
        self._ready = False

    def pause(self) -> None:
        if self._camera is not None:
            try:
                self._camera.stop()
            except Exception:
                pass

    def resume(self) -> None:
        if self._camera is not None:
            try:
                self._camera.start(target_fps=self.fps, video_mode=True)
            except Exception:
                self._switch_to_mss()

    def _switch_to_mss(self) -> None:
        try:
            if self._camera is not None:
                self._camera.release()
        except Exception:
            pass
        self._camera = None
        try:
            self._sct = mss.MSS()
            self.backend = "gdi"
        except Exception:
            self._sct = None

    # ------------------------------------------------------------ capture
    def frame(self) -> Optional[bytes | bytearray | memoryview]:
        if not self._ready:
            self._init_backend()
        if self._camera is not None:
            try:
                return self._frame_dxgi()
            except Exception:
                self._switch_to_mss()
        if self.source.kind == "window":
            return self._frame_window()
        return self._frame_mss()

    def _frame_dxgi(self):
        assert self._camera is not None and self._crop is not None
        img = self._camera.get_latest_frame()
        if img is None:
            return None
        x, y, w, h = self._crop
        if x == 0 and y == 0 and img.shape[1] == w and img.shape[0] == h:
            out = img
            if self.draw_cursor:
                out = img.copy()
        else:
            if img.shape[1] < x + w or img.shape[0] < y + h:
                raise RuntimeError("DXGI 帧尺寸变化")
            out = np.ascontiguousarray(img[y:y + h, x:x + w])
        if self.draw_cursor:
            cur, pos = winutil.get_cursor()
            if cur is not None:
                winutil.composite_cursor(out, cur, pos, self.origin)
        return memoryview(out)

    def _frame_mss(self):
        if self._sct is None:
            return None
        rect = self._rect
        try:
            shot = self._sct.grab({"left": rect.x, "top": rect.y,
                                   "width": rect.w, "height": rect.h})
        except Exception:
            return None
        if shot.width == self.width and shot.height == self.height:
            if self.draw_cursor:
                arr = np.frombuffer(shot.raw, dtype=np.uint8).reshape(
                    shot.height, shot.width, 4)
                cur, pos = winutil.get_cursor()
                if cur is not None:
                    winutil.composite_cursor(arr, cur, pos, self.origin)
            return shot.raw
        return self._fit_to_canvas(shot, rect)

    def _fit_to_canvas(self, shot, rect: Rect):
        if self._canvas is None:
            self._canvas = np.zeros((self.height, self.width, 4), dtype=np.uint8)
            self._canvas[:, :, 3] = 255
        self._canvas[:, :, :3] = 0
        img = np.frombuffer(shot.raw, dtype=np.uint8).reshape(shot.height, shot.width, 4)
        h = min(self.height, img.shape[0])
        w = min(self.width, img.shape[1])
        self._canvas[:h, :w] = img[:h, :w]
        self._compose_cursor()
        return memoryview(self._canvas)

    def _frame_window(self):
        assert self._sct is not None and self._canvas is not None
        if winutil.is_minimized(self.source.hwnd):
            return None
        rect = winutil.get_window_rect(self.source.hwnd)
        if rect.w < 8 or rect.h < 8:
            return None
        visible = rect.intersect(winutil.virtual_screen())
        if visible.w < 2 or visible.h < 2:
            return None
        try:
            shot = self._sct.grab({"left": visible.x, "top": visible.y,
                                   "width": visible.w, "height": visible.h})
        except Exception:
            return None
        img = np.frombuffer(shot.raw, dtype=np.uint8).reshape(shot.height, shot.width, 4)
        self._canvas[:, :, :3] = 0
        dx = max(0, rect.x - self.origin[0])
        dy = max(0, rect.y - self.origin[1])
        sx = max(0, self.origin[0] - rect.x)
        sy = max(0, self.origin[1] - rect.y)
        h = min(img.shape[0] - sy, self.height - dy)
        w = min(img.shape[1] - sx, self.width - dx)
        if h <= 0 or w <= 0:
            return None
        self._canvas[dy:dy + h, dx:dx + w] = img[sy:sy + h, sx:sx + w]
        self._compose_cursor()
        return memoryview(self._canvas)

    def _compose_cursor(self) -> None:
        if not self.draw_cursor or self._canvas is None:
            return
        cur, pos = winutil.get_cursor()
        if cur is not None:
            winutil.composite_cursor(self._canvas, cur, pos, self.origin)
