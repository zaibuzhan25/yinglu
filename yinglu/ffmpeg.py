"""ffmpeg 定位、编码器探测、视频写入与音视频封装。"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Optional

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _popen_kwargs() -> dict:
    if os.name == "nt":
        return {"creationflags": CREATE_NO_WINDOW,
                "startupinfo": subprocess.STARTUPINFO()}
    return {}


def find_ffmpeg() -> str:
    env = os.environ.get("YINGLU_FFMPEG")
    if env and os.path.isfile(env):
        return env
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.isfile(exe):
            return exe
    except Exception:
        pass
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    local = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "bin", "ffmpeg.exe")
    if os.path.isfile(local):
        return local
    raise FileNotFoundError("找不到 ffmpeg，请运行 setup.bat 安装依赖，或设置 YINGLU_FFMPEG 环境变量")


FFMPEG = None


def ffmpeg_exe() -> str:
    global FFMPEG
    if FFMPEG is None:
        FFMPEG = find_ffmpeg()
    return FFMPEG


@dataclass(frozen=True)
class Encoder:
    name: str          # libx264 / h264_nvenc / h264_qsv / h264_amf
    label: str
    hardware: bool

    def video_args(self, crf: int) -> list[str]:
        if self.name == "h264_nvenc":
            return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr",
                    "-cq", str(crf), "-b:v", "0"]
        if self.name == "h264_qsv":
            return ["-c:v", "h264_qsv", "-preset", "veryfast",
                    "-global_quality", str(crf)]
        if self.name == "h264_amf":
            return ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp",
                    "-qp_i", str(crf), "-qp_p", str(crf), "-qp_b", str(crf)]
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
                "-profile:v", "high"]


X264 = Encoder("libx264", "H.264 (CPU)", False)
ENCODER_CANDIDATES = [
    Encoder("h264_nvenc", "NVIDIA NVENC", True),
    Encoder("h264_qsv", "Intel Quick Sync", True),
    Encoder("h264_amf", "AMD AMF", True),
    X264,
]

_encoder_cache: Optional[Encoder] = None
_encoder_lock = threading.Lock()


def _run(cmd: list[str], timeout: float = 20) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace", **_popen_kwargs())


def available_encoders() -> list[str]:
    try:
        out = _run([ffmpeg_exe(), "-hide_banner", "-encoders"], timeout=10).stdout
    except Exception:
        return []
    return [e.name for e in ENCODER_CANDIDATES if re.search(rf"\b{e.name}\b", out)]


def _try_encoder(enc: Encoder) -> Optional[float]:
    """真实编码 60 帧 720p，返回耗时（秒）；失败返回 None。"""
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
           "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-frames:v", "60",
           *enc.video_args(23), "-pix_fmt", "yuv420p", "-f", "null", "-"]
    started = time.perf_counter()
    try:
        if _run(cmd, timeout=25).returncode != 0:
            return None
        return time.perf_counter() - started
    except Exception:
        return None


def detect_encoder(prefer_hardware: bool = True) -> Encoder:
    """实测各编码器速度，只有明显快于 x264 才启用硬件编码。"""
    global _encoder_cache
    with _encoder_lock:
        if _encoder_cache is not None:
            return _encoder_cache
    if not prefer_hardware:
        _encoder_cache = X264
        return X264
    try:
        names = set(available_encoders())
    except Exception:
        names = set()
    base = _try_encoder(X264)
    best, best_time = X264, base if base is not None else 1.0
    for enc in ENCODER_CANDIDATES[:-1]:
        if enc.name not in names:
            continue
        elapsed = _try_encoder(enc)
        if elapsed is not None and elapsed < best_time * 0.7:
            best, best_time = enc, elapsed
    with _encoder_lock:
        _encoder_cache = best
    return best


QUALITY_CRF = {"standard": 25, "high": 21, "ultra": 17}


class VideoWriter:
    """把 BGRA 原始帧通过管道送给 ffmpeg 编码。"""

    def __init__(self, path: str, width: int, height: int, fps: int,
                 encoder: Encoder, quality: str = "high"):
        self.path = path
        self.width = width
        self.height = height
        self.fps = fps
        self.encoder = encoder
        self.crf = QUALITY_CRF.get(quality, 21)
        self._proc: Optional[subprocess.Popen] = None
        self._stderr: list[str] = []
        self._reader: Optional[threading.Thread] = None

    def start(self) -> None:
        cmd = [
            ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{self.width}x{self.height}",
            "-r", str(self.fps), "-i", "pipe:0",
            *self.encoder.video_args(self.crf),
            "-vf", "scale=out_range=tv:out_color_matrix=bt709",
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-pix_fmt", "yuv420p", "-g", str(self.fps * 2),
            "-movflags", "+faststart", self.path,
        ]
        self._proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, bufsize=0, **_popen_kwargs())

        def _drain():
            try:
                for line in iter(self._proc.stderr.readline, b""):
                    if len(self._stderr) < 200:
                        self._stderr.append(line.decode("utf-8", "replace").strip())
            except Exception:
                pass

        self._reader = threading.Thread(target=_drain, daemon=True)
        self._reader.start()

    def write(self, data: bytes) -> bool:
        if self._proc is None or self._proc.stdin is None:
            return False
        try:
            self._proc.stdin.write(data)
            return True
        except (BrokenPipeError, OSError):
            return False

    def close(self, timeout: float = 30) -> tuple[bool, str]:
        if self._proc is None:
            return False, "编码器未启动"
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
        except Exception:
            pass
        try:
            self._proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait(timeout=5)
            return False, "编码超时"
        ok = self._proc.returncode == 0 and os.path.isfile(self.path) and os.path.getsize(self.path) > 1024
        return ok, "\n".join(self._stderr[-6:])

    def abort(self) -> None:
        if self._proc is None:
            return
        try:
            self._proc.kill()
        except Exception:
            pass


def mux(video_path: str, audio_inputs: list[tuple[str, float]], out_path: str,
        pauses: list[tuple[float, float]] | None = None,
        audio_total: float = 0.0, video_total: float = 0.0,
        timeout: float = 600) -> tuple[bool, str]:
    """把视频与 1~2 条音频（带音量、可剪掉暂停区间）封装成 mp4。

    audio_total 是音频时间轴（含暂停）的墙钟时长；video_total 是成片时长。
    """
    if not audio_inputs:
        try:
            os.replace(video_path, out_path)
            return True, ""
        except Exception as exc:
            return False, str(exc)

    from .audio import build_audio_filter

    if video_total <= 0:
        video_total = probe_duration(video_path)
    if audio_total <= 0:
        audio_total = video_total
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-i", video_path]
    for path, _vol in audio_inputs:
        cmd += ["-i", path]

    parts: list[str] = []
    for i, (_path, vol) in enumerate(audio_inputs, start=1):
        parts.append(build_audio_filter(i, pauses or [], f"a{i}", audio_total))
        parts.append(f"[a{i}]volume={vol:.3f}[av{i}]")
    if len(audio_inputs) == 1:
        parts.append(f"[av1]apad=whole_dur={video_total + 0.5:.3f}[aout]")
    else:
        parts.append("[av1][av2]amix=inputs=2:duration=longest:"
                     "dropout_transition=0:normalize=0[am]")
        parts.append(f"[am]apad=whole_dur={video_total + 0.5:.3f}[aout]")

    cmd += ["-filter_complex", ";".join(parts), "-map", "0:v:0", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-shortest", "-movflags", "+faststart", out_path]
    try:
        proc = _run(cmd, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "音频合并超时"
    if proc.returncode == 0 and os.path.isfile(out_path):
        return True, ""
    return False, (proc.stderr or "")[-800:]


def probe_duration(path: str) -> float:
    """读取媒体文件时长（秒），失败返回 0。"""
    cmd = [ffmpeg_exe(), "-hide_banner", "-i", path]
    try:
        proc = _run(cmd, timeout=15)
    except Exception:
        return 0.0
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", proc.stderr or "")
    if not m:
        return 0.0
    h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return h * 3600 + mi * 60 + s
