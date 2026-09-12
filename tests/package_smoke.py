"""Run from source or freeze with the production hooks to verify the payload.

Usage: package_smoke.exe path/to/multipage.eps
The test uses temporary files/settings and never changes the source document.
"""

import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import QMimeData, QPoint, QPointF, QSettings, Qt, QUrl
from PyQt6.QtGui import QColor, QDragEnterEvent, QDropEvent, QImage, QImageReader, QWheelEvent
from PyQt6.QtPdf import QPdfDocument
from PyQt6.QtWidgets import QApplication, QDialog
from PyQt6 import sip

from config import AppConfig, ConfigManager
from color_dialog import ColorReplacementDialog
from dialogs import SettingsDialog
from encoder import ffmpeg_executable
from eps_renderer import EpsRenderError
from i18n import set_language
from image_transforms import ColorReplacement, TransformSnapshot
from main import EpsApplication
from video_creator import (
    VideoExporter,
    VideoExportCancelled,
    VideoExportRequest,
    VideoFrameSource,
)
from video_dialog import VideoCreationDialog
from viewer import MainWindow


def wait_for(app, predicate):
    deadline = time.monotonic() + 20
    while not predicate():
        assert time.monotonic() < deadline, "Timed out waiting for preview"
        app.processEvents()
        time.sleep(0.01)


def run():
    source = Path(sys.argv[1]).resolve()
    assert source.is_file()
    app = EpsApplication([])
    app.setOrganizationName("EPSLiveViewerPackagingTest")
    app.setApplicationName("Smoke")
    with tempfile.TemporaryDirectory(prefix="eps_smoke_") as folder:
        root = Path(folder)
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, folder)
        manager = ConfigManager()
        manager.base_dir, manager.path = root, root / "config.json"
        window = MainWindow(manager)
        window.show()
        try:
            eps = root / "01.eps"
            eps.write_bytes(source.read_bytes())
            ps = root / "02.ps"
            ps.write_bytes(source.read_bytes())
            window.open_eps(eps)
            wait_for(app, lambda: window._page_count >= 2)
            page_count = window._page_count
            window._next_page_action.trigger()
            assert window._current_page_index == 1
            window._view.zoom_by(2)
            window._view.fit_to_window()
            window._view.reset_to_actual_size()
            for mode in ("white", "custom", "transparent"):
                window._view.set_page_background(mode, "#123456")
                assert not window._view.grab().isNull()

            def wheel(mode, modifiers=Qt.KeyboardModifier.NoModifier):
                window._view.set_wheel_action(mode)
                event = QWheelEvent(QPointF(40, 40), QPointF(40, 40), QPoint(), QPoint(0, -120),
                                    Qt.MouseButton.NoButton, modifiers, Qt.ScrollPhase.ScrollUpdate, False)
                window._view.wheelEvent(event)

            wheel("pages")
            assert window._current_page_index == min(2, page_count - 1)
            previous = window._current_page_index
            zoom = window._view.transform().m11()
            wheel("pages", Qt.KeyboardModifier.ControlModifier)
            assert window._current_page_index == previous and window._view.transform().m11() < zoom
            wheel("files")
            wait_for(app, lambda: window._current_file == ps and window._page_count >= 2)
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(eps))])
            enter = QDragEnterEvent(QPoint(40, 40), Qt.DropAction.CopyAction, mime,
                                   Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            window._view.dragEnterEvent(enter)
            assert enter.isAccepted()
            drop = QDropEvent(QPointF(40, 40), Qt.DropAction.CopyAction, mime,
                             Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            window._view.dropEvent(drop)
            wait_for(app, lambda: window._current_file == eps and window._page_count >= 2)
            old_pdf = window._current_pdf
            eps.write_bytes(source.read_bytes() + b"\n")
            wait_for(app, lambda: window._current_pdf != old_pdf)

            renderer = window._renderer
            window._rotate_right_action.trigger()
            window._invert_colors_action.setChecked(True)
            assert window._current_transforms().rotation_for(
                window._current_page_index + 1
            ) == 90
            assert window._current_transforms().inverted
            assert not window._view.grab().isNull()

            # Real menu path: accept the color editor, render changed tiles,
            # then reopen it. The old tr(source=...) crash lived in this path.
            mappings = (ColorReplacement("#000000", "#00FF00", 8),)
            def accept_colors(dialog):
                dialog._list.addItem(dialog._item(mappings[0]))
                return QDialog.DialogCode.Accepted
            with patch.object(ColorReplacementDialog, "exec", accept_colors):
                window._replace_colors_action.trigger()
            assert window._current_transforms().replacements == mappings
            assert window._view._in_flight == sum(
                len(context.pending) for context in window._view._contexts.values()
            )
            wait_for(app, lambda: window._view._in_flight == 0 and not window._view._color_jobs)
            assert not window._view.grab().isNull()
            editor = ColorReplacementDialog(mappings, window)
            assert editor.replacements() == mappings
            editor.close()
            window._reset_transforms()
            window._rotate_all_action.trigger()
            window._rotate_right_action.trigger()
            assert all(window._current_transforms().rotation_for(p) == 90
                       for p in range(1, page_count + 1))
            window._undo_action.trigger()
            assert all(window._current_transforms().rotation_for(p) == 0
                       for p in range(1, page_count + 1))
            window._redo_action.trigger()
            assert all(window._current_transforms().rotation_for(p) == 90
                       for p in range(1, page_count + 1))
            window._rotate_current_action.trigger()
            window._rotate_left_action.trigger()
            assert window._current_transforms().rotation_for(window._current_page_index + 1) == 0
            assert window._rotation_scope_button.text() == window._rotate_current_action.text()
            window._reset_transforms()
            window._view.set_page(0)
            window._rotate_right_action.trigger()
            original_state = window._current_transforms().snapshot()
            previews = []
            def preview_and_close(dialog):
                previews.append(dialog._load_reference_preview())
                return QDialog.DialogCode.Rejected
            # Reopen through the same main-window action a user invokes.
            with patch.object(VideoCreationDialog, "exec", preview_and_close):
                for _ in range(3):
                    window._make_video_action.trigger()
            assert all(image == previews[0] for image in previews)
            assert window._current_transforms().snapshot() == original_state
            assert window._view._rotation == 90

            png1 = renderer.export_png(eps, root / "page1.png", dpi=72, page_number=1)
            png2 = renderer.export_png(eps, root / "page2.png", dpi=72, page_number=2,
                                       background="custom", background_color="#123456")
            assert png1.read_bytes() != png2.read_bytes()
            assert QImage(str(png1)).hasAlphaChannel()
            pdf = renderer.export_pdf(eps, root / "multipage")
            assert pdf.suffix == ".pdf" and pdf.is_file()
            document = QPdfDocument(None)
            assert document.load(str(pdf)) == QPdfDocument.Error.None_
            assert document.pageCount() == page_count
            document.close()
            sip.delete(document)
            transformed = TransformSnapshot(
                True,
                (ColorReplacement("#000000", "#FFFFFF", 8),),
                ((1, 90), (2, 180), (3, 270)),
            )
            all_pages = renderer.export_png_pages(
                eps,
                root / "all_pages",
                page_count,
                dpi=72,
                transforms=transformed,
            )
            assert len(list(all_pages.glob("*.png"))) == page_count
            transformed_pdf = renderer.export_document(
                eps,
                root / "transformed.pdf",
                TransformSnapshot(True, (), ((1, 90),)),
                page_count,
                1,
                dpi=72,
            )
            document = QPdfDocument(None)
            assert document.load(str(transformed_pdf)) == QPdfDocument.Error.None_
            assert document.pageCount() == page_count
            assert document.pagePointSize(0).width() > document.pagePointSize(0).height()
            document.close()
            sip.delete(document)
            transformed_ps = renderer.export_document(
                eps,
                root / "transformed.ps",
                TransformSnapshot(True, (), ((2, 90),)),
                page_count,
                2,
                dpi=72,
            )
            transformed_eps = renderer.export_document(
                eps,
                root / "transformed.eps",
                TransformSnapshot(True, (), ((2, 90),)),
                page_count,
                2,
                dpi=72,
            )
            assert renderer.page_count(transformed_ps) == page_count
            assert renderer.page_count(transformed_eps) == 1
            existing = root / "existing.pdf"
            existing.write_bytes(b"keep existing output")
            broken = root / "broken.eps"
            broken.write_bytes(b"this is not PostScript")
            try:
                renderer.export_pdf(broken, existing)
                raise AssertionError("Invalid EPS unexpectedly produced a PDF")
            except EpsRenderError:
                assert existing.read_bytes() == b"keep existing output"
            frame = QImage(83, 65, QImage.Format.Format_RGB32)
            frame.fill(QColor("red"))
            jpg = root / "frame.jpg"
            assert frame.save(str(jpg), "JPG")
            assert VideoExporter.read_raster(jpg).size() == frame.size()
            raster_transforms = TransformSnapshot(
                True,
                (ColorReplacement("#00FFFF", "#00FF00", 8),),
                ((1, 90),),
            )
            adjusted_raster = renderer.export_png(
                jpg,
                root / "adjusted_raster.png",
                transforms=raster_transforms,
            )
            adjusted_image = QImage(str(adjusted_raster))
            assert adjusted_image.size() == frame.size().transposed()
            assert adjusted_image.pixelColor(0, 0).green() > 240
            sequence_folder = root / "sequence_sources"
            sequence_folder.mkdir()
            sequence_eps = sequence_folder / eps.name
            sequence_eps.write_bytes(eps.read_bytes())
            sequence_jpg = sequence_folder / jpg.name
            sequence_jpg.write_bytes(jpg.read_bytes())
            sequence_dialog = VideoCreationDialog(
                sequence_folder,
                renderer,
                {sequence_eps: TransformSnapshot(False, (), ((1, 90),))},
                window,
            )
            assert sequence_dialog._included.count() == page_count + 1
            assert sequence_dialog.selected_frames()[0].page_number == 1
            sequence_dialog.close()
            window.open_eps(jpg)
            wait_for(app, lambda: window._current_file == jpg and window._page_count == 1)
            assert not window._view.grab().isNull()
            exporter = VideoExporter(renderer)
            started = time.monotonic()
            ffmpeg = ffmpeg_executable()
            print("Encoder first-use seconds:", round(time.monotonic() - started, 3), flush=True)
            assert ffmpeg_executable() == ffmpeg
            for suffix, width, height in (("mp4", 80, 64), ("mp4", 81, 65), ("gif", 81, 65)):
                target = root / f"video{width}.{suffix}"
                request = VideoExportRequest((eps, ps, png1, jpg), target, suffix, width, height, 4,
                                             crop_rect=(0.1, 0.1, 0.6, 0.7))
                exporter.create(request, threading.Event())
                decoded = subprocess.run([str(ffmpeg), "-v", "error", "-i", str(target),
                                          "-f", "null", "-"], capture_output=True,
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                assert decoded.returncode == 0, decoded.stderr
                if suffix == "gif":
                    reader = QImageReader(str(target))
                    assert reader.imageCount() == 4
                    reader.setFileName("")
                cancelled = threading.Event()
                cancelled.set()
                original = target.read_bytes()
                try:
                    exporter.create(request, cancelled)
                    raise AssertionError("Cancellation was ignored")
                except VideoExportCancelled:
                    assert target.read_bytes() == original
            page_gif = root / "multipage.gif"
            exporter.create(
                VideoExportRequest(
                    tuple(
                        VideoFrameSource(
                            eps,
                            page,
                            TransformSnapshot(False, (), ((page, 90 if page == 1 else 0),)),
                        )
                        for page in range(1, page_count + 1)
                    ),
                    page_gif,
                    "gif",
                    80,
                    64,
                    4,
                ),
                threading.Event(),
            )
            reader = QImageReader(str(page_gif))
            assert reader.imageCount() == page_count
            reader.setFileName("")
            for language in ("en", "zh_CN"):
                window._config.language = language
                set_language(language)
                window._retranslate_ui()
                assert "PDF" in window._save_pdf_action.text().replace("&", "")
                update_text = window._check_updates_action.text().replace("&", "")
                assert ("Update" in update_text) if language == "en" else ("更新" in update_text)
                settings = SettingsDialog(window._config, window)
                assert settings.get_config().language == language
                settings.close()
            print("PASS: multipage preview/PNG/video, rotation, inversion, color replacement, EPS/PS/PDF export, PNG/JPG opening, zoom, navigation, drop, live refresh, MP4/GIF, crop, cancellation, languages, update menu", flush=True)
        finally:
            window.close()
            app.processEvents()


if __name__ == "__main__":
    run()
