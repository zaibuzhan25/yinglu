"""录制引擎：抓屏 + 编码 + 音频 + 暂停/停止 + 封装。"""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import ctypes

import numpy as np

from . import audio as audio_mod
from . import ffmpeg as ff
from .capture import CaptureSource, Grabber

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002


def keep_awake(enable: bool) -> None:
    """录制期间阻止系统休眠 / 关闭显示器。"""
    try:
        flags = _ES_CONTINUOUS
        if enable:
            flags |= _ES_SYSTEM_REQUIRED | _ES_DISPLAY_REQUIRED
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except Exception:
        pass


class State:
    IDLE = "idle"
    RECORDING = "recording"
    PAUSED = "paused"
    SAVING = "saving"


@dataclass
class VideoOptions:
    fps: int = 30
    quality: str = "high"
    encoder: ff.Encoder = ff.X264


@dataclass
class AudioOptions:
    system: bool = True
    mic: bool = False
    system_device: Optional[audio_mod.AudioDevice] = None
    mic_device: Optional[audio_mod.AudioDevice] = None
    system_volume: float = 1.0
    mic_volume: float = 1.0


@dataclass
class RecordOptions:
    source: CaptureSource
    video: VideoOptions
    audio: AudioOptions
    out_path: str
    draw_cursor: bool = True


class RecordingEngine:
    def __init__(self, emit: Callable[[dict], None]):
        self._emit = emit
        self.state = State.IDLE
        self.options: Optional[RecordOptions] = None
        self.error: Optional[str] = None
        self.output_path: Optional[str] = None
        self.width = 0
        self.height = 0
        self.frames_written = 0

        self._grabber: Optional[Grabber] = None
        self._writer: Optional[ff.VideoWriter] = None
        self._tracks: list[audio_mod.AudioTrack] = []
        self._thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()
        self._t0 = 0.0
        self._end_time = 0.0
        self._paused_at: Optional[float] = None
        self._pause_total = 0.0
        self._pauses: list[tuple[float, float]] = []
        self._preview_lock = threading.Lock()
        self._preview: Optional[tuple[bytes, tuple[int, int]]] = None
        self._tmpdir: Optional[str] = None
        self._video_tmp: Optional[str] = None
        self._last_frame = None
        self._finalizing = False
        self._backend_reported = False

    # ------------------------------------------------------------ helpers
    def _set_state(self, state: str, **extra) -> None:
        self.state = state
        self._emit({"type": "state", "state": state, **extra})

    def elapsed(self) -> float:
        if self._t0 <= 0:
            return 0.0
        now = time.perf_counter()
        paused = self._pause_total
        if self._paused_at is not None:
            paused += now - self._paused_at
        return max(0.0, now - self._t0 - paused)

    def get_preview(self) -> Optional[tuple[bytes, tuple[int, int]]]:
        with self._preview_lock:
            return self._preview

    def file_size(self) -> int:
        total = 0
        for path in [self._video_tmp] + [t.path for t in self._tracks]:
            try:
                if path and os.path.isfile(path):
                    total += os.path.getsize(path)
            except OSError:
                pass
        return total

    # ------------------------------------------------------------ start
    def start(self, options: RecordOptions) -> tuple[bool, str]:
        if self.state != State.IDLE:
            return False, "正在录制中"
        self.options = options
        self.error = None
        self.output_path = None
        self._pauses.clear()
        self._pause_total = 0.0
        self._paused_at = None
        self._end_time = 0.0
        self.frames_written = 0
        self._preview = None
        self._last_frame = None
        self._finalizing = False
        self._backend_reported = False
        self._stop_flag.clear()

        out_dir = os.path.dirname(os.path.abspath(options.out_path)) or "."
        try:
            os.makedirs(out_dir, exist_ok=True)
            self._tmpdir = tempfile.mkdtemp(prefix=".yinglu_", dir=out_dir)
        except Exception as exc:
            return False, f"无法创建临时目录：{exc}"
        self._video_tmp = os.path.join(self._tmpdir, "video.mp4")

        grabber = Grabber(options.source, draw_cursor=options.draw_cursor,
                          fps=options.video.fps)
        try:
            grabber.open()
        except Exception as exc:
            self._cleanup_tmp()
            return False, f"抓屏失败：{exc}"
        if grabber.width < 16 or grabber.height < 16:
            grabber.close()
            self._cleanup_tmp()
            return False, "录制区域太小"
        self._grabber = grabber
        self.width, self.height = grabber.width, grabber.height

        writer = ff.VideoWriter(self._video_tmp, grabber.width, grabber.height,
                                options.video.fps, options.video.encoder,
                                options.video.quality)
        try:
            writer.start()
        except Exception as exc:
            grabber.close()
            self._cleanup_tmp()
            return False, f"编码器启动失败：{exc}"
        self._writer = writer

        self._t0 = time.perf_counter()
        self._start_audio(options, self._t0)
        self._thread = threading.Thread(target=self._capture_loop, daemon=True,
                                        name="capture")
        self._thread.start()
        keep_awake(True)
        self._set_state(State.RECORDING, width=grabber.width, height=grabber.height,
                        backend=grabber.backend)
        return True, ""

    def _start_audio(self, options: RecordOptions, t0: float) -> None:
        self._tracks = []
        if not audio_mod.available():
            if options.audio.system or options.audio.mic:
                self._emit({"type": "warning", "message": "音频组件不可用，将只录制画面"})
            return
        assert self._tmpdir
        if options.audio.system:
            path = os.path.join(self._tmpdir, "system.wav")
            track = audio_mod.AudioTrack(options.audio.system_device, "system", path,
                                         options.audio.system_volume, t0)
            track.start()
            self._tracks.append(track)
        if options.audio.mic:
            path = os.path.join(self._tmpdir, "mic.wav")
            track = audio_mod.AudioTrack(options.audio.mic_device, "mic", path,
                                         options.audio.mic_volume, t0)
            track.start()
            self._tracks.append(track)

    # ------------------------------------------------------------ capture loop
    def _capture_loop(self) -> None:
        fps = max(1, self.options.video.fps)
        writer = self._writer
        grabber = self._grabber
        assert writer is not None and grabber is not None
        written = 0
        last_preview = 0.0
        error: Optional[str] = None
        try:
            while not self._stop_flag.is_set():
                if self._paused_at is not None:
                    time.sleep(0.012)
                    continue
                elapsed = time.perf_counter() - self._t0 - self._pause_total
                target = int(elapsed * fps)
                if target < written:
                    # 抓得比目标帧率快，等下一帧到点
                    time.sleep(0.0015)
                    continue

                frame = grabber.frame()
                if frame is None:
                    frame = self._last_frame
                if frame is None:
                    time.sleep(0.008)
                    continue
                self._last_frame = frame

                gap = target - written
                if gap > fps * 5:
                    error = "画面捕获中断超过 5 秒，录制已停止"
                    break
                count = gap + 1
                data = frame
                failed = False
                for _ in range(count):
                    if not writer.write(data):
                        failed = True
                        break
                    written += 1
                if failed:
                    error = "视频编码中断（ffmpeg 退出）"
                    break
                self.frames_written = written
                if not self._backend_reported:
                    self._backend_reported = True
                    self._emit({"type": "backend", "backend": grabber.backend})

                now = time.perf_counter()
                if now - last_preview > 0.18:
                    last_preview = now
                    try:
                        from PIL import Image
                        raw = data
                        arr = np.frombuffer(raw, dtype=np.uint8)
                        need = grabber.width * grabber.height * 4
                        if arr.size >= need:
                            arr = arr[:need].reshape(grabber.height, grabber.width, 4)
                            img = Image.frombuffer("RGBA", (grabber.width, grabber.height),
                                                   arr.tobytes(), "raw", "BGRA", 0, 1)
                            img = img.convert("RGB")
                            img.thumbnail((480, 270), Image.Resampling.BILINEAR)
                            with self._preview_lock:
                                self._preview = (img.tobytes(), img.size)
                    except Exception:
                        pass
        except Exception as exc:  # 任何意外都要收尾，不能把界面卡在录制态
            error = f"录制异常：{exc}"
        self._finish_capture(error)

    # ------------------------------------------------------------ control
    def pause(self) -> bool:
        if self.state != State.RECORDING:
            return False
        self._paused_at = time.perf_counter()
        if self._grabber is not None:
            self._grabber.pause()
        self._set_state(State.PAUSED)
        return True

    def resume(self) -> bool:
        if self.state != State.PAUSED:
            return False
        now = time.perf_counter()
        if self._paused_at is not None:
            self._pauses.append((self._paused_at - self._t0, now - self._t0))
            self._pause_total += now - self._paused_at
            self._paused_at = None
        if self._grabber is not None:
            self._grabber.resume()
        self._set_state(State.RECORDING)
        return True

    def stop(self) -> None:
        if self.state not in (State.RECORDING, State.PAUSED):
            return
        if self._paused_at is not None:
            now = time.perf_counter()
            self._pauses.append((self._paused_at - self._t0, now - self._t0))
            self._pause_total += now - self._paused_at
            self._paused_at = None
        self._set_state(State.SAVING)
        self._end_time = time.perf_counter()
        self._stop_flag.set()

    # ------------------------------------------------------------ finalize
    def _finish_capture(self, error: Optional[str]) -> None:
        if self._finalizing:
            return
        self._finalizing = True
        keep_awake(False)
        writer = self._writer
        if writer is not None:
            ok, log = writer.close()
            if not ok and error is None:
                error = f"编码失败：{log or 'ffmpeg 异常退出'}"
        for track in self._tracks:
            track.stop()
        deadline = time.time() + 3
        for track in self._tracks:
            try:
                track.join(timeout=max(0.1, deadline - time.time()))
            except Exception:
                pass
        if self._grabber is not None:
            try:
                self._grabber.close()
            except Exception:
                pass

        if error:
            self.error = error
            self._cleanup_tmp()
            self._set_state(State.IDLE, error=error)
            self._reset()
            return

        end = self._end_time or time.perf_counter()
        wall_total = max(0.0, end - self._t0)
        duration = max(0.0, wall_total - self._pause_total)
        tracks = [(t.path, t.volume) for t in self._tracks
                  if t.frames > 0 and os.path.isfile(t.path)]
        for track in self._tracks:
            if track.error:
                label = "麦克风" if track.kind == "mic" else "系统声音"
                self._emit({"type": "warning",
                            "message": f"{label}不可用：{track.error}"})

        threading.Thread(target=self._finalize, args=(tracks, duration, wall_total),
                         daemon=True, name="mux").start()

    def _finalize(self, tracks: list[tuple[str, float]], duration: float,
                  wall_total: float) -> None:
        out_path = self.options.out_path
        try:
            ok, err = ff.mux(self._video_tmp, tracks, out_path, self._pauses,
                             audio_total=wall_total, video_total=duration)
        except Exception as exc:
            ok, err = False, f"合并失败：{exc}"
        if ok:
            self.output_path = out_path
            self._cleanup_tmp()
            self._set_state(State.IDLE, saved=out_path, duration=duration,
                            size=os.path.getsize(out_path))
        else:
            self.error = err or "合并音视频失败"
            self._cleanup_tmp()
            self._set_state(State.IDLE, error=self.error)
        self._reset()

    def _cleanup_tmp(self) -> None:
        if self._tmpdir and os.path.isdir(self._tmpdir):
            shutil.rmtree(self._tmpdir, ignore_errors=True)
        self._tmpdir = None

    def _reset(self) -> None:
        if self._grabber is not None:
            try:
                self._grabber.close()
            except Exception:
                pass
        self._grabber = None
        self._writer = None
        self._thread = None
        self._tracks = []
        self._video_tmp = None
        self._last_frame = None
