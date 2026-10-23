"""全局热键：F9 开始/停止，F10 暂停/继续。"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable

user32 = ctypes.WinDLL("user32", use_last_error=True)

MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
VK_F9 = 0x78
VK_F10 = 0x79

HOTKEY_TOGGLE = 1
HOTKEY_PAUSE = 2


class HotkeyManager(threading.Thread):
    def __init__(self, on_hotkey: Callable[[int], None]):
        super().__init__(daemon=True, name="hotkeys")
        self.on_hotkey = on_hotkey
        self.registered: dict[int, bool] = {}
        self._ready = threading.Event()

    def run(self) -> None:
        for hid, vk in ((HOTKEY_TOGGLE, VK_F9), (HOTKEY_PAUSE, VK_F10)):
            self.registered[hid] = bool(user32.RegisterHotKey(None, hid, MOD_NOREPEAT, vk))
        self._ready.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY:
                try:
                    self.on_hotkey(int(msg.wParam))
                except Exception:
                    pass

    def wait_ready(self, timeout: float = 1.0) -> bool:
        return self._ready.wait(timeout)

    def stop(self) -> None:
        try:
            user32.PostThreadMessageW(self.ident, WM_QUIT, 0, 0)
        except Exception:
            pass
