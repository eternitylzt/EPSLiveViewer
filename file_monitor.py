"""Robust QFileSystemWatcher wrapper for live source refresh notifications."""

from __future__ import annotations

import hashlib
from pathlib import Path

from PyQt6.QtCore import QFileSystemWatcher, QObject, QTimer, pyqtSignal


class EpsFileMonitor(QObject):
    """Watch one source file and its parent directory, with polling fallback.

    File writers often update plots by deleting/replacing them. Watching the
    parent directory lets the viewer survive that pattern; light mtime polling
    covers filesystems where native change notifications arrive unreliably.
    """

    file_changed = pyqtSignal(str)

    def __init__(self, refresh_interval: int = 500, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._source: Path | None = None
        self._enabled = True
        self._last_signature: tuple[int, int, bytes] | None = None
        self._last_emitted_signature: tuple[int, int, bytes] | None = None
        self._native_activity_pending = False

        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_watcher_activity)
        self._watcher.directoryChanged.connect(self._on_watcher_activity)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._emit_change)

        self._poller = QTimer(self)
        self._poller.timeout.connect(self._poll)
        self.set_refresh_interval(refresh_interval)

    def set_refresh_interval(self, milliseconds: int) -> None:
        milliseconds = max(100, min(int(milliseconds), 10_000))
        self._refresh_interval = milliseconds
        self._poller.setInterval(milliseconds)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if enabled and self._source:
            self._poller.start()
        else:
            self._poller.stop()

    def set_file(self, filename: str | Path | None) -> None:
        self.clear()
        if filename is None:
            return
        self._source = Path(filename).resolve()
        self._last_signature = self._signature()
        self._last_emitted_signature = self._last_signature
        self._add_paths()
        if self._enabled:
            self._poller.start()

    def clear(self) -> None:
        paths = self._watcher.files() + self._watcher.directories()
        if paths:
            self._watcher.removePaths(paths)
        self._source = None
        self._last_signature = None
        self._last_emitted_signature = None
        self._native_activity_pending = False
        self._debounce.stop()
        self._poller.stop()

    def _add_paths(self) -> None:
        if self._source is None:
            return
        parent = str(self._source.parent)
        if parent not in self._watcher.directories() and self._source.parent.exists():
            self._watcher.addPath(parent)
        source_name = str(self._source)
        if self._source.is_file() and source_name not in self._watcher.files():
            self._watcher.addPath(source_name)

    def _signature(self) -> tuple[int, int, bytes] | None:
        if self._source is None:
            return None
        try:
            stat = self._source.stat()
            digest = hashlib.blake2b(digest_size=8)
            with self._source.open("rb") as file:
                digest.update(file.read(4096))
                if stat.st_size > 4096:
                    file.seek(max(0, stat.st_size - 4096))
                    digest.update(file.read(4096))
            return stat.st_mtime_ns, stat.st_size, digest.digest()
        except OSError:
            return None

    def _on_watcher_activity(self, changed_path: str) -> None:
        self._add_paths()  # QFileSystemWatcher drops a file after replacement.
        if self._source is None:
            return
        try:
            source_event = Path(changed_path).resolve() == self._source
        except OSError:
            source_event = False
        signature = self._signature()
        if source_event:
            # A direct file event is meaningful even if a filesystem exposes a
            # coarse timestamp.  Multiple native events are merged by debounce.
            self._native_activity_pending = True
            self._last_signature = signature
            self._schedule_change()
        elif signature != self._last_signature:
            # Parent-directory watches survive atomic file replacement, but an
            # unrelated plot or log written beside the source must not reload it.
            self._last_signature = signature
            self._schedule_change()

    def _poll(self) -> None:
        signature = self._signature()
        if signature != self._last_signature:
            self._last_signature = signature
            self._add_paths()
            self._schedule_change()

    def _schedule_change(self) -> None:
        if self._enabled and self._source is not None:
            self._debounce.start(self._refresh_interval)

    def _emit_change(self) -> None:
        if self._source is None:
            return
        signature = self._signature()
        self._last_signature = signature
        # A single replacement write can produce fileChanged, directoryChanged,
        # and polling notifications.  Render once per observed mtime/size state.
        native_activity = self._native_activity_pending
        self._native_activity_pending = False
        if signature is not None and (
            native_activity or signature != self._last_emitted_signature
        ):
            self._last_emitted_signature = signature
            self.file_changed.emit(str(self._source))
