"""Small cancellable Qt worker pool; callbacks always run on the UI thread."""

from __future__ import annotations

import threading
from collections.abc import Callable

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, Qt, pyqtSignal, pyqtSlot


class _Task(QRunnable):
    def __init__(self, owner, number, work, cancelled):
        super().__init__()
        self.owner, self.number = owner, number
        self.work, self.cancelled = work, cancelled

    def run(self):
        result = error = None
        try:
            if not self.cancelled.is_set():
                result = self.work(self.cancelled)
        except Exception as caught:
            error = caught
        self.owner.finished.emit(self.number, result, error)


class TaskRunner(QObject):
    """Keep at most one worker by default, with cooperative cancellation."""

    finished = pyqtSignal(int, object, object)

    def __init__(self, parent=None, threads=1):
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(threads)
        self._jobs = {}
        self._sequence = 0
        self._closed = False
        self.finished.connect(self._deliver, Qt.ConnectionType.QueuedConnection)

    @property
    def pending_count(self):
        return len(self._jobs)

    def submit(self, work: Callable, callback: Callable) -> int:
        if self._closed:
            raise RuntimeError("Worker has been closed")
        self._sequence += 1
        number = self._sequence
        cancelled = threading.Event()
        self._jobs[number] = (cancelled, callback)
        self._pool.start(_Task(self, number, work, cancelled))
        return number

    def cancel_all(self):
        for cancelled, _callback in self._jobs.values():
            cancelled.set()

    @pyqtSlot(int, object, object)
    def _deliver(self, number, result, error):
        job = self._jobs.pop(number, None)
        if job is not None and not self._closed:
            cancelled, callback = job
            callback(result, error, cancelled.is_set())

    def shutdown(self, timeout_ms=5000) -> bool:
        self.cancel_all()
        if not self._pool.waitForDone(timeout_ms):
            return False
        self._closed = True
        self._jobs.clear()
        return True
