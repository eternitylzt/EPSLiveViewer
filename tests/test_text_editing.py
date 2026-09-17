"""Conservative editing, preserved vectors/originals, landing page and UI."""
import hashlib
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import QSize, Qt, QPointF, QEvent
from PyQt6.QtGui import QFontDatabase, QTextCursor, QMouseEvent
from PyQt6.QtTest import QTest
from PyQt6.QtPdf import QPdfDocument
from PyQt6.QtWidgets import QApplication, QMessageBox
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject, ByteStringObject

from config import ConfigManager, AppConfig
from eps_renderer import EpsRenderer
from text_objects import discover_text, make_stamp, write_edits, TextStyle
from text_editor import TextEditorDialog
from document_palette import vector_palette
from image_transforms import TransformSnapshot
from viewer import MainWindow
from rich_text import read_style

APP = QApplication.instance() or QApplication([])


def fixture(path, extra=""):
    writer = PdfWriter()
    font = DictionaryObject({NameObject("/Type"):NameObject("/Font"),
                             NameObject("/Subtype"):NameObject("/Type1"),
                             NameObject("/BaseFont"):NameObject("/Helvetica")})
    for n in range(2):
        page = writer.add_blank_page(width=400,height=300)
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"):
            DictionaryObject({NameObject("/F1"):font})})
        stream = DecodedStreamObject()
        stream.set_data(("0.1 0.3 0.8 RG 2 w 10 10 m 390 290 l S\n"
                        "0 0 0 rg BT /F1 20 Tf 1 0 0 1 60 200 Tm (Original label) Tj ET\n"
                        "BT /F1 12 Tf 1 0 0 1 40 30 Tm (Do not alter) Tj ET\n"+extra).encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(path)
    writer.close()


def settle(dialog):
    deadline = time.monotonic()+15
    while dialog._busy and time.monotonic()<deadline:
        APP.processEvents()
        time.sleep(.01)
    APP.processEvents()
    if dialog._busy:
        raise AssertionError("Text operation timed out")


class TextEditingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.source = self.folder/"input.pdf"
        fixture(self.source)
        self.renderer = EpsRenderer()

    def tearDown(self):
        self.renderer.cache.cleanup()
        self.temp.cleanup()

    def test_real_replacement_preserves_vectors_pages_and_source(self):
        before = self.source.read_bytes()
        objects = discover_text(self.source)
        self.assertEqual(len(objects),4)
        obj = objects[0]
        style = replace(obj.style,text="Edited scientific label",color="#CC1100",bold=True,angle=15)
        stamp = self.folder/"stamp.pdf"
        margin = make_stamp(stamp,style)
        target = self.folder/"edited.pdf"
        write_edits(self.source,target,objects,{obj.key:style},{obj.key:(stamp,margin)})
        with PdfReader(target) as pdf:
            self.assertEqual(len(pdf.pages),2)
            text = pdf.pages[0].extract_text()
            self.assertNotIn("Original label",text)
            self.assertIn("Do not alter",text)
            self.assertIn("Original label",pdf.pages[1].extract_text())
            self.assertTrue(any(op==b"S" for args,op in pdf.pages[0].get_contents().operations))
            self.assertEqual(pdf.pages[0].get("/Resources").get("/XObject")["/ELVText0"].get_object()["/Subtype"],"/Form")
        self.assertIn("Edited scientific label",[x.style.text for x in discover_text(target)])
        self.assertEqual(before,self.source.read_bytes())
        qt = QPdfDocument(None)
        try:
            self.assertEqual(qt.load(str(target)),QPdfDocument.Error.None_)
            image = qt.render(0,QSize(800,600))
            self.assertFalse(image.isNull())
        finally:
            qt.close()
        reopened = discover_text(target)
        self.assertIn("Edited scientific label",[x.style.text for x in reopened])
        edited_run = next(x for x in reopened if x.style.text == style.text)
        self.assertAlmostEqual(edited_run.x,obj.x,places=4)
        self.assertAlmostEqual(edited_run.y,obj.y,places=4)
        second_style = replace(style,text="Second revision",angle=-20)
        second_stamp = self.folder/"second-stamp.pdf"
        second_margin = make_stamp(second_stamp,second_style)
        second = self.folder/"second.pdf"
        write_edits(target,second,reopened,{edited_run.key:second_style},
                    {edited_run.key:(second_stamp,second_margin)})
        with PdfReader(second) as pdf:
            self.assertNotIn("Edited scientific label",pdf.pages[0].extract_text())
        self.assertIn("Second revision",[x.style.text for x in discover_text(second)])
        if self.renderer.ghostscript_path:
            for suffix,count in ((".ps",2),(".eps",1)):
                output = self.folder/("export"+suffix)
                self.renderer.export_document(target,output,TransformSnapshot(),2,1,vector_text=True)
                result = self.renderer.convert_to_pdf(output)
                with PdfReader(result.pdf_path) as pdf:
                    self.assertEqual(len(pdf.pages),count)
                    # Older Ghostscript may outline embedded fonts. It must
                    # not cache the edited glyphs as bitmap image masks.
                    self.assertFalse(any(op==b"INLINE IMAGE" for args,op in pdf.pages[0].get_contents().operations))

    def test_unsafe_text_skipped_and_document_palette(self):
        fixture(self.source,"BT /F1 12 Tf 20 40 Td (part1) Tj (part2) Tj ET\n"
                "q 0 0 50 50 re W n BT /F1 12 Tf 20 40 Td (clipped) Tj ET Q\n")
        objects = discover_text(self.source)
        self.assertEqual(len(objects),4)
        palette = vector_palette(self.source)
        self.assertIn("#000000",palette)
        self.assertIn("#1A4DCC",palette)

    def test_unicode_font_validation_and_dialog_undo(self):
        families = QFontDatabase.families()
        family = next((x for x in ("Microsoft YaHei","Noto Sans CJK SC","PingFang SC") if x in families),None)
        if family:
            path = self.folder/"unicode.pdf"
            try:
                make_stamp(path,TextStyle("科学 αβ ± ≤",family,18,"#000000"))
            except ValueError:
                family = None
            if family:
                doc = QPdfDocument(None)
                doc.load(str(path))
                self.assertIn("科学",doc.getAllText(0).text())
                self.assertIn("αβ",doc.getAllText(0).text())
                doc.close()
                # Combine Qt's positioned glyphs into a simple Identity-H run,
                # modeling a recognizable CJK PostScript-to-PDF label.
                with PdfReader(path) as reader:
                    writer = PdfWriter(clone_from=reader)
                    page = writer.pages[0]
                    stream = page.get_contents()
                    shows = [args[0].original_bytes for args,op in stream.operations if op==b"Tj"]
                    start = next(i for i,(_,op) in enumerate(stream.operations) if op==b"Tj")
                    end = next(i for i,(_,op) in enumerate(stream.operations[start:],start) if op==b"ET")
                    stream.operations = stream.operations[:start]+[([ByteStringObject(b"".join(shows))],b"Tj")]+stream.operations[end:]
                    page.replace_contents(stream)
                    # Ignore Qt's benign color/graphics state for this font test.
                    stream = page.get_contents()
                    stream.operations = [(a,b) for a,b in stream.operations if b not in (b"gs",b"cs",b"scn")]
                    page.replace_contents(stream)
                    cid = self.folder/"cid.pdf"
                    writer.write(cid)
                    writer.close()
                self.assertEqual(discover_text(cid)[0].style.text,"科学 αβ ± ≤")
        dialog = TextEditorDialog(self.source,self.source,self.renderer,TransformSnapshot())
        dialog.show()
        settle(dialog)
        self.assertEqual(dialog.items.count(),2)
        dialog._start_edit(dialog.objects[0])
        settle(dialog)
        cursor = dialog._active_item.textCursor()
        cursor.insertText("Revised title")
        dialog._active_item.setTextCursor(cursor)
        dialog._apply()
        settle(dialog)
        self.assertEqual(len(dialog.edits),1)
        self.assertTrue(dialog.undo.isEnabled())
        dialog._history(False)
        settle(dialog)
        self.assertEqual(dialog.edits,{})
        dialog.reject()
        self.assertFalse(dialog.isVisible())

    def test_home_toolbar_and_source_protection(self):
        manager = ConfigManager()
        manager.base_dir = self.folder
        manager.path = self.folder/"config.json"
        manager.save(AppConfig(auto_refresh=False))
        window = MainWindow(manager)
        window.show()
        APP.processEvents()
        self.assertIs(window._pages.currentWidget(),window._welcome)
        self.assertIn("eternitylzt@gmail.com",window._welcome.footer.text())
        for action in window._toolbar.actions():
            self.assertFalse(action.icon().isNull())
        window.close()
        dialog = TextEditorDialog(self.source,self.source,self.renderer,TransformSnapshot())
        settle(dialog)
        before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        with patch("text_editor.QFileDialog.getSaveFileName",return_value=(str(self.source),"PDF (*.pdf)")), patch.object(QMessageBox,"warning") as warning:
            dialog._save()
            warning.assert_called_once()
        self.assertEqual(before,hashlib.sha256(self.source.read_bytes()).hexdigest())
        dialog.reject()

    def test_double_click_rotated_label_partial_styles_and_symbols(self):
        dialog = TextEditorDialog(self.source,self.source,self.renderer,TransformSnapshot(page_rotations=((1,90),)))
        dialog.show()
        settle(dialog)
        self.assertTrue(dialog.items.isHidden())
        obj = dialog.objects[0]
        pos = dialog.preview.mapFromScene(dialog.preview._page_item.mapToScene(dialog._rect(obj).center()))
        QTest.mouseDClick(dialog.preview.viewport(),Qt.MouseButton.LeftButton,pos=pos)
        settle(dialog)
        self.assertIsNotNone(dialog._active_item)
        self.assertNotIn("No editable",dialog.status.text())
        item = dialog._active_item
        cursor = item.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(8,QTextCursor.MoveMode.KeepAnchor)
        item.setTextCursor(cursor)
        dialog._format("color","#FF0000")
        dialog._format("bold",True)
        dialog._format("size",28)
        style = read_style(item.document(),dialog.angle.value())
        self.assertEqual(style.runs[0].text,"Original")
        self.assertEqual(style.runs[0].color,"#ff0000")
        self.assertEqual(style.runs[0].size,28)
        self.assertTrue(style.runs[0].bold)
        self.assertEqual(style.runs[-1].text," label")
        self.assertEqual(style.runs[-1].color,"#000000")
        self.assertFalse(style.runs[-1].bold)
        cursor = item.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        item.setTextCursor(cursor)
        dialog._insert_symbol("α")
        self.assertTrue(item.toPlainText().endswith("α"))
        # Actual key events must reach the text item rather than navigate pages.
        dialog.preview.setFocus()
        item.setFocus()
        QTest.keyClick(dialog.preview.viewport(),Qt.Key.Key_Backspace)
        self.assertEqual(item.toPlainText(),"Original label")
        dialog._apply()
        settle(dialog)
        self.assertEqual(len(dialog.edits),1)
        reopened = next(x for x in discover_text(dialog.current) if x.style.text=="Original label" and x.page==0)
        self.assertEqual(reopened.style.runs[0].color,"#ff0000")
        self.assertEqual(reopened.style.runs[-1].color,"#000000")
        self.assertAlmostEqual(abs(reopened.style.angle),90)
        with patch.object(QMessageBox,"question",return_value=QMessageBox.StandardButton.Discard):
            dialog.reject()

    def test_save_commits_live_edits_and_eps_is_first_filter(self):
        dialog = TextEditorDialog(self.source,self.source,self.renderer,TransformSnapshot())
        settle(dialog)
        dialog._start_edit(dialog.objects[0])
        settle(dialog)
        cursor = dialog._active_item.textCursor()
        cursor.insertText("Live save")
        dialog._active_item.setTextCursor(cursor)
        target = self.folder/"saved.pdf"
        with patch("text_editor.QFileDialog.getSaveFileName",return_value=(str(target),"PDF (*.pdf)")) as picker:
            dialog._save()
            settle(dialog)
            self.assertTrue(picker.call_args.args[2].endswith("-edited.eps"))
            self.assertEqual(picker.call_args.args[3],"EPS (*.eps);;PostScript (*.ps);;PDF (*.pdf)")
        self.assertTrue(target.is_file())
        self.assertIn("Live save",[x.style.text for x in discover_text(target)])
        self.assertIsNone(dialog._active_item)
        self.assertEqual(dialog.edits,dialog._saved_edits)
        dialog.reject()

    def test_main_preview_double_click_maps_rotated_text_to_editor(self):
        manager = ConfigManager()
        manager.base_dir = self.folder
        manager.path = self.folder/"settings.json"
        manager.save(AppConfig(auto_refresh=False))
        window = MainWindow(manager)
        window.show()
        window.open_eps(self.source)
        deadline = time.monotonic()+10
        while window._current_pdf is None and time.monotonic()<deadline:
            APP.processEvents();time.sleep(.01)
        self.assertIsNotNone(window._current_pdf)
        window._rotate_right_action.trigger()
        APP.processEvents()
        view = window._view
        bounds = view._active_context.document.getAllText(0).bounds()[0].boundingRect()
        point = bounds.topLeft() + QPointF(.5,.5)
        position = view.mapFromScene(view._page_item.mapToScene(point))
        hits = []
        view.edit_text_requested.disconnect()
        view.edit_text_requested.connect(hits.append)
        QTest.mouseDClick(view.viewport(),Qt.MouseButton.LeftButton,pos=position)
        APP.processEvents()
        self.assertEqual(len(hits),1)
        dialog = TextEditorDialog(window._current_pdf,self.source,self.renderer,
                                  window._current_transforms().snapshot(),initial_point=hits[0])
        settle(dialog)
        self.assertIsNotNone(dialog._active_item)
        self.assertEqual(dialog._active_item.toPlainText(),"Original label")
        dialog.reject()
        window._discard_on_close = True
        window.close()

    def test_positioned_rotated_fragments_and_canvas_preserved_on_export(self):
        fixture(self.source,"BT /F1 20 Tf 0 1 -1 0 300 70 Tm (Rotated) Tj 0 30 Td (Second) Tj ET\n")
        objects = discover_text(self.source)
        rotated = [o for o in objects if o.page==0 and o.style.angle==90]
        self.assertEqual([o.style.text for o in rotated],["Rotated","Second"])
        edits,stamps = {},{}
        for i,obj in enumerate(rotated):
            style = replace(obj.style,text=f"Edit {i}")
            stamp = self.folder/f"fragment{i}.pdf"
            stamps[obj.key]=(stamp,make_stamp(stamp,style))
            edits[obj.key]=style
        target = self.folder/"fragments.pdf"
        write_edits(self.source,target,objects,edits,stamps)
        self.assertEqual(tuple(PdfReader(target).pages[0].mediabox),(0,0,400,300))
        result = [x.style.text for x in discover_text(target) if x.page == 0]
        self.assertIn("Edit 0",result);self.assertIn("Edit 1",result)
        self.assertNotIn("Rotated",result);self.assertNotIn("Second",result)
        if self.renderer.ghostscript_path:
            for suffix in (".eps",".ps"):
                output=self.folder/("canvas"+suffix)
                self.renderer.export_document(target,output,TransformSnapshot(),2,1,vector_text=True)
                converted=self.renderer.convert_to_pdf(output)
                with PdfReader(converted.pdf_path) as doc:
                    box=doc.pages[0].mediabox
                    self.assertAlmostEqual(float(box.width),400,delta=.02)
                    self.assertAlmostEqual(float(box.height),300,delta=.02)
            rotated_output=self.folder/"rotated-canvas.eps"
            self.renderer.export_document(target,rotated_output,TransformSnapshot(page_rotations=((1,90),)),2,1,vector_text=True)
            converted=self.renderer.convert_to_pdf(rotated_output)
            with PdfReader(converted.pdf_path) as doc:
                self.assertAlmostEqual(float(doc.pages[0].mediabox.width),300,delta=.02)
                self.assertAlmostEqual(float(doc.pages[0].mediabox.height),400,delta=.02)

    def test_rotated_hover_cursor_and_reading_vs_editing_bounds(self):
        fixture(self.source,"BT /F1 20 Tf 0 1 -1 0 300 70 Tm (Rotated) Tj 0 30 Td (Second) Tj ET\n")
        dialog=TextEditorDialog(self.source,self.source,self.renderer,TransformSnapshot())
        dialog.show();settle(dialog)
        obj=next(o for o in dialog.objects if o.style.text=="Rotated")
        point=dialog._rect(obj).center()
        pos=dialog.preview.mapFromScene(dialog.preview._page_item.mapToScene(point))
        event=QMouseEvent(QEvent.Type.MouseMove,QPointF(pos),
                         QPointF(dialog.preview.viewport().mapToGlobal(pos)),
                         Qt.MouseButton.NoButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier)
        APP.sendEvent(dialog.preview.viewport(),event)
        APP.processEvents()
        self.assertEqual(dialog.preview.viewport().cursor().shape(),Qt.CursorShape.IBeamCursor)
        QTest.mouseDClick(dialog.preview.viewport(),Qt.MouseButton.LeftButton,pos=pos)
        settle(dialog)
        self.assertEqual(dialog._active_item.toPlainText(),"Rotated")
        dialog.reject()


if __name__ == "__main__":
    unittest.main()
