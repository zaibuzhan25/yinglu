"""配置读写（便携式：config.json 放在程序目录）。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = APP_DIR / "config.json"


def _default_output_dir() -> str:
    videos = Path.home() / "Videos"
    target = videos / "映录"
    try:
        target.mkdir(parents=True, exist_ok=True)
        return str(target)
    except Exception:
        fallback = APP_DIR / "recordings"
        try:
            fallback.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return str(fallback)


DEFAULTS: dict = {
    "fps": 30,
    "quality": "high",
    "countdown": 0,
    "cursor": True,
    "system_audio": True,
    "mic": False,
    "system_volume": 1.0,
    "mic_volume": 0.8,
    "system_device": "",
    "mic_device": "",
    "output_dir": "",
    "source_kind": "screen",
    "region": None,
    "window_title": "",
    "window_hwnd": 0,
    "last_file": "",
    "last_duration": 0.0,
    "last_size": 0,
    "last_backend": "",
    "ui_scale": 1.0,
}


class Config:
    def __init__(self, path: Path = CONFIG_PATH):
        self.path = path
        self.data = dict(DEFAULTS)
        self.load()
        if not self.data.get("output_dir"):
            self.data["output_dir"] = _default_output_dir()

    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8-sig") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict):
                for key, value in raw.items():
                    if key in DEFAULTS:
                        self.data[key] = value
        except Exception:
            pass

    def save(self) -> None:
        try:
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def get(self, key: str, default=None):
        return self.data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value) -> None:
        self.data[key] = value
