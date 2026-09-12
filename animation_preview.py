"""Low-resolution sequence rehearsal using Qt timers, without a media framework."""

from collections import OrderedDict
from dataclasses import replace
from pathlib import Path
import tempfile
import time

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QSlider, QVBoxLayout,
)

from background_tasks import TaskRunner
from i18n import tr
from preview_widgets import ImagePreview
from video_creator import VideoFrameSource


class AnimationPreviewDialog(QDialog):
    progress = pyqtSignal(int, int)

    def __init__(self, request, exporter, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("视频试播"))
        self.resize(780, 580)
        self._request = exporter._validate(request)
        self._exporter = exporter
        self._runner = TaskRunner(self)
        self._temporary = tempfile.TemporaryDirectory(prefix="eps_trial_")
        self._paths = []
        self._cache = OrderedDict()
        self._finished = False
        self._anchor_index = 0
        self._anchor_time = 0.0
        root = QVBoxLayout(self)
        note = QLabel(tr("低分辨率试播，使用当前帧顺序、裁剪和图像调整；不会生成或覆盖输出视频。"))
        note.setWordWrap(True)
        root.addWidget(note)
        self._preview = ImagePreview()
        root.addWidget(self._preview, 1)
        self._position = QLabel(tr("正在准备预览…"))
        root.addWidget(self._position)
        self._progress = QProgressBar()
        self.progress.connect(self._on_progress)
        root.addWidget(self._progress)
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, len(request.sources) - 1)
        self._slider.setEnabled(False)
        self._slider.sliderPressed.connect(lambda: self._play.setChecked(False))
        self._slider.valueChanged.connect(self._seek)
        root.addWidget(self._slider)
        row = QHBoxLayout()
        self._play = QPushButton(tr("播放"))
        self._play.setCheckable(True)
        self._play.setEnabled(False)
        self._play.toggled.connect(self._play_changed)
        row.addWidget(self._play)
        self._loop = QCheckBox(tr("循环播放"))
        self._loop.setChecked(True)
        row.addWidget(self._loop)
        row.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(tr("关闭"))
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        root.addLayout(row)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(max(1, round(1000 / request.fps)))
        self._timer.timeout.connect(self._tick)
        QTimer.singleShot(0, self._start)

    def _start(self):
        if self._finished:
            return
        request, exporter = self._request, self._exporter
        directory = Path(self._temporary.name)
        ratio = min(1.0, 640 / request.width, 360 / request.height)
        canvas = replace(request, width=max(2, round(request.width * ratio)),
                         height=max(2, round(request.height * ratio)))

        def prepare(cancel):
            paths = []
            for index, frame in enumerate(request.sources):
                if cancel.is_set():
                    return []
                if not isinstance(frame, VideoFrameSource):
                    frame = VideoFrameSource(Path(frame))
                image = exporter.read_frame(frame, request.background_color, 72, cancel, 900)
                image = exporter._crop_image(image, request)
                image = exporter._fit_to_canvas(image, canvas, frame.transforms)
                path = directory / f"{index:07}.png"
                if not image.save(str(path), "PNG"):
                    raise RuntimeError(tr("无法写入临时帧：{name}", name=frame.display_name))
                paths.append(path)
                self.progress.emit(index + 1, len(request.sources))
            return paths
        self._runner.submit(prepare, self._ready)

    def _on_progress(self, current, total):
        self._progress.setRange(0, total)
        self._progress.setValue(current)
        self._position.setText(tr("正在准备试播 {current}/{total}", current=current, total=total))

    def _ready(self, paths, error, cancelled):
        if self._finished or cancelled:
            return
        self._progress.hide()
        if error is not None:
            self._position.setText(tr("预览失败：{error}", error=error))
            return
        self._paths = paths
        self._slider.setEnabled(bool(paths))
        self._play.setEnabled(bool(paths))
        self._display(0)
        self._play.setChecked(bool(paths))

    def _display(self, index):
        if not self._paths:
            return
        if index not in self._cache:
            self._cache[index] = QImage(str(self._paths[index]))
        self._cache.move_to_end(index)
        while len(self._cache) > 8:
            self._cache.popitem(last=False)
        self._preview.set_image(self._cache[index])
        self._position.setText(tr("第 {current}/{total} 帧 · {seconds:.2f} / {duration:.2f} 秒",
                                  current=index + 1, total=len(self._paths),
                                  seconds=index / self._request.fps,
                                  duration=len(self._paths) / self._request.fps))

    def _seek(self, index):
        self._anchor_index, self._anchor_time = index, time.monotonic()
        self._display(index)

    def _play_changed(self, playing):
        self._play.setText(tr("暂停") if playing else tr("播放"))
        if playing:
            self._anchor_index = self._slider.value()
            self._anchor_time = time.monotonic()
            self._timer.start()
        else:
            self._timer.stop()

    def _tick(self):
        if not self._paths:
            return
        index = self._anchor_index + int((time.monotonic() - self._anchor_time) * self._request.fps)
        if index >= len(self._paths) and not self._loop.isChecked():
            self._slider.setValue(len(self._paths) - 1)
            self._play.setChecked(False)
            return
        index %= len(self._paths)
        self._slider.blockSignals(True)
        self._slider.setValue(index)
        self._slider.blockSignals(False)
        self._display(index)

    def done(self, result):
        self._timer.stop()
        if not self._runner.shutdown():
            QTimer.singleShot(100, lambda: self.done(result))
            return
        self._finished = True
        self._cache.clear()
        self._temporary.cleanup()
        super().done(result)
