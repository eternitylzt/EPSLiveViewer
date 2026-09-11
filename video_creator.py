"""Build MP4 or GIF sequences from vector and raster plot files."""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage, QImageReader, QPainter

from config import VIDEO_SOURCE_SUFFIXES
from eps_renderer import EpsRenderCancelledError, EpsRenderer
from i18n import tr


MAX_VIDEO_PIXELS = 33_177_600  # 7680 x 4320 (8K UHD)
ProgressCallback = Callable[[int, int, str], None]


class VideoExportError(RuntimeError):
    """Raised when a frame cannot be prepared or FFmpeg cannot encode it."""


class VideoExportCancelled(VideoExportError):
    """Raised after the user cancels video creation."""


@dataclass(frozen=True)
class VideoExportRequest:
    """Immutable options for one animation/video job."""

    sources: tuple[Path, ...]
    target: Path
    output_format: str
    width: int
    height: int
    fps: int
    background_color: str = "#FFFFFF"
    crop_rect: tuple[float, float, float, float] | None = None


class VideoExporter:
    """Prepare equal-sized PNG frames, then encode them with bundled FFmpeg."""

    def __init__(self, renderer: EpsRenderer) -> None:
        self._renderer = renderer

    @staticmethod
    def _raise_if_cancelled(cancel_event: threading.Event) -> None:
        if cancel_event.is_set():
            raise VideoExportCancelled(tr("视频生成已取消。"))

    @staticmethod
    def _validate(request: VideoExportRequest) -> VideoExportRequest:
        output_format = request.output_format.strip().lower()
        if output_format not in {"mp4", "gif"}:
            raise VideoExportError(tr("输出格式必须是 MP4 或 GIF。"))
        if not request.sources:
            raise VideoExportError(tr("参与视频的文件列表不能为空。"))
        if request.width < 2 or request.height < 2:
            raise VideoExportError(tr("视频宽度和高度不能小于 2 像素。"))
        if request.width * request.height > MAX_VIDEO_PIXELS:
            raise VideoExportError(tr("视频分辨率超过 8K UHD，可能耗尽内存。"))
        if not 1 <= request.fps <= 60:
            raise VideoExportError(tr("帧率必须在 1 到 60 FPS 之间。"))
        if not QColor(request.background_color).isValid():
            raise VideoExportError(tr("视频背景颜色无效。"))

        crop_rect = request.crop_rect
        if crop_rect is not None:
            if len(crop_rect) != 4:
                raise VideoExportError(tr("裁剪区域参数无效。"))
            x, y, width, height = (float(value) for value in crop_rect)
            if (
                x < 0
                or y < 0
                or width <= 0
                or height <= 0
                or x + width > 1.000001
                or y + height > 1.000001
            ):
                raise VideoExportError(tr("裁剪区域必须位于图像范围内。"))
            crop_rect = (
                max(0.0, min(1.0, x)),
                max(0.0, min(1.0, y)),
                max(0.0, min(1.0 - x, width)),
                max(0.0, min(1.0 - y, height)),
            )

        sources = tuple(Path(item).resolve() for item in request.sources)
        for source in sources:
            if not source.is_file():
                raise VideoExportError(tr("找不到序列文件：{path}", path=source))
            if source.suffix.lower() not in VIDEO_SOURCE_SUFFIXES:
                raise VideoExportError(
                    tr("不支持的序列文件格式：{name}", name=source.name)
                )

        target = Path(request.target).expanduser()
        if target.name in {"", ".", ".."}:
            raise VideoExportError(tr("输出文件名无效。"))
        target = target.with_suffix(f".{output_format}").resolve()
        return VideoExportRequest(
            sources,
            target,
            output_format,
            request.width,
            request.height,
            request.fps,
            request.background_color,
            crop_rect,
        )

    @staticmethod
    def _read_raster(source: Path) -> QImage:
        reader = QImageReader(str(source))
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            detail = reader.errorString().strip()
            suffix = f"：{detail}" if detail else ""
            raise VideoExportError(
                tr("无法读取图片 {name}{suffix}", name=source.name, suffix=suffix)
            )
        return image

    def _read_source(
        self,
        source: Path,
        request: VideoExportRequest,
        cancel_event: threading.Event,
    ) -> QImage:
        if source.suffix.lower() not in {".eps", ".ps"}:
            return self._read_raster(source)

        # Vector sources are rasterized only for the requested video canvas.
        # 300 DPI covers most HD frames; larger canvases use up to 600 DPI.
        longest_edge = max(request.width, request.height)
        dpi = max(150, min(600, round(300 * longest_edge / 1920)))
        rendered = self._renderer.render(
            source,
            dpi=dpi,
            cancel_event=cancel_event,
            guard_dimensions=True,
        )
        try:
            return self._read_raster(rendered.png_path)
        finally:
            self._renderer.cache.release(rendered.png_path)

    @staticmethod
    def _crop_image(image: QImage, request: VideoExportRequest) -> QImage:
        if request.crop_rect is None:
            return image
        x, y, width, height = request.crop_rect
        left = max(0, min(image.width() - 1, int(x * image.width())))
        top = max(0, min(image.height() - 1, int(y * image.height())))
        right = max(
            left + 1,
            min(image.width(), math.ceil((x + width) * image.width())),
        )
        bottom = max(
            top + 1,
            min(image.height(), math.ceil((y + height) * image.height())),
        )
        return image.copy(left, top, right - left, bottom - top)

    @staticmethod
    def _fit_to_canvas(image: QImage, request: VideoExportRequest) -> QImage:
        canvas = QImage(
            request.width,
            request.height,
            QImage.Format.Format_RGB32,
        )
        canvas.fill(QColor(request.background_color))
        scaled = image.scaled(
            request.width,
            request.height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = (request.width - scaled.width()) // 2
        y = (request.height - scaled.height()) // 2
        painter = QPainter(canvas)
        painter.drawImage(x, y, scaled)
        painter.end()
        return canvas

    @staticmethod
    def _ffmpeg_executable() -> Path:
        try:
            import imageio_ffmpeg

            executable = Path(imageio_ffmpeg.get_ffmpeg_exe())
        except Exception as error:
            raise VideoExportError(tr("无法加载视频编码器：{error}", error=error)) from error
        if not executable.is_file():
            raise VideoExportError(tr("未找到随程序提供的视频编码器。"))
        return executable

    @staticmethod
    def _stop_process(process: subprocess.Popen[str]) -> None:
        try:
            process.terminate()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def _run_ffmpeg(
        self,
        command: list[str],
        cancel_event: threading.Event,
    ) -> None:
        process: subprocess.Popen[str] | None = None
        stdout = ""
        stderr = ""
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            while True:
                if cancel_event.is_set():
                    self._stop_process(process)
                    raise VideoExportCancelled(tr("视频生成已取消。"))
                try:
                    stdout, stderr = process.communicate(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    continue
        except VideoExportCancelled:
            raise
        except OSError as error:
            if process is not None and process.poll() is None:
                self._stop_process(process)
            raise VideoExportError(
                tr("无法启动视频编码器：{error}", error=error)
            ) from error
        if process.returncode != 0:
            detail = " ".join((stderr or stdout).split())[-1600:]
            suffix = f"\nFFmpeg: {detail}" if detail else ""
            raise VideoExportError(tr("视频编码失败。{suffix}", suffix=suffix))

    def create(
        self,
        request: VideoExportRequest,
        cancel_event: threading.Event,
        progress: ProgressCallback | None = None,
    ) -> Path:
        """Create one MP4/GIF atomically and return its final path."""
        request = self._validate(request)
        try:
            request.target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise VideoExportError(tr("无法创建输出目录：{error}", error=error)) from error
        if not request.target.parent.is_dir():
            raise VideoExportError(tr("视频输出目录无效。"))

        staging = Path(
            tempfile.mkdtemp(prefix=".eps_video_", dir=request.target.parent)
        )
        encoded = staging / f"encoded.{request.output_format}"
        total_steps = len(request.sources) + 1
        try:
            for index, source in enumerate(request.sources):
                self._raise_if_cancelled(cancel_event)
                if progress:
                    progress(index, total_steps, tr("正在准备：{name}", name=source.name))
                try:
                    image = self._read_source(source, request, cancel_event)
                    image = self._crop_image(image, request)
                    frame = self._fit_to_canvas(image, request)
                    frame_path = staging / f"frame_{index:06d}.png"
                    if not frame.save(str(frame_path), "PNG"):
                        raise VideoExportError(
                            tr("无法写入临时帧：{name}", name=source.name)
                        )
                except (VideoExportCancelled, EpsRenderCancelledError):
                    raise VideoExportCancelled(tr("视频生成已取消。"))
                except VideoExportError:
                    raise
                except Exception as error:
                    raise VideoExportError(
                        tr("处理 {name} 时失败：{error}", name=source.name, error=error)
                    ) from error

            self._raise_if_cancelled(cancel_event)
            if progress:
                progress(len(request.sources), total_steps, tr("正在编码视频…"))
            ffmpeg = self._ffmpeg_executable()
            command = [
                str(ffmpeg),
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-framerate",
                str(request.fps),
                "-i",
                str(staging / "frame_%06d.png"),
            ]
            if request.output_format == "mp4":
                command.extend(
                    [
                        "-c:v",
                        "libx264",
                        "-pix_fmt",
                        "yuv420p"
                        if request.width % 2 == 0 and request.height % 2 == 0
                        else "yuv444p",
                        "-crf",
                        "18",
                        "-movflags",
                        "+faststart",
                    ]
                )
            else:
                command.extend(
                    [
                        "-filter_complex",
                        "split[s0][s1];[s0]palettegen=max_colors=256[p];"
                        "[s1][p]paletteuse=dither=sierra2_4a",
                        "-loop",
                        "0",
                    ]
                )
            command.append(str(encoded))
            self._run_ffmpeg(command, cancel_event)
            if not encoded.is_file() or encoded.stat().st_size == 0:
                raise VideoExportError(tr("视频编码器没有生成有效文件。"))
            self._raise_if_cancelled(cancel_event)
            try:
                os.replace(encoded, request.target)
            except OSError as error:
                raise VideoExportError(
                    tr("无法保存视频文件：{error}", error=error)
                ) from error
            if progress:
                progress(total_steps, total_steps, tr("视频已生成"))
            return request.target
        finally:
            # This directory is created exclusively for this export operation.
            shutil.rmtree(staging, ignore_errors=True)
