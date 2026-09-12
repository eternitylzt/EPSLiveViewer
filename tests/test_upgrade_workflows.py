"""User-facing regression checks for the local 2.1 workflow improvements."""

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import QEvent, QSettings, QTimer
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QApplication, QDialogButtonBox

from animation_preview import AnimationPreviewDialog
from color_dialog import ColorReplacementDialog
from config import ConfigManager
from diagnostics import Diagnostics
from image_transforms import ColorReplacement, TransformHistory, TransformSnapshot
from video_creator import VideoExporter, VideoExportRequest
from video_dialog import VideoCreationDialog
from viewer import MainWindow


APP = QApplication.instance() or QApplication([])


def wait_for(predicate, seconds=20):
    deadline = time.monotonic() + seconds
    while not predicate():
        APP.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("UI work did not finish before deadline")
        time.sleep(0.005)
    APP.processEvents()


class UpgradeWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="eps_upgrade_test_")
        self.root = Path(self.folder.name).resolve()
        APP.setOrganizationName("EPSLiveViewerUpgradeTests")
        APP.setApplicationName("Upgrade")
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, self.folder.name)
        manager = ConfigManager()
        manager.base_dir, manager.path = self.root, self.root / "config.json"
        self.window = MainWindow(manager)
        self.window.show()
        self.first = self.make_image("01.png", "black")
        self.second = self.make_image("02.png", "blue")

    def tearDown(self):
        self.window._discard_on_close = True
        self.window.close()
        APP.processEvents()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.folder.cleanup()

    def make_image(self, name, color):
        image = QImage(480, 320, QImage.Format.Format_RGB32)
        image.fill(QColor(color))
        path = self.root / name
        self.assertTrue(image.save(str(path)))
        return path

    def open(self, source):
        self.window.open_eps(source)
        # Match the canonical path used by the viewer (macOS /var -> /private/var,
        # and Windows temporary-directory aliases).
        wait_for(lambda: self.window._current_file == source.resolve() and self.window._page_count == 1
                 and self.window._current_pdf is not None
                 and self.window._view.has_document())

    def test_undo_redo_is_per_file_and_preserves_live_refresh(self):
        self.open(self.first)
        self.window._invert_colors_action.setChecked(True)
        self.window._rotate_right_action.trigger()
        self.window._undo_action.trigger()
        state = self.window._current_transforms()
        self.assertEqual(state.rotation_for(1), 0)
        self.assertTrue(state.inverted)
        self.window._redo_action.trigger()
        self.assertEqual(state.rotation_for(1), 90)
        self.open(self.second)
        self.assertFalse(self.window._undo_action.isEnabled())
        self.open(self.first)
        self.assertTrue(self.window._undo_action.isEnabled())
        self.assertEqual(self.window._current_transforms().rotation_for(1), 90)
        old_pdf = self.window._current_pdf
        self.make_image(self.first.name, "red")
        wait_for(lambda: self.window._current_pdf != old_pdf)
        self.window._undo_action.trigger()
        self.assertTrue(self.window._redo_action.isEnabled())
        self.window._rotate_left_action.trigger()
        self.assertFalse(self.window._redo_action.isEnabled())
        self.assertEqual(self.window._current_transforms().rotation_for(1), 270)
        history = TransformHistory()
        for index in range(80):
            history.record(TransformSnapshot(False, (), ((1, index),)),
                           TransformSnapshot(False, (), ((1, index + 1),)))
        self.assertEqual(len(history.undo_states), history.LIMIT)

    def test_color_preview_latest_edit_original_and_cancel(self):
        image = QImage(700, 460, QImage.Format.Format_RGBA8888)
        image.fill(QColor(0, 0, 0, 128))
        dialog = ColorReplacementDialog((), self.window,
                                        preview_loader=lambda _cancel: image,
                                        inverted=True, rotation=90)
        dialog.show()
        ticks = []
        timer = QTimer()
        timer.setInterval(5)
        timer.timeout.connect(lambda: ticks.append(time.monotonic()))
        timer.start()
        try:
            dialog._add()
            dialog._source_edit.setText("#FFFFFF")
            for color in ("#FF0000", "#00FF00", "#0000FF"):
                dialog._target_edit.setText(color)
                APP.processEvents()
            wait_for(lambda: not dialog._adjusted.isNull()
                     and dialog._adjusted.pixelColor(0, 0).blue() == 255)
            self.assertGreater(len(ticks), 3)
            self.assertEqual(dialog._adjusted.size(), image.size().transposed())
            self.assertEqual(dialog._adjusted.pixelColor(0, 0).alpha(), 128)
            dialog._original_button.setDown(True)
            dialog._original_button.pressed.emit()
            self.assertEqual(dialog._image_preview._image.pixelColor(0, 0).red(), 0)
            self.assertEqual(dialog._image_preview._image.pixelColor(0, 0).blue(), 0)
            dialog._original_button.setDown(False)
            dialog._original_button.released.emit()
            self.assertEqual(dialog._image_preview._image.pixelColor(0, 0).blue(), 255)
            dialog._target_edit.setText("invalid-color")
            self.assertFalse(dialog._buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled())
            dialog.reject()
            self.assertFalse(self.window._current_transforms().replacements)
            self.assertEqual(dialog._runner._pool.activeThreadCount(), 0)
        finally:
            timer.stop()
            dialog.close()
            dialog.deleteLater()

    def test_background_tiles_discard_old_color_jobs(self):
        self.open(self.first)
        state = self.window._current_transforms()
        for target in ("#FF0000", "#00FF00", "#0000FF"):
            state.replacements = (ColorReplacement("#000000", target),)
            self.window._apply_current_transforms()
            APP.processEvents()
        view = self.window._view
        wait_for(lambda: not view._color_jobs and view._in_flight == 0
                 and not view._page_item._overview.isNull())
        pixel = view._page_item._overview.toImage().pixelColor(30, 30)
        self.assertGreater(pixel.blue(), 240)
        self.assertLess(pixel.red(), 15)
        state.replacements = (ColorReplacement("#000000", "#00FF00"),)
        self.window._apply_current_transforms()
        self.open(self.second)
        wait_for(lambda: not view._color_jobs and view._in_flight == 0
                 and not view._page_item._overview.isNull())
        pixel = view._page_item._overview.toImage().pixelColor(30, 30)
        self.assertGreater(pixel.blue(), 240)
        self.assertLess(pixel.green(), 15)

    def test_trial_playback_order_seek_cleanup_and_duration(self):
        third = self.make_image("03.png", "green")
        target = self.root / "existing.mp4"
        target.write_bytes(b"existing output")
        request = VideoExportRequest((self.first, self.second, third) * 4,
                                     target, "mp4", 81, 65, 4,
                                     crop_rect=(0.1, 0.2, 0.5, 0.5))
        dialog = AnimationPreviewDialog(request, VideoExporter(self.window._renderer), self.window)
        directory = Path(dialog._temporary.name)
        dialog.show()
        try:
            wait_for(lambda: len(dialog._paths) == 12)
            dialog._play.setChecked(False)
            for index in range(12):
                dialog._slider.setValue(index)
            self.assertLessEqual(len(dialog._cache), 8)
            dialog._slider.setValue(1)
            self.assertGreater(dialog._preview._image.pixelColor(40, 32).blue(), 240)
            dialog._loop.setChecked(False)
            dialog._play.setChecked(True)
            dialog._anchor_time -= 10
            dialog._tick()
            self.assertFalse(dialog._play.isChecked())
            self.assertEqual(dialog._slider.value(), 11)
            self.assertEqual(target.read_bytes(), b"existing output")
        finally:
            dialog.close()
            dialog.deleteLater()
        self.assertFalse(directory.exists())
        sequence = VideoCreationDialog(self.root, self.window._renderer, parent=self.window)
        sequence._fps_spin.setValue(5)
        self.assertIn("0.60", sequence._duration_label.text())
        sequence._included.setCurrentRow(0)
        sequence._move_selected(sequence._included, sequence._excluded)
        self.assertIn("0.40", sequence._duration_label.text())
        sequence.close()
        sequence.deleteLater()

    def test_comparison_link_lock_follow_and_close(self):
        self.open(self.first)
        self.window._show_comparison()
        dialog = self.window._comparison
        wait_for(lambda: dialog.left.view.has_document() and dialog.right.view.has_document())
        reference_pdf = dialog.left.view._active_context.path
        before = reference_pdf.read_bytes()
        dialog.right.view.zoom_by(2)
        self.assertAlmostEqual(dialog.left.view.transform().m11(), dialog.right.view.transform().m11())
        dialog._linked.setChecked(False)
        zoom = dialog.left.view.transform().m11()
        dialog.right.view.zoom_by(2)
        self.assertEqual(zoom, dialog.left.view.transform().m11())
        self.window._rotate_right_action.trigger()
        self.assertEqual(dialog.right.transforms.rotation_for(1), 90)
        self.assertEqual(dialog.left.transforms.rotation_for(1), 0)
        self.open(self.second)
        wait_for(lambda: dialog.right.source == self.second and not dialog.right._runner.pending_count)
        self.assertEqual(dialog.left.source, self.first)
        self.assertEqual(reference_pdf.read_bytes(), before)
        cache = dialog._renderer.cache.directory
        dialog.reject()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertIsNone(self.window._comparison)
        self.assertFalse(cache.exists())
        self.window._show_comparison()
        self.window._comparison.close()

    def test_diagnostics_are_manual_bounded_and_include_error_context(self):
        diagnostics = Diagnostics()
        try:
            raise ValueError("test color failure")
        except ValueError as error:
            diagnostics.record("Color", error, {"page": 2, "rotation": 90})
        with patch("subprocess.run", side_effect=AssertionError("Unexpected process")):
            report = json.loads(diagnostics.report({"file": str(self.first)}))
        self.assertIn("ValueError: test color failure", report["recent_events"][0]["detail"])
        self.assertEqual(report["recent_events"][0]["context"]["rotation"], 90)
        self.assertIn("Qt", report)
        for index in range(30):
            diagnostics.record("Example", str(index))
        self.assertEqual(len(json.loads(diagnostics.report({}))["recent_events"]), 20)


if __name__ == "__main__":
    unittest.main()
