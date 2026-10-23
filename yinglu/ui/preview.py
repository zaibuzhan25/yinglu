"""空闲时的实时预览线程：每 0.4 秒抓一张当前来源的画面。"""
from __future__ import annotations

import threading
import time
from typing import Optional

import mss
from PIL import Image

from .. import winutil
from ..capture import CaptureSource
from ..winutil import Rect


class Previewer(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="preview")
        self._lock = threading.Lock()
        self._source: Optional[CaptureSource] = None
        self._paused = False
        self._stop_evt = threading.Event()
        self._image: Optional[Image.Image] = None
        self._last_error = ""

    def set_source(self, source: Optional[CaptureSource]) -> None:
        with self._lock:
            self._source = source
            self._image = None

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    def latest(self) -> Optional[Image.Image]:
        with self._lock:
            return self._image

    def stop(self) -> None:
        self._stop_evt.set()

    def _bbox(self) -> Optional[Rect]:
        with self._lock:
            source = self._source
        if source is None:
            return None
        if source.kind == "screen":
            return winutil.primary_screen()
        if source.kind == "region":
            return source.rect
        if source.kind == "window":
            if not source.hwnd or winutil.is_minimized(source.hwnd):
                return None
            r = winutil.get_window_rect(source.hwnd)
            if r.w < 8 or r.h < 8:
                return None
            return r.intersect(winutil.virtual_screen())
        return None

    def run(self) -> None:
        try:
            with mss.MSS() as sct:
                while not self._stop_evt.is_set():
                    if self._paused:
                        time.sleep(0.15)
                        continue
                    rect = self._bbox()
                    if rect is None or rect.w < 8 or rect.h < 8:
                        time.sleep(0.35)
                        continue
                    try:
                        shot = sct.grab({"left": rect.x, "top": rect.y,
                                         "width": rect.w, "height": rect.h})
                        img = Image.frombuffer("RGBA", (shot.width, shot.height),
                                               shot.bgra, "raw", "BGRA", 0, 1)
                        img = img.convert("RGB")
                        with self._lock:
                            self._image = img
                    except Exception:
                        time.sleep(0.6)
                        continue
                    for _ in range(8):
                        if self._stop_evt.is_set():
                            return
                        time.sleep(0.05)
        except Exception:
            return
