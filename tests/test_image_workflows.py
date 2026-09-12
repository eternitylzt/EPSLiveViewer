"""Regression coverage for color dialogs, repeated crop previews, and MP4 playback."""

import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QApplication, QDialog

from color_dialog import ColorReplacementDialog
from eps_renderer import EpsRenderer
from i18n import set_language
from image_transforms import ColorReplacement, DocumentTransforms
from video_creator import VideoExporter, VideoExportRequest
from video_dialog import VideoCreationDialog


APP = QApplication.instance() or QApplication([])


def image_digest(image):
    bits = image.constBits()
    bits.setsize(image.sizeInBytes())
    return image.size(), hashlib.sha256(bytes(bits)).hexdigest()


class ImageWorkflowTests(unittest.TestCase):
    def test_replacement_dialog_add_edit_accept_reopen(self):
        for language in ("zh_CN", "en"):
            set_language(language)
            first = ColorReplacement("#000000", "#FFFFFF", 8)
            second = ColorReplacement("#888888", "#00FF00", 12)
            dialog = ColorReplacementDialog(())
            with patch.object(dialog, "_choose_replacement", return_value=first):
                dialog._add()
            self.assertEqual(dialog.replacements(), (first,))
            dialog._list.setCurrentRow(0)
            with patch.object(dialog, "_choose_replacement", return_value=second):
                dialog._edit_selected()
            dialog.accept()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            reopened = ColorReplacementDialog(dialog.replacements())
            self.assertEqual(reopened.replacements(), (second,))
            dialog.close()
            reopened.close()
        set_language("zh_CN")

    def test_repeated_rotated_crop_preview_and_export(self):
        renderer = EpsRenderer()
        if renderer.ghostscript_path is None:
            renderer.cache.cleanup()
            self.skipTest("Ghostscript is required")
        try:
            with tempfile.TemporaryDirectory(prefix="eps_repeat_test_") as folder:
                root = Path(folder)
                source = root / "01.eps"
                sample = Path(r"C:\Users\ztli\Desktop\20241001.eps")
                if sample.is_file():
                    shutil.copyfile(sample, source)
                else:
                    source.write_text(
                        "%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 200 100\n"
                        "%%Pages: 2\n%%EndComments\n"
                        "<< /PageSize [200 100] >> setpagedevice\n"
                        "%%Page: 1 1\n1 0 0 setrgbcolor 0 0 60 30 rectfill showpage\n"
                        "%%Page: 2 2\n0 0 1 setrgbcolor 20 20 40 50 rectfill showpage\n"
                        "%%EOF\n", encoding="ascii"
                    )
                original = source.read_bytes()
                state = DocumentTransforms()
                state.rotate_page(1, 90)
                snapshot = state.snapshot()
                reference = None
                for attempt in range(3):
                    dialog = VideoCreationDialog(root, renderer, {source: snapshot})
                    self.assertGreaterEqual(len(dialog.selected_frames()), 2)
                    for _ in range(2):
                        digest = image_digest(dialog._load_reference_preview())
                        if reference is None:
                            reference = digest
                        self.assertEqual(digest, reference)
                    exported_frame = VideoExporter(renderer).read_frame(
                        dialog.selected_frames()[0], "#FFFFFF", 150
                    )
                    self.assertEqual(image_digest(exported_frame), reference)
                    request = VideoExportRequest(
                        dialog.selected_frames(), root / "sequence.mp4", "mp4",
                        81, 65, 4,
                    )
                    VideoExporter(renderer).create(request, threading.Event())
                    self.assertEqual(state.snapshot(), snapshot)
                    self.assertEqual(source.read_bytes(), original)
                    dialog.close()
                    dialog.deleteLater()
                    APP.processEvents()
        finally:
            renderer.cache.cleanup()

    def test_mp4_format_timing_and_decoded_frame_order(self):
        renderer = EpsRenderer()
        exporter = VideoExporter(renderer)
        ffmpeg = str(exporter._ffmpeg_executable())
        try:
            with tempfile.TemporaryDirectory(prefix="eps_mp4_test_") as folder:
                root = Path(folder)
                colors = ("#DD2222", "#22DD22", "#2222DD", "#CCCC22") * 3
                paths = []
                for index, color in enumerate(colors):
                    image = QImage(81, 65, QImage.Format.Format_RGB32)
                    image.fill(QColor(color))
                    path = root / f"{index:02}.png"
                    self.assertTrue(image.save(str(path)))
                    paths.append(path)
                for width, height, fps in ((81, 65, 1), (81, 65, 7), (80, 64, 30), (81, 65, 60)):
                    with self.subTest(width=width, height=height, fps=fps):
                        target = root / f"test{fps}.mp4"
                        exporter.create(VideoExportRequest(
                            tuple(paths), target, "mp4", width, height, fps
                        ), threading.Event())
                        run_options = dict(capture_output=True, timeout=30,
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                        inspected = subprocess.run([
                            ffmpeg, "-hide_banner", "-i", str(target), "-vf", "showinfo",
                            "-fps_mode", "passthrough", "-f", "null", "-",
                        ], **run_options)
                        log = inspected.stderr.decode("utf-8", errors="replace")
                        self.assertEqual(inspected.returncode, 0, log)
                        self.assertIn("h264 (Main)", log)
                        self.assertIn("yuv420p", log)
                        encoded_width, encoded_height = width + width % 2, height + height % 2
                        self.assertIn(f"{encoded_width}x{encoded_height}", log)
                        times = [float(t) for t in re.findall(r"\bn:\s*\d+\s+pts:\s*\d+\s+pts_time:([\d.]+)", log)]
                        self.assertEqual(len(times), len(paths), log)
                        for index, timestamp in enumerate(times):
                            self.assertAlmostEqual(timestamp, index / fps, places=4)
                        decoded = subprocess.run([
                            ffmpeg, "-v", "error", "-i", str(target), "-pix_fmt", "rgb24",
                            "-fps_mode", "passthrough", "-f", "rawvideo", "-",
                        ], **run_options)
                        self.assertEqual(decoded.returncode, 0, decoded.stderr)
                        frame_bytes = encoded_width * encoded_height * 3
                        self.assertEqual(len(decoded.stdout), len(paths) * frame_bytes)
                        center = ((height // 2) * encoded_width + width // 2) * 3
                        for index, color in enumerate(colors):
                            offset = index * frame_bytes + center
                            actual = decoded.stdout[offset:offset + 3]
                            expected = QColor(color).getRgb()[:3]
                            self.assertTrue(all(abs(a - b) < 15 for a, b in zip(actual, expected)),
                                            (index, actual, expected))
        finally:
            renderer.cache.cleanup()


if __name__ == "__main__":
    unittest.main()
