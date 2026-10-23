"""Windows 底层工具：DPI、显示器、窗口枚举、窗口矩形、鼠标指针抓取。"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes as wt
from dataclasses import dataclass
from typing import Optional

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

# ---------------------------------------------------------------- 常量
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
DWMWA_CLOAKED = 14
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_CAPTION_COLOR = 35
DWMWA_BORDER_COLOR = 34
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79
CURSOR_SHOWING = 0x00000001
WDA_EXCLUDEFROMCAPTURE = 0x00000011


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class BITMAP(ctypes.Structure):
    _fields_ = [("bmType", ctypes.c_long), ("bmWidth", ctypes.c_long),
                ("bmHeight", ctypes.c_long), ("bmWidthBytes", ctypes.c_long),
                ("bmPlanes", wt.WORD), ("bmBitsPixel", wt.WORD),
                ("bmBits", ctypes.c_void_p)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wt.BOOL), ("xHotspot", wt.DWORD),
                ("yHotspot", wt.DWORD), ("hbmMask", wt.HBITMAP),
                ("hbmColor", wt.HBITMAP)]


class CURSORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("flags", wt.DWORD),
                ("hCursor", wt.HANDLE), ("ptScreenPos", wt.POINT)]


user32.GetCursorInfo.argtypes = [ctypes.POINTER(CURSORINFO)]
user32.GetCursorInfo.restype = wt.BOOL
user32.GetIconInfo.argtypes = [wt.HANDLE, ctypes.POINTER(ICONINFO)]
user32.GetIconInfo.restype = wt.BOOL
user32.GetDC.argtypes = [wt.HWND]
user32.GetDC.restype = wt.HDC
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
gdi32.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT,
                            ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), wt.UINT]
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.GetObjectW.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p]
gdi32.GetObjectW.restype = ctypes.c_int
gdi32.DeleteObject.argtypes = [wt.HANDLE]


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)

    def intersect(self, other: "Rect") -> "Rect":
        x1, y1 = max(self.x, other.x), max(self.y, other.y)
        x2, y2 = min(self.right, other.right), min(self.bottom, other.bottom)
        return Rect(x1, y1, max(0, x2 - x1), max(0, y2 - y1))

    def contains(self, x: int, y: int) -> bool:
        return self.x <= x < self.right and self.y <= y < self.bottom


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    app: str
    rect: Rect


def enable_dpi_awareness() -> None:
    """必须在创建任何窗口前调用，保证坐标 = 物理像素。"""
    try:
        ctx = ctypes.c_void_p(-4)  # PER_MONITOR_AWARE_V2
        if user32.SetProcessDpiAwarenessContext(ctx):
            return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def virtual_screen() -> Rect:
    return Rect(
        user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
    )


def primary_screen() -> Rect:
    return Rect(0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))


def get_window_rect(hwnd: int) -> Rect:
    r = RECT()
    try:
        if dwmapi.DwmGetWindowAttribute(wt.HWND(hwnd), DWMWA_EXTENDED_FRAME_BOUNDS,
                                        ctypes.byref(r), ctypes.sizeof(r)) == 0:
            if r.right > r.left and r.bottom > r.top:
                return Rect(r.left, r.top, r.right - r.left, r.bottom - r.top)
    except Exception:
        pass
    if user32.GetWindowRect(wt.HWND(hwnd), ctypes.byref(r)):
        return Rect(r.left, r.top, r.right - r.left, r.bottom - r.top)
    return Rect(0, 0, 0, 0)


def is_minimized(hwnd: int) -> bool:
    return bool(user32.IsIconic(wt.HWND(hwnd)))


_BLACKLIST_TITLES = {
    "Program Manager", "Windows Input Experience", "MSCTFIME UI",
    "Default IME", "PopupHost", "应用商店",
}


def _exe_name(pid: int) -> str:
    hproc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not hproc:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(512)
        size = wt.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
    finally:
        kernel32.CloseHandle(hproc)
    return ""


def list_windows(include_self: bool = False) -> list[WindowInfo]:
    """列出适合录制的顶层窗口（可见、有标题、非工具窗口、未隐藏）。"""
    result: list[WindowInfo] = []
    own_pid = os.getpid()
    WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def _cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()
        if not title or title in _BLACKLIST_TITLES:
            return True
        exstyle = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if exstyle & WS_EX_TOOLWINDOW and not (exstyle & WS_EX_APPWINDOW):
            return True
        cloaked = wt.DWORD(0)
        try:
            if dwmapi.DwmGetWindowAttribute(wt.HWND(hwnd), DWMWA_CLOAKED,
                                            ctypes.byref(cloaked), 4) == 0 and cloaked.value:
                return True
        except Exception:
            pass
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == own_pid and not include_self:
            return True
        r = get_window_rect(hwnd)
        if r.w < 160 or r.h < 120:
            return True
        if is_minimized(hwnd):
            return True
        result.append(WindowInfo(int(hwnd), title, _exe_name(pid.value), r))
        return True

    user32.EnumWindows(WNDENUMPROC(_cb), 0)
    result.sort(key=lambda w: (w.app.lower(), w.title.lower()))
    return result


def set_dark_titlebar(hwnd: int, color: int = 0x00120D0B) -> None:
    """让 Windows 原生标题栏跟随深色主题（Win10 2004+ / Win11）。"""
    try:
        value = ctypes.c_int(1)
        dwmapi.DwmSetWindowAttribute(wt.HWND(hwnd), DWMWA_USE_IMMERSIVE_DARK_MODE,
                                     ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass
    for attr, val in ((DWMWA_CAPTION_COLOR, color), (DWMWA_BORDER_COLOR, color),
                      (DWMWA_WINDOW_CORNER_PREFERENCE, 2)):
        try:
            v = ctypes.c_int(val)
            dwmapi.DwmSetWindowAttribute(wt.HWND(hwnd), attr, ctypes.byref(v), 4)
        except Exception:
            pass


def exclude_from_capture(hwnd: int) -> bool:
    """尽量让悬浮控制条不被录进画面（Win10 2004+）。"""
    try:
        return bool(user32.SetWindowDisplayAffinity(wt.HWND(hwnd), WDA_EXCLUDEFROMCAPTURE))
    except Exception:
        return False


# ---------------------------------------------------------------- 鼠标指针
class _CursorImage:
    __slots__ = ("data", "width", "height", "hotspot")

    def __init__(self, data, width: int, height: int, hotspot: tuple[int, int]):
        self.data = data          # numpy HxWx4 BGRA
        self.width = width
        self.height = height
        self.hotspot = hotspot


_cursor_cache: dict[int, Optional[_CursorImage]] = {}


def _dib_bits(hdc, hbm, width: int, height: int, bpp: int):
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -height  # top-down
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = bpp
    bmi.bmiHeader.biCompression = 0  # BI_RGB
    if bpp == 32:
        buf = ctypes.create_string_buffer(width * height * 4)
    else:
        stride = ((width + 31) // 32) * 4
        buf = ctypes.create_string_buffer(stride * height)
    if gdi32.GetDIBits(hdc, hbm, 0, height, buf, ctypes.byref(bmi), 0) == 0:
        return None
    return buf


def _render_cursor(hcursor: int) -> Optional[_CursorImage]:
    import numpy as np

    info = ICONINFO()
    if not user32.GetIconInfo(wt.HANDLE(hcursor), ctypes.byref(info)):
        return None
    try:
        hbm_color, hbm_mask = info.hbmColor, info.hbmMask
        bmp = BITMAP()
        if hbm_color:
            gdi32.GetObjectW(hbm_color, ctypes.sizeof(BITMAP), ctypes.byref(bmp))
            w, h = int(bmp.bmWidth), int(bmp.bmHeight)
        elif hbm_mask:
            gdi32.GetObjectW(hbm_mask, ctypes.sizeof(BITMAP), ctypes.byref(bmp))
            w, h = int(bmp.bmWidth), int(bmp.bmHeight) // 2
        else:
            return None
        if w <= 0 or h <= 0 or w > 256 or h > 256:
            return None

        hdc = user32.GetDC(0)
        if not hdc:
            return None
        try:
            color_buf = _dib_bits(hdc, hbm_color, w, h, 32) if hbm_color else None
            mask_buf = _dib_bits(hdc, hbm_mask, w, h, 1) if hbm_mask else None
        finally:
            user32.ReleaseDC(0, hdc)

        if color_buf is None:
            return None
        color = np.frombuffer(color_buf.raw, dtype=np.uint8).reshape(h, w, 4).copy()
        alpha = color[:, :, 3]
        if int(alpha.max()) == 0 and mask_buf is not None:
            stride = ((w + 31) // 32) * 4
            mask = np.frombuffer(mask_buf.raw, dtype=np.uint8).reshape(h, stride)
            bits = np.unpackbits(mask, axis=1)[:, :w]
            color[:, :, 3] = np.where(bits > 0, 0, 255).astype(np.uint8)
        return _CursorImage(color, w, h, (int(info.xHotspot), int(info.yHotspot)))
    finally:
        if info.hbmColor:
            gdi32.DeleteObject(info.hbmColor)
        if info.hbmMask:
            gdi32.DeleteObject(info.hbmMask)


def get_cursor() -> tuple[Optional[_CursorImage], tuple[int, int]]:
    ci = CURSORINFO()
    ci.cbSize = ctypes.sizeof(CURSORINFO)
    if not user32.GetCursorInfo(ctypes.byref(ci)) or not (ci.flags & CURSOR_SHOWING):
        return None, (0, 0)
    key = int(ci.hCursor or 0)
    if key not in _cursor_cache:
        if len(_cursor_cache) > 64:
            _cursor_cache.clear()
        _cursor_cache[key] = _render_cursor(key)
    return _cursor_cache[key], (ci.ptScreenPos.x, ci.ptScreenPos.y)


def composite_cursor(frame, cursor: Optional[_CursorImage], pos: tuple[int, int],
                     origin: tuple[int, int]) -> None:
    """把鼠标指针按 alpha 混合进 BGRA 帧（原地）。"""
    if cursor is None:
        return
    import numpy as np

    x = pos[0] - origin[0] - cursor.hotspot[0]
    y = pos[1] - origin[1] - cursor.hotspot[1]
    h, w = frame.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(w, x + cursor.width), min(h, y + cursor.height)
    if x1 <= x0 or y1 <= y0:
        return
    src = cursor.data[y0 - y:y1 - y, x0 - x:x1 - x]
    dst = frame[y0:y1, x0:x1]
    alpha = src[:, :, 3:4].astype(np.float32) / 255.0
    if alpha.max() <= 0:
        return
    dst[:, :, :3] = (src[:, :, :3].astype(np.float32) * alpha +
                     dst[:, :, :3].astype(np.float32) * (1.0 - alpha)).astype(np.uint8)
