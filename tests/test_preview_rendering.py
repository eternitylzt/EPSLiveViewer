"""Visible-region accuracy, repaint stability, and bounded preview memory."""
import tempfile
import time
import unittest
from pathlib import Path

from PIL import Image, ImageChops, ImageStat
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, FloatObject, NameObject
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from vector_preview import VectorGraphicsView

APP = QApplication.instance() or QApplication([])


def rgba(image):
    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return Image.frombytes("RGBA", (converted.width(), converted.height()),
                           converted.constBits().asstring(converted.sizeInBytes()))


class PreviewRenderingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.source = Path(self.temp.name) / "transparent-lines.pdf"
        writer = PdfWriter()
        page = writer.add_blank_page(width=600, height=500)
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/ExtGState"):
            DictionaryObject({NameObject("/alpha"): DictionaryObject({
                NameObject("/ca"): FloatObject(.4), NameObject("/CA"): FloatObject(.4)})})})
        stream = DecodedStreamObject()
        commands = ["/alpha gs 1 0 0 rg 0 0 600 500 re f", "0 0 1 RG 0.8 w"]
        commands.extend(f"{x} 0 m {x + 135} 500 l S" for x in range(-100, 600, 17))
        commands.extend(f"0 {y} m 600 {y + 47} l S" for y in range(0, 500, 31))
        stream.set_data("\n".join(commands).encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
        writer.write(self.source)
        writer.close()
        self.view = VectorGraphicsView()
        self.view.resize(520, 420)
        self.view.show()
        self.view.load_pdf(self.source, 1, reset_view=True)
        self.settle()

    def tearDown(self):
        self.view.close()
        APP.processEvents()
        self.temp.cleanup()

    def settle(self):
        self.view._refresh_visible_frame()
        deadline = time.monotonic() + 20
        while True:
            APP.processEvents()
            if (not self.view._in_flight and not self.view._queued and not self.view._color_jobs
                    and not self.view._detail_timer.isActive()):
                return
            if time.monotonic() > deadline:
                self.fail("Viewport did not finish rendering")
            time.sleep(.002)

    def test_region_matches_full_page_sampling_and_click_repaint(self):
        for rotation in (0, 90):
            self.view.set_visual_transforms(rotation)
            self.view.zoom_by(2.35 / self.view.transform().m11())
            self.view.centerOn(310, 257)
            self.settle()
            item = self.view._page_item
            request = item._frame_request
            reference = self.view._active_context.document.render(0, request.full_size).copy(request.clip)
            difference = ImageChops.difference(rgba(reference), rgba(item._frame.toImage()))
            # Qt uses slightly different float rounding for whole/partial page
            # draws. Large shifts and region seams are not acceptable.
            self.assertLess(max(ImageStat.Stat(difference).mean), .25)
            self.view.setFocus()
            APP.processEvents()
            before = self.view.viewport().grab().toImage()
            QTest.mouseClick(self.view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(140, 180))
            APP.processEvents()
            after = self.view.viewport().grab().toImage()
            self.assertEqual(before, after, "Click-only repaint changed document pixels")

    def test_zoom_keeps_complete_frame_and_cache_does_not_accumulate(self):
        item = self.view._page_item
        previous = item._frame.cacheKey()
        for _ in range(6):
            self.view.zoom_by(1.07)
            self.view._refresh_visible_frame()
            self.assertEqual(item._frame.cacheKey(), previous)
            self.assertLessEqual(len(self.view._queued), 1)
        self.settle()
        for _ in range(8):
            item = self.view._page_item
            previous = item._frame.cacheKey()
            self.view.zoom_by(1.22)
            self.view._refresh_visible_frame()
            self.assertEqual(item._frame.cacheKey(), previous)
            self.assertLessEqual(len(self.view._queued), 1)
            self.settle()
            self.assertLessEqual(item._cache_bytes,
                                 self.view.MAX_DETAIL_PIXELS * 4 + 4 * 960 * 960 + 100_000)
        self.view.hide()
        APP.processEvents()
        self.assertTrue(item._frame.isNull())
        self.assertLessEqual(item._cache_bytes, 4 * 960 * 960)
        self.view.show()
        self.settle()
        self.assertFalse(item._frame.isNull())
        self.assertEqual(self.view.page_count(), 1)


if __name__ == "__main__":
    unittest.main()
