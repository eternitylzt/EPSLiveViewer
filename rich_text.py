"""One shared rich-text layout for editable scene labels and vector export."""
import math
from PyQt6.QtCore import QMarginsF, QSizeF, QPointF
from PyQt6.QtGui import (QColor, QFont, QImage, QTextDocument, QTextCursor,
                        QTextCharFormat, QTextOption, QRawFont, QPageLayout,
                        QPageSize, QPainter, QPdfWriter)
from text_objects import TextRun, TextStyle


def char_format(run):
    fmt = QTextCharFormat()
    fmt.setFontFamilies([run.family])
    fmt.setFontPointSize(run.size)
    fmt.setFontWeight(QFont.Weight.Bold if run.bold else QFont.Weight.Normal)
    fmt.setFontItalic(run.italic)
    fmt.setForeground(QColor(run.color))
    return fmt


def configure_document(doc):
    device = QImage(1,1,QImage.Format.Format_RGB32)
    device.setDotsPerMeterX(2835);device.setDotsPerMeterY(2835)
    doc._elv_device = device  # keep layout's paint device alive
    doc.documentLayout().setPaintDevice(device)
    doc.setDocumentMargin(0)
    options = QTextOption()
    options.setWrapMode(QTextOption.WrapMode.NoWrap)
    options.setUseDesignMetrics(True)
    doc.setDefaultTextOption(options)
    doc.setTextWidth(-1)


def make_document(style):
    doc = QTextDocument()
    doc.setUndoRedoEnabled(False)
    configure_document(doc)
    cursor = QTextCursor(doc)
    for run in style.runs or (TextRun(style.text,style.family,style.size,style.color,style.bold,style.italic),):
        cursor.insertText(run.text,char_format(run))
    doc.setUndoRedoEnabled(True)
    return doc


def document_metrics(doc):
    doc.adjustSize()
    # adjustSize may choose a wrap width; these labels are always single-line.
    doc.setTextWidth(-1)
    size = doc.size()
    line = doc.firstBlock().layout().lineAt(0)
    return max(1.,size.width()),max(1.,size.height()),line.ascent() if line.isValid() else size.height()


def read_style(doc, angle):
    runs = []
    block = doc.firstBlock()
    if doc.blockCount()!=1:
        raise ValueError("Please use a single line for each text object")
    it = block.begin()
    while not it.atEnd():
        fragment = it.fragment()
        if fragment.isValid():
            fmt = fragment.charFormat()
            font = fmt.font()
            family = (fmt.fontFamilies() or [font.family()])[0]
            runs.append(TextRun(fragment.text(),family,fmt.fontPointSize() or font.pointSizeF(),
                                fmt.foreground().color().name(),font.bold(),font.italic()))
        it += 1
    if not runs:
        raise ValueError("Text cannot be empty")
    first = runs[0]
    return TextStyle("".join(r.text for r in runs),first.family,first.size,first.color,
                     first.bold,first.italic,angle,tuple(runs))


def paint_stamp(path,style):
    if "".join(run.text for run in style.runs)!=style.text:
        raise ValueError("Text spans do not match the label")
    for run in style.runs:
        if not 1<=run.size<=500 or not QColor(run.color).isValid():
            raise ValueError("Invalid text style")
        font = char_format(run).font()
        raw = QRawFont.fromFont(font)
        missing = "".join(dict.fromkeys(
            c for c in run.text if not c.isspace() and not raw.supportsCharacter(ord(c))
        ))
        if missing:
            raise ValueError("The selected font does not contain: "+missing)
    doc = make_document(style)
    width,height,ascent = document_metrics(doc)
    margin = max(run.size for run in style.runs)*2+20
    page_width,page_height = math.ceil(width+margin*2),math.ceil(height+margin*2)
    writer = QPdfWriter(str(path))
    writer.setResolution(72)
    writer.setPageLayout(QPageLayout(QPageSize(QSizeF(page_width,page_height),QPageSize.Unit.Point,
                                              "Text",QPageSize.SizeMatchPolicy.ExactMatch),
                                    QPageLayout.Orientation.Portrait,QMarginsF(0,0,0,0)))
    painter = QPainter(writer)
    if not painter.isActive():
        raise ValueError("Could not create embedded text")
    painter.translate(QPointF(margin,page_height-margin-ascent))
    doc.drawContents(painter)
    painter.end()
    return margin
