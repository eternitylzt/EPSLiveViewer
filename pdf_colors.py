"""Recolor PDF paint operators while preserving paths, fonts, and page geometry.

Unsupported color spaces/effects are reported rather than silently miscolored.
PostScript interpretation remains Ghostscript's responsibility.
"""

import zlib

from PyQt6.QtGui import QColor, QImage
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, ContentStream, FloatObject, NameObject, NumberObject

from image_transforms import adjusted_color, apply_color_adjustments


class UnsupportedVectorColor(ValueError):
    pass


def recolor_pdf(source, target, transforms, background="transparent", background_color="#FFFFFF",
                cancel_event=None, paint_background=True):
    reader = PdfReader(source)
    if reader.is_encrypted and not reader.decrypt(""):
        raise ValueError("Password-protected PDF cannot be edited without its password")
    writer = PdfWriter(clone_from=reader)
    processed = set()
    form_spaces = {}

    def cancelled():
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("PDF color export cancelled")

    def resolve_space(space, resources):
        spaces = resources.get("/ColorSpace", {})
        if hasattr(spaces, "get_object"):
            spaces = spaces.get_object()
        if hasattr(space, "get_object"):
            space = space.get_object()
        if isinstance(space, str) and space in spaces:
            space = spaces[space].get_object()
        if isinstance(space, (list, ArrayObject)):
            if space[0] == "/ICCBased":
                # Use only a declared device alternate; calibrated colors with
                # no alternate need the normal rendering fallback.
                profile = space[1].get_object()
                space = profile.get("/Alternate", "/UnsupportedICC")
            else:
                raise UnsupportedVectorColor(str(space[0]))
        if space not in ("/DeviceRGB", "/DeviceGray", "/DeviceCMYK"):
            raise UnsupportedVectorColor(str(space))
        return space

    def rgb(values, space, resources):
        space = resolve_space(space, resources)
        v = [max(0.0, min(1.0, float(x))) for x in values]
        if space == "/DeviceGray" and len(v) == 1:
            return QColor.fromRgbF(v[0], v[0], v[0])
        if space == "/DeviceRGB" and len(v) == 3:
            return QColor.fromRgbF(*v)
        if space == "/DeviceCMYK" and len(v) == 4:
            return QColor.fromCmykF(*v)
        raise UnsupportedVectorColor("Invalid color operands")

    def mapped(color):
        c = adjusted_color(color, transforms.inverted, transforms.replacements)
        return [FloatObject(channel / 255) for channel in (c.red(), c.green(), c.blue())]

    def recolor_image(image, resources):
        if image.get("/ImageMask"):
            return  # Stencils use the recolored current paint color.
        if image.get("/Decode") is not None or image.get("/Mask") is not None:
            raise UnsupportedVectorColor("Image Decode/color-key mask")
        space = resolve_space(image.get("/ColorSpace"), resources)
        if space == "/DeviceCMYK":
            raise UnsupportedVectorColor("CMYK image")
        width, height = int(image["/Width"]), int(image["/Height"])
        if width * height > 64_000_000 or image.get("/BitsPerComponent") != 8:
            raise UnsupportedVectorColor("Image size/bit depth")
        data = image.get_data()
        filters = str(image.get("/Filter", ""))
        if "/DCTDecode" in filters or "/JPXDecode" in filters:
            pixels = QImage.fromData(data)
        else:
            channels = 3 if space == "/DeviceRGB" else 1
            if len(data) != width * height * channels:
                raise UnsupportedVectorColor("Image stream length")
            fmt = QImage.Format.Format_RGB888 if channels == 3 else QImage.Format.Format_Grayscale8
            pixels = QImage(data, width, height, width * channels, fmt).copy()
        if pixels.isNull():
            raise UnsupportedVectorColor("Image codec")
        pixels = apply_color_adjustments(pixels, transforms.inverted, transforms.replacements,
                                         cancel_event).convertToFormat(QImage.Format.Format_RGB888)
        raw = pixels.constBits().asstring(pixels.sizeInBytes())
        raw = b"".join(raw[y * pixels.bytesPerLine():y * pixels.bytesPerLine() + width * 3]
                       for y in range(height))
        image._data = zlib.compress(raw)
        if hasattr(image, "decoded_self"):
            image.decoded_self = None
        image[NameObject("/Filter")] = NameObject("/FlateDecode")
        image.pop("/DecodeParms", None)
        image[NameObject("/ColorSpace")] = NameObject("/DeviceRGB")
        image[NameObject("/BitsPerComponent")] = NumberObject(8)

    def transform_stream(contents, resources, initial=("/DeviceGray", "/DeviceGray")):
        if hasattr(resources, "get_object"):
            resources = resources.get_object()
        # Type 3 glyph programs may carry their own paint operators. Rendering
        # is safer than leaving explicitly colored glyphs partially unchanged.
        fonts = resources.get("/Font", {})
        if hasattr(fonts, "get_object"):
            fonts = fonts.get_object()
        if any(font.get_object().get("/Subtype") == "/Type3" for font in fonts.values()):
            raise UnsupportedVectorColor("Type 3 glyph programs")
        stream = ContentStream(contents, writer)
        stroke, fill = initial
        stack, output = [], []
        for operands, op in stream.operations:
            cancelled()
            if op == b"q":
                stack.append((stroke, fill))
            elif op == b"Q":
                if stack:
                    stroke, fill = stack.pop()
            elif op in (b"CS", b"cs"):
                space = operands[0]
                resolve_space(space, resources)
                if op == b"CS":
                    stroke = space
                else:
                    fill = space
                # Setting a PDF colorspace also sets its default color.
                base = resolve_space(space, resources)
                default = [0] * ({"/DeviceGray": 1, "/DeviceRGB": 3, "/DeviceCMYK": 4}[base])
                if base == "/DeviceCMYK":
                    default[-1] = 1
                operands, op = mapped(rgb(default, space, resources)), (b"RG" if op == b"CS" else b"rg")
            elif op in (b"G", b"g", b"RG", b"rg", b"K", b"k", b"SC", b"sc", b"SCN", b"scn"):
                is_stroke = op.isupper()
                direct = {b"G": "/DeviceGray", b"g": "/DeviceGray", b"RG": "/DeviceRGB",
                          b"rg": "/DeviceRGB", b"K": "/DeviceCMYK", b"k": "/DeviceCMYK"}.get(op)
                if direct:
                    if is_stroke:
                        stroke = direct
                    else:
                        fill = direct
                operands = mapped(rgb(operands, stroke if is_stroke else fill, resources))
                op = b"RG" if is_stroke else b"rg"
            elif op == b"Do":
                obj = resources.get("/XObject", {})[operands[0]].get_object()
                key = id(obj)
                if obj.get("/Subtype") == "/Form":
                    inherited = (str(stroke), str(fill))
                    if key in form_spaces and form_spaces[key] != inherited:
                        raise UnsupportedVectorColor("Shared form with varying inherited color spaces")
                    form_spaces[key] = inherited
                if key not in processed:
                    processed.add(key)
                    if obj.get("/Subtype") == "/Form":
                        child = transform_stream(obj, obj.get("/Resources", resources), (stroke, fill))
                        obj._data = child.get_data()
                        obj.pop("/Filter", None)
                        obj.pop("/DecodeParms", None)
                        if hasattr(obj, "decoded_self"):
                            obj.decoded_self = None
                    elif obj.get("/Subtype") == "/Image":
                        recolor_image(obj, resources)
                    else:
                        raise UnsupportedVectorColor("XObject subtype")
            elif op == b"gs":
                gs = resources.get("/ExtGState", {})[operands[0]].get_object()
                if any(key in gs for key in ("/TR", "/TR2")) or gs.get("/SMask", "/None") != "/None" or gs.get("/BM", "/Normal") not in ("/Normal", "/Compatible"):
                    raise UnsupportedVectorColor("Transparency/transfer effect")
            elif op in (b"sh", b"INLINE IMAGE"):
                raise UnsupportedVectorColor("Gradient/inline image")
            output.append((operands, op))
        stream.operations = output
        return stream

    try:
        for page_number, page in enumerate(writer.pages, 1):
            cancelled()
            if transforms.has_color_adjustments():
                if page.get("/Annots") is not None and page["/Annots"]:
                    raise UnsupportedVectorColor("Annotations")
                resources = page.get("/Resources", {})
                stream = transform_stream(page.get_contents(), resources)
                black = mapped(QColor("black"))
                prefix = [([], b"q")]
                # Materialize the page backdrop only if it actually changes.
                color = QColor(background_color if background == "custom" else "white")
                backdrop = mapped(color)
                if paint_background and (background != "transparent" or transforms.inverted):
                    rect = page.cropbox
                    prefix += [(backdrop, b"rg"), ([FloatObject(rect.left), FloatObject(rect.bottom),
                                FloatObject(rect.width), FloatObject(rect.height)], b"re"), ([], b"f")]
                prefix += [(black, b"rg"), (black, b"RG")]
                stream.operations = prefix + stream.operations + [([], b"Q")]
                page.replace_contents(stream)
                page.compress_content_streams()
            rotation = transforms.rotation_for(page_number)
            if rotation:
                page.rotate(rotation)
        writer.add_metadata({"/Producer": "EPS Live Viewer", "/EPSLiveViewerColorMode": "vector"})
        with open(target, "wb") as output:
            writer.write(output)
    finally:
        writer.close()
        reader.close()
