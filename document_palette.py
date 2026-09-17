"""Extract explicit document paint colors, with a labeled bitmap fallback."""
from collections import Counter
from PyQt6.QtGui import QColor, QImage
from pypdf import PdfReader
from pypdf.generic import ContentStream


def vector_palette(path, page_index=0):
    colors, visited = Counter(), set()
    reader = PdfReader(path)
    def scan(contents, resources):
        for operands, op in ContentStream(contents, reader).operations:
            if op in (b"rg", b"RG", b"g", b"G", b"k", b"K"):
                values = [max(0.,min(1.,float(v))) for v in operands]
                if op.lower() == b"g":
                    color = QColor.fromRgbF(values[0],values[0],values[0])
                elif op.lower() == b"rg":
                    color = QColor.fromRgbF(*values)
                else:
                    color = QColor.fromCmykF(*values)
                colors[color.name().upper()] += 1
            elif op == b"Do":
                child = resources.get("/XObject", {})[operands[0]].get_object()
                if child.get("/Subtype") == "/Form" and id(child) not in visited:
                    visited.add(id(child))
                    scan(child,child.get("/Resources",resources))
    try:
        page = reader.pages[page_index]
        if page.get_contents() is not None:
            scan(page.get_contents(),page.get("/Resources", {}))
        return [color for color,count in colors.most_common(64)]
    finally:
        reader.close()


def sampled_palette(image):
    """Sample dominant visible colors, not an assertion about source operators."""
    from PIL import Image
    small = image.scaled(256,256).convertToFormat(QImage.Format.Format_RGBA8888)
    if small.isNull():
        return []
    pixels = Image.frombytes("RGBA",(small.width(),small.height()),
                              small.constBits().asstring(small.sizeInBytes()))
    colors = Counter()
    for count, (r,g,b,a) in pixels.getcolors(256*256) or []:
        if a > 240:
            colors[r,g,b] += count
    return ["#%02X%02X%02X"%rgb for rgb,count in colors.most_common(32)]
