"""High-DPI output, actual vector recoloring, and PDF input workflows."""

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch, PropertyMock

from PyQt6.QtCore import QEvent, QMarginsF, QPoint, QPointF, QRectF, QSizeF, Qt
from PyQt6.QtGui import QColor, QImage, QImageReader, QMouseEvent, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from pypdf import PdfReader

from eps_renderer import EpsRenderer
from image_transforms import ColorReplacement, TransformSnapshot, apply_color_adjustments
from pdf_colors import recolor_pdf
from video_creator import VideoExporter, VideoFrameSource
from vector_preview import VectorGraphicsView

APP = QApplication.instance() or QApplication([])


def make_pdf(path, width=595, height=842):
    writer = QPdfWriter(str(path))
    writer.setResolution(72)
    size = QPageSize(QSizeF(width, height), QPageSize.Unit.Point, "Test", QPageSize.SizeMatchPolicy.ExactMatch)
    writer.setPageLayout(QPageLayout(size, QPageLayout.Orientation.Portrait, QMarginsF(0, 0, 0, 0)))
    painter = QPainter(writer)
    painter.fillRect(QRectF(0, 0, width, height), QColor("white"))
    painter.setPen(QColor("black"))
    painter.drawText(QRectF(25, 25, 200, 30), "Selectable text")
    painter.setPen(QPen(QColor("black"), 0.5))
    painter.drawLine(50, 100, 50, 400)
    painter.drawLine(50, 400, 450, 400)
    painter.setPen(QPen(QColor("black"), 0))
    painter.drawLine(200, 100, 200, 400)
    painter.setPen(QPen(QColor("black"), 0.5))
    painter.drawLine(QPointF(width - 0.25, 100), QPointF(width - 0.25, 400))
    writer.newPage()
    painter.fillRect(QRectF(0, 0, width, height), QColor("white"))
    painter.setPen(QColor("red"))
    painter.drawText(QRectF(25, 25, 200, 30), "Second page")
    painter.end()


class PdfColorExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "figure.pdf"
        make_pdf(self.source)
        self.renderer = EpsRenderer()

    def tearDown(self):
        self.renderer.cache.cleanup()
        self.temp.cleanup()

    def test_color_matching_preserves_alpha_order_and_cancellation(self):
        image = QImage(4, 1, QImage.Format.Format_RGBA8888)
        for i, c in enumerate((QColor(0, 0, 0, 100), QColor(4, 4, 4), QColor(255, 0, 0), QColor(0, 0, 0, 0))):
            image.setPixelColor(i, 0, c)
        mappings = (ColorReplacement("#000000", "#FF0000", 8), ColorReplacement("#FF0000", "#00FF00"))
        result = apply_color_adjustments(image, False, mappings)
        self.assertEqual(result.pixelColor(0, 0), QColor(255, 0, 0, 100))
        self.assertEqual(result.pixelColor(1, 0), QColor("red"))
        self.assertEqual(result.pixelColor(2, 0), QColor(0, 255, 0))
        self.assertEqual(result.pixelColor(3, 0).alpha(), 0)
        cancelled = threading.Event()
        cancelled.set()
        self.assertEqual(apply_color_adjustments(image, False, mappings, cancelled), image)

    def test_pdf_recolor_keeps_text_and_vector_paths(self):
        output = self.root / "recolored.pdf"
        state = TransformSnapshot(False, (ColorReplacement("#000000", "#0000FF"),), ((2, 90),))
        with patch.object(EpsRenderer, "ghostscript_path", new_callable=PropertyMock, return_value=None):
            self.renderer.export_document(self.source, output, state, 2, 1, background="white")
        with PdfReader(output) as pdf:
            self.assertEqual(len(pdf.pages), 2)
            self.assertIn("Selectable", pdf.pages[0].extract_text())
            self.assertEqual(pdf.pages[1].rotation, 90)
            ops = pdf.pages[0].get_contents().operations
            self.assertTrue(any(op == b"RG" and list(map(float, args)) == [0, 0, 1] for args, op in ops))
            self.assertTrue(any(op in (b"l", b"re", b"S") for _, op in ops))
            self.assertFalse(pdf.pages[0].images)
        image = self.renderer.render_page_image(output, 72)
        self.assertGreater(image.pixelColor(50, 250).blue(), image.pixelColor(50, 250).red())

    def test_a4_600dpi_recolored_png_and_multipage_input(self):
        target = self.root / "600dpi.png"
        state = TransformSnapshot(False, (ColorReplacement("#000000", "#0000FF"),))
        started = time.monotonic()
        self.renderer.export_png(self.source, target, 600, "white", transforms=state)
        print(f"600 DPI recolored A4 PNG: {time.monotonic() - started:.2f}s", flush=True)
        reader = QImageReader(str(target))
        self.assertEqual((reader.size().width(), reader.size().height()), (4958, 7017))
        # Decode a small region/thumbnail instead of asking Qt's default PNG
        # decoder allocation budget to hold the >128 MiB full image.
        from PyQt6.QtCore import QSize
        reader.setScaledSize(QSize(595, 842))
        image = reader.read()
        self.assertFalse(image.isNull())
        self.assertGreater(image.pixelColor(50, 250).blue(), image.pixelColor(50, 250).red())
        exporter = VideoExporter(self.renderer)
        try:
            self.assertEqual(self.renderer.page_count(self.source), 2)
            self.assertNotEqual(exporter.read_frame(VideoFrameSource(self.source, 1), "#FFFFFF", 72),
                                exporter.read_frame(VideoFrameSource(self.source, 2), "#FFFFFF", 72))
        finally:
            exporter.close()

    def test_thin_axes_survive_zoom_and_automatic_text_or_pan(self):
        view = VectorGraphicsView()
        view.resize(850, 800)
        view.show()
        view.load_pdf(self.source, 1, reset_view=True)
        view.set_text_selection_mode(True)

        def settle():
            view._refresh_visible_tiles()
            deadline = time.monotonic() + 15
            while view._in_flight or view._queued or view._color_jobs:
                APP.processEvents()
                if time.monotonic() > deadline:
                    self.fail("Preview rendering did not finish")
                time.sleep(.005)
            APP.processEvents()

        try:
            for zoom in (.6, .83, 1, 1.25, 1.5, 2, 3):
                view.zoom_by(zoom / view.transform().m11())
                for x in (50, 200, 594.75):
                    view.centerOn(x, 250)
                    settle()
                    screenshot = view.viewport().grab().toImage()
                    ratio = screenshot.devicePixelRatio()
                    for y in (230, 250, 270):
                        point = view.mapFromScene(QPointF(x, y))
                        px, py = round(point.x() * ratio), round(point.y() * ratio)
                        # A visible dark sample must survive next to each axis,
                        # including a PDF hairline and a tightly cropped edge.
                        ink = min(screenshot.pixelColor(px + dx, py).lightness()
                                  for dx in range(-2, 3))
                        self.assertLess(ink, 245, (zoom, x, y, ink))
            view.reset_to_actual_size()
            view.centerOn(100, 65)
            settle()
            bounds = QRectF()
            for polygon in view._active_context.document.getAllText(0).bounds():
                bounds = bounds.united(polygon.boundingRect())
            start = view.mapFromScene(bounds.topLeft())
            end = view.mapFromScene(bounds.bottomRight())
            def hover(point):
                # Send through Qt's viewport event route. Host cursor movement
                # can be intercepted by an unrelated foreground/remote window.
                event = QMouseEvent(QEvent.Type.MouseMove, QPointF(point),
                                    QPointF(view.viewport().mapToGlobal(point)),
                                    Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                                    Qt.KeyboardModifier.NoModifier)
                APP.sendEvent(view.viewport(), event)
            hover(start)
            self.assertEqual(view.viewport().cursor().shape(), Qt.CursorShape.IBeamCursor)
            QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseMove(view.viewport(), end)
            QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
            self.assertIn("Selectable", view._selection.text())
            view.zoom_by(2)
            view.centerOn(300, 300)
            settle()
            blank = view.mapFromScene(QPointF(300, 300))
            hover(blank)
            self.assertEqual(view.viewport().cursor().shape(), Qt.CursorShape.OpenHandCursor)
            before = view.mapToScene(QPoint(400, 400))
            QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=blank)
            QTest.mouseMove(view.viewport(), blank + QPoint(30, 30))
            QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=blank + QPoint(30, 30))
            self.assertIsNone(view._selection)
            self.assertNotEqual(view.mapToScene(QPoint(400, 400)), before)
        finally:
            view.close()


if __name__ == "__main__":
    unittest.main()
