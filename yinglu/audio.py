"""音频采集：系统声音（WASAPI loopback）与麦克风，统一写 48kHz WAV。"""
from __future__ import annotations

import ctypes
import threading
import wave
from dataclasses import dataclass
from typing import Optional

import numpy as np

try:
    import soundcard as sc
except Exception:  # pragma: no cover - 依赖缺失时降级为纯视频
    sc = None

SAMPLE_RATE = 48000
BLOCK = 2400  # 50ms

_VIRTUAL_HINTS = ("vb-audio", "cable", "virtual", "voicemeeter", "steam streaming",
                  "nvidia broadcast", "obs virtual")


def available() -> bool:
    return sc is not None


@dataclass(frozen=True)
class AudioDevice:
    id: str
    name: str
    kind: str          # system | mic
    is_default: bool = False

    @property
    def short_name(self) -> str:
        return self.name


def _is_virtual(name: str) -> bool:
    low = name.lower()
    return any(h in low for h in _VIRTUAL_HINTS)


def list_system_devices() -> list[AudioDevice]:
    if sc is None:
        return []
    result: list[AudioDevice] = []
    try:
        default = sc.default_speaker()
        default_name = default.name if default else ""
        for spk in sc.all_speakers():
            result.append(AudioDevice(id=str(spk.id), name=spk.name, kind="system",
                                      is_default=(spk.name == default_name)))
    except Exception:
        pass
    result.sort(key=lambda d: (not d.is_default, d.name.lower()))
    return result


def list_mic_devices() -> list[AudioDevice]:
    if sc is None:
        return []
    result: list[AudioDevice] = []
    try:
        default = sc.default_microphone()
        default_name = default.name if default else ""
        seen: set[str] = set()
        for mic in sc.all_microphones(include_loopback=False):
            if mic.name in seen or _is_virtual(mic.name):
                continue
            seen.add(mic.name)
            result.append(AudioDevice(id=str(mic.id), name=mic.name, kind="mic",
                                      is_default=(mic.name == default_name)))
    except Exception:
        pass
    if not result:
        try:
            for mic in sc.all_microphones(include_loopback=False):
                result.append(AudioDevice(id=str(mic.id), name=mic.name, kind="mic",
                                          is_default=True))
        except Exception:
            pass
    result.sort(key=lambda d: (not d.is_default, d.name.lower()))
    return result


def default_system_device() -> Optional[AudioDevice]:
    devices = list_system_devices()
    return devices[0] if devices else None


def default_mic_device() -> Optional[AudioDevice]:
    devices = list_mic_devices()
    return devices[0] if devices else None


def resolve_device(device: Optional[AudioDevice], kind: str):
    """按配置解析出 soundcard 设备；找不到则回退默认设备。"""
    if sc is None:
        return None
    if device is not None:
        try:
            if kind == "system":
                for spk in sc.all_speakers():
                    if str(spk.id) == device.id:
                        return sc.get_microphone(spk.id, include_loopback=True)
                for spk in sc.all_speakers():
                    if spk.name == device.name:
                        return sc.get_microphone(spk.id, include_loopback=True)
            else:
                for mic in sc.all_microphones(include_loopback=False):
                    if str(mic.id) == device.id:
                        return mic
                for mic in sc.all_microphones(include_loopback=False):
                    if mic.name == device.name:
                        return mic
        except Exception:
            pass
    try:
        if kind == "system":
            spk = sc.default_speaker()
            return sc.get_microphone(spk.id, include_loopback=True) if spk else None
        return sc.default_microphone()
    except Exception:
        return None


class AudioTrack(threading.Thread):
    """一路音频录制线程，写入单个 48kHz 16bit WAV。"""

    def __init__(self, device: Optional[AudioDevice], kind: str, path: str,
                 volume: float = 1.0, t0: float = 0.0):
        super().__init__(daemon=True, name=f"audio-{kind}")
        self.device = device
        self.kind = kind
        self.path = path
        self.volume = max(0.0, min(1.5, volume))
        self.t0 = t0
        self.error: Optional[str] = None
        self.ready = threading.Event()
        self._stop_evt = threading.Event()
        self._recorder = None
        self._wave: Optional[wave.Wave_write] = None
        self.channels = 2
        self.samplerate = SAMPLE_RATE
        self.frames = 0

    def stop(self) -> None:
        self._stop_evt.set()

    def _open(self):
        mic = resolve_device(self.device, self.kind)
        if mic is None:
            raise RuntimeError("找不到音频设备")
        last: Optional[Exception] = None
        for rate, ch in ((48000, 2), (48000, 1), (44100, 2), (44100, 1)):
            rec = None
            try:
                rec = mic.recorder(samplerate=rate, channels=ch,
                                   blocksize=int(rate * 0.05), exclusive_mode=False)
                rec.__enter__()
                self.channels = ch
                self.samplerate = rate
                return rec
            except Exception as exc:  # 设备可能不支持该采样率/声道数
                last = exc
                try:
                    if rec is not None:
                        rec.__exit__(None, None, None)
                except Exception:
                    pass
        raise RuntimeError(f"无法打开音频设备：{last}")

    def run(self) -> None:
        if sc is None:
            self.error = "音频组件未安装"
            self.ready.set()
            return
        try:
            ctypes.windll.ole32.CoInitializeEx(None, 0x2)
        except Exception:
            pass
        rec = None
        try:
            rec = self._open()
            self._recorder = rec
            wav = wave.open(self.path, "wb")
            wav.setnchannels(self.channels)
            wav.setsampwidth(2)
            wav.setframerate(self.samplerate)
            self._wave = wav
            self.ready.set()
            block = int(self.samplerate * 0.05)
            while not self._stop_evt.is_set():
                data = rec.record(numframes=block)
                if data is None:
                    continue
                arr = np.asarray(data, dtype=np.float32)
                if arr.ndim == 1:
                    arr = arr[:, None]
                if arr.shape[1] == 1 and self.channels == 2:
                    arr = np.repeat(arr, 2, axis=1)
                elif arr.shape[1] > 2:
                    arr = arr[:, :2]
                arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
                pcm = (np.clip(arr, -1.0, 1.0) * 32767.0).astype("<i2")
                wav.writeframes(pcm.tobytes())
                self.frames += pcm.shape[0]
        except Exception as exc:
            self.error = str(exc)
            self.ready.set()
        finally:
            try:
                if self._wave is not None:
                    self._wave.close()
            except Exception:
                pass
            try:
                if rec is not None:
                    rec.__exit__(None, None, None)
            except Exception:
                pass
            try:
                ctypes.windll.ole32.CoUninitialize()
            except Exception:
                pass


def build_audio_filter(index: int, pauses: list[tuple[float, float]],
                       out_label: str, total: float) -> str:
    """生成 atrim + concat 的滤镜链，把暂停区间从音频里剪掉。"""
    spans: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in pauses:
        if start > cursor + 0.01:
            spans.append((cursor, min(start, total)))
        cursor = max(cursor, end)
    if total > cursor + 0.01:
        spans.append((cursor, total))
    if not spans:
        spans = [(0.0, max(total, 0.1))]

    parts = []
    for i, (start, end) in enumerate(spans):
        parts.append(f"[{index}:a]atrim=start={start:.3f}:end={end:.3f},"
                     f"asetpts=PTS-STARTPTS[a{index}_{i}]")
    labels = "".join(f"[a{index}_{i}]" for i in range(len(spans)))
    if len(spans) > 1:
        parts.append(f"{labels}concat=n={len(spans)}:v=0:a=1[{out_label}]")
    else:
        parts.append(f"{labels}anull[{out_label}]")
    return ";".join(parts)
