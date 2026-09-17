"""Conservative editing of independent PDF text runs produced by Ghostscript.

PostScript is never parsed here. Unsupported text, forms, clipping and encodings
remain untouched. Replacement glyphs are embedded by Qt, not painted over a box.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QMarginsF, QPointF, QSizeF
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QFontMetricsF, QPageLayout, QPageSize, QPainter, QPdfWriter, QRawFont
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, ContentStream, DecodedStreamObject, DictionaryObject, FloatObject, NameObject, TextStringObject, NumberObject

IDENTITY = (1., 0., 0., 1., 0., 0.)


def compose(a, b):
    """PDF row-vector affine composition (apply a, then b)."""
    return (a[0]*b[0]+a[1]*b[2], a[0]*b[1]+a[1]*b[3],
            a[2]*b[0]+a[3]*b[2], a[2]*b[1]+a[3]*b[3],
            a[4]*b[0]+a[5]*b[2]+b[4], a[4]*b[1]+a[5]*b[3]+b[5])


def inverse(m):
    a, b, c, d, e, f = m
    det = a*d-b*c
    if abs(det) < 1e-10:
        raise ValueError("Singular text transform")
    return (d/det, -b/det, -c/det, a/det, (c*f-d*e)/det, (b*e-a*f)/det)


@dataclass(frozen=True)
class TextRun:
    text: str
    family: str
    size: float
    color: str
    bold: bool = False
    italic: bool = False


@dataclass(frozen=True)
class TextStyle:
    text: str
    family: str
    size: float
    color: str
    bold: bool = False
    italic: bool = False
    angle: float = 0.0  # counterclockwise in page coordinates
    runs: tuple[TextRun, ...] = ()


@dataclass(frozen=True)
class TextObject:
    page: int
    start: int
    end: int
    show: int
    x: float
    y: float
    cm: tuple
    bounds: tuple
    style: TextStyle
    form: bool = False

    @property
    def key(self):
        return self.page, self.start


def _decode(value, font):
    # pypdf 6 changed its internal font helper; keep both supported variants.
    try:
        from pypdf._cmap import get_encoding
        encoding, mapping = get_encoding(font)
    except ImportError:
        from pypdf._cmap import build_char_map_from_dict
        _, _, encoding, mapping = build_char_map_from_dict(200, font)
    raw = value.original_bytes if hasattr(value, "original_bytes") else bytes(value)
    if isinstance(encoding, str):
        chars = raw.decode(encoding, errors="strict")
    else:
        chars = "".join(encoding[c] for c in raw)
    text = "".join(mapping.get(c, c) for c in chars)
    if any(ord(c) < 32 or c == "\ufffd" or 0xE000 <= ord(c) <= 0xF8FF for c in text):
        raise ValueError("Unsupported character encoding")
    return text


def discover_text(path, cancel=None):
    """List text shows with explicit, independent line positioning.

    No OCR or inference from outlines. Text inside XObject forms is deliberately
    excluded: editing a shared form could change several occurrences at once.
    """
    result = []
    reader = PdfReader(path)
    try:
        for page_number, page in enumerate(reader.pages):
            if float(page.get("/UserUnit", 1)) != 1:
                continue
            resources = page.get("/Resources", {})
            fonts = resources.get("/Font", {})
            stream = page.get_contents()
            if stream is None:
                continue
            state = dict(cm=IDENTITY, color="#000000", safe=True, font=None, size=12.,
                         spacing=0., word=0., scale=100., rise=0., mode=0)
            stack, block = [], None
            for index, (args, op) in enumerate(stream.operations):
                if cancel is not None and cancel.is_set():
                    raise InterruptedError("Cancelled")
                if op == b"q":
                    stack.append(state.copy())
                elif op == b"Q":
                    state = stack.pop() if stack else dict(state, safe=False)
                elif op == b"cm":
                    state["cm"] = compose(tuple(map(float, args)), state["cm"])
                elif op == b"gs":
                    gs = resources.get("/ExtGState", {})[args[0]].get_object()
                    # Ghostscript commonly emits an OPM-only state. These
                    # opaque, non-font states are also inherited by the Form.
                    allowed = {"/Type", "/OPM", "/OP", "/op", "/LW", "/LC", "/LJ", "/ML", "/D", "/RI", "/FL", "/SA"}
                    if set(gs) - allowed:
                        state["safe"] = False
                elif op in (b"W", b"W*", b"cs", b"sc", b"scn"):
                    state["safe"] = False
                elif op in (b"g", b"rg", b"k"):
                    v = [float(a) for a in args]
                    c = QColor.fromRgbF(*v) if op == b"rg" else (
                        QColor.fromCmykF(*v) if op == b"k" else QColor.fromRgbF(v[0], v[0], v[0]))
                    state["color"] = c.name()
                elif op == b"Tf":
                    state["font"], state["size"] = str(args[0]), float(args[1])
                elif op in (b"Tc", b"Tw", b"Tz", b"Ts", b"Tr"):
                    state[{b"Tc": "spacing", b"Tw": "word", b"Tz": "scale", b"Ts": "rise", b"Tr": "mode"}[op]] = float(args[0])
                elif op == b"Do" and block is None and state["safe"]:
                    form = resources.get("/XObject", {})[args[0]].get_object()
                    meta = form.get("/ELVEditableText")
                    if form.get("/Subtype") == "/Form" and meta is not None:
                        try:
                            result.append(_own_form(page_number,page,index,form,meta,state["cm"]))
                        except (ValueError, KeyError, TypeError, OverflowError):
                            pass
                if op == b"BT":
                    block = dict(start=index, tm=IDENTITY, positioned=False, shows=[], bad=False)
                elif block is not None:
                    if op == b"Tm":
                        block["tm"] = tuple(map(float, args))
                        block["positioned"] = True
                    elif op in (b"Td", b"TD"):
                        block["tm"] = compose((1,0,0,1,float(args[0]),float(args[1])), block["tm"])
                        block["positioned"] = True
                    elif op in (b"Tj", b"TJ"):
                        block["shows"].append((index, args, op, block["tm"], state.copy(), block["positioned"]))
                        block["positioned"] = False
                    elif op == b"ET":
                        # Td/TD use the text *line* matrix, not the advance
                        # left by a preceding show. Replacing one positioned
                        # fragment therefore cannot move its neighbours.
                        if block["shows"] and all(show[5] for show in block["shows"]) and not block["bad"]:
                            for show in block["shows"]:
                                fragment = dict(block,shows=[show[:5]],
                                                start=show[0] if len(block["shows"])>1 else block["start"])
                                try:
                                    obj = _object(page_number, page, fragment, index, fonts)
                                    if obj.style.text.strip():
                                        result.append(obj)
                                except (ValueError, KeyError, TypeError, UnicodeError, AttributeError, OverflowError):
                                    pass
                        block = None
                        if state["mode"] >= 4:
                            state["safe"] = False
                    elif op not in (b"Tf", b"Tc", b"Tw", b"Tz", b"Ts", b"Tr", b"TL"):
                        block["bad"] = True
            if len(result) > 10000:
                raise ValueError("Too many text objects for lightweight editing")
    finally:
        reader.close()
    return result


def _own_form(number,page,index,form,meta,cm):
    if meta.get("/Version") not in (1,2) or "/Matrix" in form:
        raise ValueError("Unknown text form")
    size, margin = float(meta["/Size"]), float(meta["/Margin"])
    a,b,c,d,e,f = cm
    scale = math.hypot(a,b)
    if (scale < 1e-8 or abs(math.hypot(c,d)-scale)>scale*.005
            or abs(a*c+b*d)>scale*scale*.005 or a*d-b*c<=0):
        raise ValueError("Unsupported form transform")
    x,y = margin*a+margin*c+e, margin*b+margin*d+f
    style = TextStyle(str(meta["/Text"]),str(meta["/Family"]),size*scale,str(meta["/Color"]),
                      bool(meta.get("/Bold")),bool(meta.get("/Italic")),math.degrees(math.atan2(b,a)))
    if meta.get("/Runs"):
        from dataclasses import replace
        runs = tuple(TextRun(str(run["/Text"]),str(run["/Family"]),float(run["/Size"])*scale,
                             str(run["/Color"]),bool(run.get("/Bold")),bool(run.get("/Italic")))
                     for run in meta["/Runs"])
        if ("".join(run.text for run in runs) != style.text
                or any(not 1<=run.size<=500 or not QColor(run.color).isValid() for run in runs)):
            raise ValueError("Invalid rich text metadata")
        style = replace(style,runs=runs)
    if not 1 <= style.size <= 500 or not QColor(style.color).isValid() or len(style.text)>2000:
        raise ValueError("Invalid text form")
    bounds = _bounds(page,style,x,y)
    return TextObject(number,index,index,index,x,y,cm,bounds,style,True)


def _object(number, page, block, end, fonts):
    show, args, op, tm, state = block["shows"][0]
    font = fonts[state["font"]].get_object()
    subtype = font.get("/Subtype")
    supported = subtype in ("/Type1", "/TrueType") or (
        subtype == "/Type0" and str(font.get("/Encoding")) == "/Identity-H"
        and font.get("/ToUnicode") is not None)
    if (not supported or not state["safe"]
            or state["spacing"] or state["word"] or state["rise"]
            or state["scale"] != 100 or state["mode"] != 0):
        raise ValueError("Unsupported text state")
    chunks = args[0] if op == b"TJ" else [args[0]]
    text = "".join(_decode(chunk, font) for chunk in chunks if isinstance(chunk, (str, bytes)))
    effective = compose(tm, state["cm"])
    a, b, c, d, x, y = effective
    sx, sy = math.hypot(a, b), math.hypot(c, d)
    if sx < 1e-8 or abs(sx-sy) > sx*.005 or abs(a*c+b*d) > sx*sy*.005 or a*d-b*c <= 0:
        raise ValueError("Skewed or mirrored text")
    size = state["size"] * sy
    if not 1 <= size <= 500:
        raise ValueError("Unsupported text size")
    name = str(font.get("/BaseFont", "/Helvetica")).split("+")[-1].lstrip("/")
    family = "Times New Roman" if "Times" in name else ("Courier New" if "Courier" in name else "Arial")
    normalized = name.lower().replace(" ", "").replace("-", "")
    families = QFontDatabase.families()
    matches = [item for item in families if normalized.startswith(item.lower().replace(" ","").replace("-",""))]
    if matches:
        family = max(matches, key=len)
    elif any("\u3400" <= char <= "\u9fff" for char in text):
        family = next((item for item in ("Microsoft YaHei", "SimSun", "PingFang SC", "Noto Sans CJK SC")
                       if item in families), family)
    style = TextStyle(text, family, size, state["color"], "Bold" in name,
                      "Italic" in name or "Oblique" in name, math.degrees(math.atan2(b, a)))
    return TextObject(number, block["start"], end, show, x, y, state["cm"],
                      _bounds(page,style,x,y), style)


def _bounds(page,style,x,y):
    return text_bounds(style,x,y,page.cropbox)


def text_bounds(style,x,y,cropbox):
    if style.runs:
        from rich_text import make_document, document_metrics
        doc = make_document(style)
        width, height, ascent = document_metrics(doc)
        descent = height-ascent
        size = ascent
        text = style.text
    else:
        descent = style.size*.25
        width = None
    size, text = style.size, style.text
    rich_width = width
    width = max(size*.4, len(text)*size*.55)
    qtfont = QFont(style.family)
    qtfont.setPointSizeF(size)
    qtfont.setBold(style.bold)
    qtfont.setItalic(style.italic)
    # Metrics at 72 dpi, independent of the user's screen scaling.
    from PyQt6.QtGui import QImage
    device = QImage(1, 1, QImage.Format.Format_RGB32)
    device.setDotsPerMeterX(2835)
    device.setDotsPerMeterY(2835)
    width = max(width*.25, QFontMetricsF(qtfont, device).horizontalAdvance(text))
    if rich_width is not None:
        width, size = rich_width, ascent
    angle = math.radians(style.angle)
    points = [(x+u*math.cos(angle)-v*math.sin(angle), y+u*math.sin(angle)+v*math.cos(angle))
              for u, v in ((0,-descent),(width,-descent),(width,size),(0,size))]
    left, bottom = min(p[0] for p in points), min(p[1] for p in points)
    right, top = max(p[0] for p in points), max(p[1] for p in points)
    box = cropbox
    return (left-float(box[0]), float(box[3])-top, right-left, top-bottom)


def make_stamp(path, style):
    """Create one embedded-font vector label; fail on missing glyphs."""
    if not style.text or "\n" in style.text or len(style.text) > 2000:
        raise ValueError("Use 1–2000 characters on a single line")
    if style.runs:
        from rich_text import paint_stamp
        return paint_stamp(path,style)
    if not 1 <= style.size <= 500 or not QColor(style.color).isValid():
        raise ValueError("Invalid font size or color")
    font = QFont(style.family)
    font.setPointSizeF(style.size)
    font.setBold(style.bold)
    font.setItalic(style.italic)
    raw = QRawFont.fromFont(font)
    # Space and other layout whitespace do not require an outline glyph.
    missing = "".join(dict.fromkeys(
        c for c in style.text if not c.isspace() and not raw.supportsCharacter(ord(c))
    ))
    if missing:
        raise ValueError("The selected font does not contain: " + missing)
    from PyQt6.QtGui import QImage
    device = QImage(1,1,QImage.Format.Format_RGB32)
    device.setDotsPerMeterX(2835)
    device.setDotsPerMeterY(2835)
    metrics = QFontMetricsF(font, device)
    margin = style.size * 2 + 20
    width = math.ceil(metrics.horizontalAdvance(style.text) + margin*2)
    height = math.ceil(metrics.height() + margin*2)
    writer = QPdfWriter(str(path))
    writer.setResolution(72)
    writer.setPageLayout(QPageLayout(QPageSize(QSizeF(width, height), QPageSize.Unit.Point),
                                   QPageLayout.Orientation.Portrait, QMarginsF(0,0,0,0)))
    painter = QPainter(writer)
    if not painter.isActive():
        raise ValueError("Could not create embedded text")
    painter.setFont(font)
    painter.setPen(QColor(style.color))
    painter.drawText(QPointF(margin, height-margin), style.text)
    painter.end()
    return margin


def write_edits(source, target, objects, edits, stamps, suppressed=()):
    """Replace original show operands with an empty show; insert a vector Form.

    The original BT/ET state commands remain, preserving inherited font state.
    A supported block has only one show, so no later text depends on its advance.
    """
    reader = PdfReader(source)
    writer = PdfWriter(clone_from=reader)
    stamp_readers = []
    try:
        by_page = {}
        for obj in objects:
            if obj.key in edits or obj.key in suppressed:
                by_page.setdefault(obj.page, []).append(obj)
        for number, runs in by_page.items():
            page = writer.pages[number]
            resources = copy.copy(page["/Resources"].get_object())
            xobjects = copy.copy(resources.get("/XObject", DictionaryObject()).get_object())
            resources[NameObject("/XObject")] = xobjects
            page[NameObject("/Resources")] = resources
            replacements, additions = {}, {}
            for index, obj in enumerate(runs):
                if obj.key in suppressed:
                    replacements[obj.show] = ([], b"q") if obj.form else ([ArrayObject()], b"TJ")
                    if obj.form:
                        additions[obj.end] = [([],b"Q")]
                    continue
                style = edits[obj.key]
                stamp_path, margin = stamps[obj.key]
                stamp_reader = PdfReader(stamp_path)
                stamp_readers.append(stamp_reader)
                stamp = stamp_reader.pages[0]
                form = DecodedStreamObject()
                form.set_data(stamp.get_contents().get_data())
                form.update({NameObject("/Type"):NameObject("/XObject"),
                             NameObject("/Subtype"):NameObject("/Form"),
                             NameObject("/BBox"):ArrayObject([FloatObject(v) for v in stamp.mediabox]),
                             NameObject("/Resources"):stamp["/Resources"].clone(writer)})
                # This describes an actual embedded-font Form, not a sidecar
                # or replacement for the saved graphics. It allows our own
                # exported PDF text to be edited again without guessing glyphs.
                form[NameObject("/ELVEditableText")] = DictionaryObject({
                    NameObject("/Version"):NumberObject(2),
                    NameObject("/Text"):TextStringObject(style.text),
                    NameObject("/Family"):TextStringObject(style.family),
                    NameObject("/Size"):FloatObject(style.size),
                    NameObject("/Color"):TextStringObject(style.color),
                    NameObject("/Bold"):NumberObject(int(style.bold)),
                    NameObject("/Italic"):NumberObject(int(style.italic)),
                    NameObject("/Margin"):FloatObject(margin)})
                if style.runs:
                    form["/ELVEditableText"][NameObject("/Runs")] = ArrayObject([
                        DictionaryObject({NameObject("/"+key):value for key,value in (
                            ("Text",TextStringObject(run.text)),("Family",TextStringObject(run.family)),
                            ("Size",FloatObject(run.size)),("Color",TextStringObject(run.color)),
                            ("Bold",NumberObject(int(run.bold))),("Italic",NumberObject(int(run.italic))))})
                        for run in style.runs])
                name = NameObject(f"/ELVText{index}")
                while name in xobjects:
                    name = NameObject(str(name)+"X")
                xobjects[name] = writer._add_object(form)
                angle = math.radians(style.angle)
                cs, sn = math.cos(angle), math.sin(angle)
                absolute = compose((1,0,0,1,-margin,-margin), (cs,sn,-sn,cs,obj.x,obj.y))
                relative = compose(absolute, inverse(obj.cm))
                replacements[obj.show] = ([], b"q") if obj.form else ([ArrayObject()], b"TJ")
                additions.setdefault(obj.end,[]).extend(
                    ([([], b"Q")] if obj.form else []) + [([], b"q"), ([FloatObject(v) for v in relative], b"cm"),
                                                        ([name], b"Do"), ([], b"Q")])
            stream = ContentStream(page.get_contents(), writer)
            operations = []
            for index, operation in enumerate(stream.operations):
                operations.append(replacements.get(index, operation))
                operations.extend(additions.get(index, []))
            stream.operations = operations
            page.replace_contents(stream)
            page.compress_content_streams()
        with open(target, "wb") as output:
            writer.write(output)
    finally:
        for item in stamp_readers:
            item.close()
        writer.close()
        reader.close()
