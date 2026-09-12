"""Optional source-only playback check using Windows Media Foundation via Qt.

QtMultimedia is used by this developer check only, not shipped with the app.
"""

import os
import sys
import tempfile
import threading
import time
from pathlib import Path

if sys.platform != "win32":
    raise SystemExit("This check uses the Windows media backend")
os.environ["QT_MEDIA_BACKEND"] = "windows"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtMultimedia import QMediaPlayer, QVideoSink
from PyQt6.QtWidgets import QApplication

from eps_renderer import EpsRenderer
from video_creator import VideoExporter, VideoExportRequest


app = QApplication([])
renderer = EpsRenderer()
try:
    with tempfile.TemporaryDirectory(prefix="eps_windows_playback_") as folder:
        root = Path(folder)
        paths = []
        for index in range(12):
            image = QImage(321, 241, QImage.Format.Format_RGB32)
            image.fill(QColor.fromHsv(index * 30, 220, 220))
            path = root / f"{index:02}.png"
            assert image.save(str(path))
            paths.append(path)
        target = root / "playback.mp4"
        VideoExporter(renderer).create(VideoExportRequest(
            tuple(paths), target, "mp4", 321, 241, 7
        ), threading.Event())
        player = QMediaPlayer()
        sink = QVideoSink()
        player.setVideoSink(sink)
        frames = []
        sink.videoFrameChanged.connect(
            lambda frame: frames.append(frame.startTime()) if frame.isValid() else None
        )
        try:
            player.setSource(QUrl.fromLocalFile(str(target)))
            player.play()
            deadline = time.monotonic() + 15
            while player.mediaStatus() != QMediaPlayer.MediaStatus.EndOfMedia:
                app.processEvents()
                assert player.error() == QMediaPlayer.Error.NoError, player.errorString()
                assert time.monotonic() < deadline, (player.mediaStatus(), len(frames))
                time.sleep(0.005)
            assert len(set(frames)) >= 11, frames
            assert 1600 <= player.duration() <= 1800, player.duration()
            assert sorted(frames) == frames, frames
            print(f"PASS: Windows Media Foundation played {len(frames)} frames; duration={player.duration()} ms")
        finally:
            player.stop()
            player.setSource(QUrl())
            app.processEvents()
finally:
    renderer.cache.cleanup()
