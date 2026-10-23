"""单实例：避免两个进程同时抢热键、同时录屏。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

_handle = None
_ERROR_ALREADY_EXISTS = 183


def acquire(name: str = "YingluScreenRecorder") -> bool:
    """返回 True 表示当前进程是唯一实例；句柄由模块持有到进程结束。"""
    global _handle
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        return True
    _handle = handle
    return ctypes.get_last_error() != _ERROR_ALREADY_EXISTS
