"""Direct page text editing, selected-character styles and vector Save As."""
from __future__ import annotations
import shutil
import tempfile
from pathlib import Path
from PyQt6.QtCore import Qt, pyqtSignal, QRectF
from PyQt6.QtGui import QColor, QFontDatabase, QFont, QTextCursor, QTextCharFormat, QAction, QKeySequence
from PyQt6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QSplitter, QVBoxLayout, QWidget, QGraphicsTextItem,
    QGraphicsView, QToolButton, QMenu, QWidgetAction, QTabWidget, QGridLayout, QScrollArea)
from pypdf import PdfReader, PdfWriter
from background_tasks import TaskRunner
from image_transforms import TransformSnapshot
from i18n import bilingual as L
from pdf_colors import recolor_pdf
from text_objects import discover_text, make_stamp, write_edits, text_bounds
from rich_text import make_document, document_metrics, read_style
from vector_preview import VectorGraphicsView
from window_geometry import fit_initial_window


class EditableLabel(QGraphicsTextItem):
    cursor_changed = pyqtSignal()
    finish_requested = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.finish_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)
        self.cursor_changed.emit()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.cursor_changed.emit()

    def mouseDoubleClickEvent(self, event):
        super().mouseDoubleClickEvent(event)
        self.cursor_changed.emit()


class EditingView(VectorGraphicsView):
    text_double_clicked = pyqtSignal(object)
    active_label = None
    editable_at = None

    def mouseDoubleClickEvent(self, event):
        if self.active_label is not None:
            QGraphicsView.mouseDoubleClickEvent(self, event)
        elif self.has_document() and event.button() == Qt.MouseButton.LeftButton:
            self.text_double_clicked.emit(self._page_point(event.position()))
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        if self.active_label is not None:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            QGraphicsView.mousePressEvent(self, event)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.active_label is not None:
            QGraphicsView.mouseMoveEvent(self, event)
        else:
            super().mouseMoveEvent(event)
        if event.buttons() == Qt.MouseButton.NoButton and self.has_document() and self.editable_at:
            point = self._page_point(event.position())
            editable = self.editable_at(point) or (self.active_label is not None and
                        self.active_label.contains(self.active_label.mapFromParent(point)))
            self.viewport().setCursor(Qt.CursorShape.IBeamCursor if editable else Qt.CursorShape.OpenHandCursor)

    def mouseReleaseEvent(self, event):
        if self.active_label is not None:
            QGraphicsView.mouseReleaseEvent(self, event)
        else:
            super().mouseReleaseEvent(event)


class TextEditorDialog(QDialog):
    def __init__(self, pdf, source, renderer, transforms, parent=None, page=0, show_list=False, initial_point=None):
        super().__init__(parent)
        self.setWindowTitle(L("编辑可识别文字", "Edit Recognizable Text"))
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self._temp = tempfile.TemporaryDirectory(prefix="eps-text-")
        self.folder = Path(self._temp.name)
        self.base, self.snapshot = self.folder/"base.pdf", self.folder/"source.pdf"
        shutil.copyfile(pdf, self.snapshot)
        self.source, self.renderer = Path(source).resolve(), renderer
        self.source_signature = self._signature()
        self.objects, self.edits, self.stamps = [], {}, {}
        self.undo_states, self.redo_states, self._saved_edits = [], [], {}
        self._generation, self._displayed_page = 0, -1
        self._busy, self._draft, self._loading_fields = True, False, False
        self._active_object = self._active_item = None
        self._initial_page = page
        self._initial_point = initial_point
        self._runner = TaskRunner(self)
        self._build_ui(show_list)
        fit_initial_window(self, 1180, 780)
        def prepare(cancel):
            recolor_pdf(self.snapshot, self.base, transforms, cancel_event=cancel, paint_background=False)
            with PdfReader(self.base) as reader:
                writer = PdfWriter(clone_from=reader)
                for item in writer.pages:
                    if item.rotation:
                        item.transfer_rotation_to_content()
                normalized = self.folder/"normalized.pdf"
                writer.write(normalized)
                writer.close()
            normalized.replace(self.base)
            return discover_text(self.base, cancel)
        self._runner.submit(prepare, self._prepared)

    def _build_ui(self, show_list):
        root = QVBoxLayout(self)
        note = QLabel(L("双击可识别文字直接编辑；拖选其中的字符可设置局部样式。旋转作用于整段。原文件不变。",
                        "Double-click recognizable text to edit; select characters for local styles. Rotation applies to the whole label. Original unchanged."))
        note.setWordWrap(True)
        root.addWidget(note)
        navigation = QHBoxLayout()
        self.page = QComboBox()
        self.page.currentIndexChanged.connect(self._page_changed)
        self.list_toggle = QCheckBox(L("显示文字列表", "Show Text List"))
        self.list_toggle.setChecked(show_list)
        self.list_toggle.toggled.connect(self._toggle_list)
        navigation.addWidget(self.page)
        navigation.addWidget(self.list_toggle)
        navigation.addStretch()
        root.addLayout(navigation)
        split = QSplitter()
        self.items = QListWidget()
        self.items.currentRowChanged.connect(self._list_selected)
        self.items.setVisible(show_list)
        split.addWidget(self.items)
        self.preview = EditingView(self)
        self.preview.editable_at = self._hit_text
        self.preview.document_released.connect(self._release_preview)
        self.preview.set_page_background("white", "#FFFFFF")
        self.preview.text_double_clicked.connect(self._double_clicked)
        self.preview.page_navigation_requested.connect(self._navigate)
        split.addWidget(self.preview)
        panel = QWidget()
        form = QFormLayout(panel)
        self.family = QComboBox()
        families = QFontDatabase.families()
        preferred = ["Arial", "Helvetica", "Times New Roman", "Courier New", "Liberation Sans",
                     "Microsoft YaHei", "SimSun", "PingFang SC", "Noto Sans CJK SC"]
        self.family.addItems([x for x in preferred if x in families] + sorted(set(families)-set(preferred)))
        self.size = QDoubleSpinBox()
        self.size.setRange(1, 500)
        self.size.setSuffix(" pt")
        self.angle = QDoubleSpinBox()
        self.angle.setRange(-360, 360)
        self.angle.setSuffix("°")
        self.bold, self.italic = QCheckBox(L("粗体", "Bold")), QCheckBox(L("斜体", "Italic"))
        self.color = QLineEdit("#000000")
        pick = QPushButton(L("选色…", "Color…"))
        pick.clicked.connect(self._pick_color)
        color_row = QHBoxLayout()
        color_row.addWidget(self.color)
        color_row.addWidget(pick)
        self.range_label = QLabel()
        self.range_label.setWordWrap(True)
        form.addRow(self.range_label)
        form.addRow(L("字体", "Font"), self.family)
        form.addRow(L("字号", "Size"), self.size)
        form.addRow(L("颜色", "Color"), color_row)
        form.addRow(self.bold)
        form.addRow(self.italic)
        form.addRow(L("整段旋转", "Label Rotation"), self.angle)
        form.addRow(self._symbol_box())
        self.apply = QPushButton(L("应用", "Apply"))
        self.apply.clicked.connect(self._apply)
        form.addRow(self.apply)
        self.undo, self.redo = QPushButton(L("撤销", "Undo")), QPushButton(L("重做", "Redo"))
        self.undo.clicked.connect(lambda: self._history(False))
        self.redo.clicked.connect(lambda: self._history(True))
        history = QHBoxLayout()
        history.addWidget(self.undo)
        history.addWidget(self.redo)
        form.addRow(history)
        hint = QLabel(L("文字在页面上实时变化。“应用”结束本段编辑；“保存”包含当前修改。局部样式适用于同一可编辑片段内部，不跨独立片段排版。",
                        "Text changes live. Apply finishes this label; Save includes current changes. Mixed styles work within one editable run, not across separate runs."))
        hint.setWordWrap(True)
        form.addRow(hint)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        scroll.setMinimumWidth(260)
        split.addWidget(scroll)
        split.setSizes([190, 740, 280])
        split.setStretchFactor(1, 1)
        split.setChildrenCollapsible(False)
        root.addWidget(split, 1)
        self.status = QLabel(L("正在识别文字对象…", "Recognizing text objects…"))
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.status)
        footer = QHBoxLayout()
        fit = QPushButton(L("适应窗口", "Fit Window"))
        fit.clicked.connect(self.preview.fit_to_window)
        self.save = QPushButton(L("保存…", "Save…"))
        self.save.clicked.connect(self._save)
        self.close_button = QPushButton(L("关闭", "Close"))
        self.close_button.clicked.connect(self.reject)
        footer.addWidget(fit)
        footer.addStretch()
        footer.addWidget(self.save)
        footer.addWidget(self.close_button)
        root.addLayout(footer)
        save_action = QAction(self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self._save)
        self.addAction(save_action)
        self._field_widgets = (self.family, self.size, self.angle, self.bold, self.italic, self.color, pick)
        self.family.currentTextChanged.connect(lambda value: self._format("family", value))
        self.size.valueChanged.connect(lambda value: self._format("size", value))
        self.bold.toggled.connect(lambda value: self._format("bold", value))
        self.italic.toggled.connect(lambda value: self._format("italic", value))
        self.color.editingFinished.connect(self._color_edited)
        self.angle.valueChanged.connect(self._rotate)
        self._set_busy(True)

    def _symbol_box(self):
        button = QToolButton()
        button.setText(L("插入符号 ▾", "Insert Symbol ▾"))
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu, tabs = QMenu(button), QTabWidget()
        for title, characters in ((L("希腊字母", "Greek"), "αβγδεζηθικλμνξοπρστυφχψωΓΔΘΛΞΠΣΦΨΩ"),
                                  (L("运算与关系", "Operators"), "±×÷−≈≠≤≥∞∑∏∫√∂∇∝∈∉∩∪"),
                                  (L("其他", "More"), "°Åℏ→←↑↓↔⇒⇔²³₀₁₂₃₄₅₆₇₈₉")):
            page = QWidget()
            grid = QGridLayout(page)
            for i, char in enumerate(characters):
                tool = QToolButton()
                tool.setText(char)
                tool.setFixedSize(36, 34)
                tool.setToolTip(f"U+{ord(char):04X}")
                tool.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                tool.clicked.connect(lambda checked=False, text=char: (self._insert_symbol(text), menu.close()))
                grid.addWidget(tool, i//8, i%8)
            tabs.addTab(page, title)
        action = QWidgetAction(menu)
        action.setDefaultWidget(tabs)
        menu.addAction(action)
        button.setMenu(menu)
        return button

    def _insert_symbol(self, text):
        if self._active_item is not None:
            cursor = self._active_item.textCursor()
            cursor.insertText(text)
            self._active_item.setTextCursor(cursor)
            self._active_item.setFocus()

    def _signature(self):
        try:
            st = self.source.stat()
            return st.st_mtime_ns, st.st_size
        except OSError:
            return None

    def _toggle_list(self, visible):
        self.items.setVisible(visible)
        parent = self.parent()
        if parent is not None and hasattr(parent, "_config"):
            parent._config.text_list_visible = visible
            parent._save_config()

    def _set_busy(self, busy):
        self._busy = busy
        for widget in (self.items, self.page, self.save):
            widget.setEnabled(not busy)
        for widget in self._field_widgets:
            widget.setEnabled(not busy and self._active_item is not None)
        self.apply.setEnabled(not busy and self._active_item is not None)
        self.undo.setEnabled(not busy and (bool(self.undo_states) or self._active_item is not None))
        self.redo.setEnabled(not busy and (bool(self.redo_states) or self._active_item is not None))

    def _prepared(self, objects, error, cancelled):
        self._set_busy(False)
        if error or cancelled:
            self.status.setText(str(error or "Cancelled"))
            self.save.setEnabled(False)
            return
        self.objects = objects
        with PdfReader(self.base) as reader:
            self._page_boxes = [tuple(float(v) for v in page.cropbox) for page in reader.pages]
        self.page.blockSignals(True)
        self.page.addItems([L("第 ", "Page ")+str(i+1) for i in range(len(self._page_boxes))])
        self.page.setCurrentIndex(self._initial_page)
        self.page.blockSignals(False)
        self.current = self.base
        self._generation += 1
        self.preview.load_pdf(self.base, self._generation, page_index=self._initial_page)
        self._show_page(self._initial_page)
        if self._initial_point is not None:
            self._double_clicked(self._initial_point)

    def _show_page(self, index):
        self._displayed_page = index
        self.items.blockSignals(True)
        self.items.clear()
        for obj in self.objects:
            if obj.page == index:
                item = QListWidgetItem(self.edits.get(obj.key, obj.style).text)
                item.setData(Qt.ItemDataRole.UserRole, obj)
                self.items.addItem(item)
        self.items.setCurrentRow(-1)
        self.items.blockSignals(False)
        self.preview.set_page(index)
        self.status.setText(L("双击可识别文字进入编辑；空白处拖动平移。",
                             "Double-click recognizable text to edit; drag blank space to pan.") if self.items.count() else
                            L("此页暂无可直接编辑的文字，可能已转曲或使用不支持的结构。",
                              "No directly editable text on this page; it may be outlined or use an unsupported structure."))

    def _page_changed(self, index):
        if self._busy or index < 0:
            return
        if self._active_item is not None:
            self.page.blockSignals(True)
            self.page.setCurrentIndex(self._displayed_page)
            self.page.blockSignals(False)
            self._finish_edit(lambda: self.page.setCurrentIndex(index))
        else:
            self._show_page(index)

    def _navigate(self, offset):
        self.page.setCurrentIndex(max(0, min(self.page.count()-1, self.page.currentIndex()+offset)))

    def _rect(self, obj):
        return QRectF(*text_bounds(self.edits.get(obj.key, obj.style), obj.x, obj.y, self._page_boxes[obj.page]))

    def _hit_text(self, point):
        if self._busy or not hasattr(self,"_page_boxes"):
            return None
        matches = [obj for obj in self.objects if obj.page == self._displayed_page
                   and self._rect(obj).adjusted(-3,-3,3,3).contains(point)]
        return min(matches,key=lambda obj:self._rect(obj).width()*self._rect(obj).height()) if matches else None

    def _double_clicked(self, point):
        if self._busy:
            return
        obj = self._hit_text(point)
        if obj is None:
            self.status.setText(L("这里未选中可编辑文字，请双击文字本身；转曲或复杂结构暂不支持。",
                                  "No editable text selected here. Double-click the text itself; outlines and complex structures are unsupported."))
            return
        self._start_edit(obj, point)

    def _list_selected(self, index):
        if index >= 0 and not self._busy:
            self._start_edit(self.items.item(index).data(Qt.ItemDataRole.UserRole))

    def _start_edit(self, obj, point=None):
        if self._busy:
            return
        if self._active_item is not None:
            if self._active_object.key != obj.key:
                self._finish_edit(lambda: self._start_edit(obj, point))
            return
        self._render(suppressed=(obj.key,), after=lambda: self._activate(obj, point))

    def _activate(self, obj, point):
        self._active_object = obj
        style = self.edits.get(obj.key, obj.style)
        item = EditableLabel(self.preview._page_item)
        document = make_document(style)
        document.setParent(item)
        item.setDocument(document)
        item.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        self._active_item = self.preview.active_label = item
        self._loading_fields = True
        self.angle.setValue(style.angle)
        self._loading_fields = False
        self._position_item()
        item.document().contentsChanged.connect(self._changed)
        item.cursor_changed.connect(self._sync_format)
        item.finish_requested.connect(self._apply)
        cursor = item.textCursor()
        if point is not None:
            local = item.mapFromParent(point)
            position = item.document().documentLayout().hitTest(local, Qt.HitTestAccuracy.FuzzyHit)
            cursor.setPosition(max(0, position))
            cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        else:
            cursor.select(QTextCursor.SelectionType.Document)
        item.setTextCursor(cursor)
        item.setFocus()
        self._draft = False
        self._set_busy(False)
        self._sync_format()
        self.status.setText(L("正在编辑：选中部分字符可修改局部样式；空选区时修改整段。Enter 或“应用”结束本段。",
                             "Editing: select characters for local styles; no selection formats the whole label. Enter or Apply finishes this label."))

    def _position_item(self):
        if self._active_item is None:
            return
        _, _, ascent = document_metrics(self._active_item.document())
        obj = self._active_object
        box = self._page_boxes[obj.page]
        self._active_item.setTransformOriginPoint(0, ascent)
        self._active_item.setPos(obj.x-box[0], box[3]-obj.y-ascent)
        self._active_item.setRotation(-self.angle.value())

    def _changed(self):
        self._draft = True
        self._position_item()

    def _rotate(self, value):
        if not self._loading_fields and self._active_item is not None:
            self._draft = True
            self._position_item()

    def _sync_format(self):
        if self._active_item is None:
            return
        cursor = self._active_item.textCursor()
        fmt = cursor.charFormat()
        self._loading_fields = True
        self.family.setCurrentText((fmt.fontFamilies() or [fmt.font().family()])[0])
        self.size.setValue(fmt.fontPointSize() or 12)
        self.color.setText(fmt.foreground().color().name())
        self.bold.setChecked(fmt.fontWeight() >= QFont.Weight.Bold)
        self.italic.setChecked(fmt.fontItalic())
        count = len(cursor.selectedText())
        self.range_label.setText(L(f"已选 {count} 个字符（仅对选区应用）" if count else "未选字符：对整段应用",
                                  f"{count} characters selected (selection only)" if count else "No selection: apply to whole label"))
        self._loading_fields = False

    def _format(self, kind, value):
        if self._loading_fields or self._active_item is None or self._busy:
            return
        fmt = QTextCharFormat()
        if kind == "family":
            fmt.setFontFamilies([value])
        elif kind == "size":
            fmt.setFontPointSize(value)
        elif kind == "bold":
            fmt.setFontWeight(QFont.Weight.Bold if value else QFont.Weight.Normal)
        elif kind == "italic":
            fmt.setFontItalic(value)
        elif kind == "color":
            if not QColor(value).isValid():
                return
            fmt.setForeground(QColor(value))
        cursor = self._active_item.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.SelectionType.Document)
        cursor.mergeCharFormat(fmt)
        self._active_item.setTextCursor(cursor)
        self._sync_format()

    def _pick_color(self):
        color = QColorDialog.getColor(QColor(self.color.text()), self)
        if color.isValid():
            self.color.setText(color.name())
            self._format("color",color.name())

    def _color_edited(self):
        if QColor(self.color.text()).isValid():
            self._format("color",self.color.text())
        else:
            self.status.setText(L("颜色无效，请输入 #RRGGBB 色值或点击选色。",
                                  "Invalid color. Enter #RRGGBB or use Color."))

    def _release_preview(self, path):
        # Retired PDFs may still have an in-flight render; delete only after
        # the preview signals that all readers have closed them.
        if Path(path) != self.base:
            Path(path).unlink(missing_ok=True)

    def _detach(self):
        if self._active_item is not None:
            item = self._active_item
            self.preview.scene().removeItem(item)
            item.setParentItem(None)
            item.deleteLater()
        self._active_item = self.preview.active_label = self._active_object = None
        self._draft = False

    def _finish_edit(self, after=None):
        if self._busy:
            return
        if self._active_item is None:
            if after:
                after()
            return
        obj = self._active_object
        try:
            style = read_style(self._active_item.document(), self.angle.value())
            if style not in self.stamps:
                path = self.folder/f"stamp-{len(self.stamps)}.pdf"
                self.stamps[style] = path, make_stamp(path, style)
        except Exception as error:
            QMessageBox.warning(self, L("无法保存此文字", "Cannot Save This Text"), str(error))
            return
        if self._draft and style != self.edits.get(obj.key, obj.style):
            self.undo_states.append(self.edits.copy())
            del self.undo_states[:-50]
            self.redo_states.clear()
            self.edits[obj.key] = style
        self._detach()
        self._render(after=after)

    def _apply(self):
        self._finish_edit()

    def _history(self, redo):
        if self._busy:
            return
        if self._active_item is not None:
            doc = self._active_item.document()
            if (doc.isRedoAvailable() if redo else doc.isUndoAvailable()):
                doc.redo() if redo else doc.undo()
                self._sync_format()
                return
            self._finish_edit(lambda: self._history(redo))
            return
        source, dest = (self.redo_states, self.undo_states) if redo else (self.undo_states, self.redo_states)
        if source:
            dest.append(self.edits.copy())
            self.edits = source.pop()
            self._render()

    def _render(self, suppressed=(), after=None):
        self._set_busy(True)
        self._generation += 1
        target = self.folder/f"edited-{self._generation}.pdf"
        edits = self.edits.copy()
        stamps = {key: self.stamps[value] for key, value in edits.items()}
        self._runner.submit(lambda cancel: write_edits(self.base, target, self.objects, edits, stamps, suppressed),
                            lambda result, error, cancelled: self._rendered(target, error, cancelled, after))

    def _rendered(self, target, error, cancelled, after):
        self._set_busy(False)
        if error or cancelled:
            self.status.setText(str(error or "Cancelled"))
            self.save.setEnabled(False)
            return
        self.preview.load_pdf(target, self._generation, reset_view=False, page_index=self._displayed_page)
        self.current = target
        self.items.blockSignals(True)
        for index in range(self.items.count()):
            item = self.items.item(index)
            obj = item.data(Qt.ItemDataRole.UserRole)
            item.setText(self.edits.get(obj.key, obj.style).text)
        self.items.blockSignals(False)
        self.status.setText(L("修改已应用；可双击其他文字继续编辑。原文件未修改。",
                             "Changes applied. Double-click another label to continue. Original unchanged."))
        if after:
            after()

    def _save(self):
        if self._busy or not hasattr(self, "current"):
            return
        if self._active_item is not None:
            self._finish_edit(self._save)
            return
        if self._signature() != self.source_signature:
            if QMessageBox.question(self, L("原文件已更新", "Source Changed"),
                    L("外部程序已更新原文件，是否仍将当前快照另存为？",
                      "The source changed externally. Save this snapshot separately?")) != QMessageBox.StandardButton.Yes:
                return
        filename, selected = QFileDialog.getSaveFileName(self, L("另存为", "Save As"),
            str(self.source.with_name(self.source.stem+"-edited.eps")),
            "EPS (*.eps);;PostScript (*.ps);;PDF (*.pdf)")
        if not filename:
            return
        suffix = ".eps" if selected.startswith("EPS") else (".ps" if selected.startswith("PostScript") else ".pdf")
        target = Path(filename).with_suffix(suffix).resolve()
        if target == self.source or (target.exists() and self.source.exists() and target.samefile(self.source)):
            QMessageBox.warning(self, L("保留原文件", "Preserve Original"),
                                L("请选择其他文件名，不能覆盖原文件。", "Choose another filename; the original cannot be overwritten."))
            return
        if target.exists() and QMessageBox.question(self, L("覆盖文件？", "Replace File?"), str(target)) != QMessageBox.StandardButton.Yes:
            return
        self._set_busy(True)
        self._saving_page = self.page.currentIndex() if suffix == ".eps" else None
        current, count, page = self.current, self.page.count(), self.page.currentIndex()+1
        self._runner.submit(lambda cancel: self.renderer.export_document(current, target, TransformSnapshot(),
                            count, page, cancel_event=cancel, vector_text=True), self._saved)

    def _saved(self, output, error, cancelled):
        self._set_busy(False)
        if error or cancelled:
            self.status.setText(str(error or "Cancelled"))
            QMessageBox.warning(self, L("保存失败", "Save Failed"), self.status.text())
            return
        if self._saving_page is None:
            self._saved_edits = self.edits.copy()
        else:
            self._saved_edits = {key: value for key, value in self._saved_edits.items() if key[0] != self._saving_page}
            self._saved_edits.update({key: value for key, value in self.edits.items() if key[0] == self._saving_page})
        self.status.setText(L("已保存：", "Saved: ")+str(output))

    def reject(self):
        if self._busy:
            self._runner.cancel_all()
            self.status.setText(L("正在取消，请稍后关闭。", "Cancelling; please close again shortly."))
            return
        if self.edits != self._saved_edits or self._draft:
            if QMessageBox.question(self, L("未保存的文字修改", "Unsaved Text Changes"),
                    L("关闭并放弃尚未保存的文字修改？", "Close and discard unsaved text changes?"),
                    QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Discard:
                return
        if not self._runner.shutdown():
            return
        self._detach()
        if not self.preview.close():
            return
        self._temp.cleanup()
        super().reject()
