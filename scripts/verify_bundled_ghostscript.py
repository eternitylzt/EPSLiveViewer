"""Exercise the shipped interpreter without a system Ghostscript installation.

Run from source or through EPSLiveViewer --verify-ghostscript. The test owns
only temporary documents and settings; every interpreter process is bounded.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

if __package__ in (None, "") and not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import find_ghostscript
from eps_renderer import EpsRenderer, EpsRenderCancelledError, EpsRenderError
from ghostscript_runtime import bundled_ghostscript_path, ghostscript_environment
from image_transforms import ColorReplacement, TransformSnapshot


@contextmanager
def _environment(values):
    previous = {key: os.environ.get(key) for key in values}
    try:
        os.environ.update(values)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class _Deadline:
    def __init__(self, cancellation):
        self.cancellation = cancellation
        self.expires = time.monotonic() + 30

    def is_set(self):
        return self.timed_out() or bool(self.cancellation and self.cancellation.is_set())

    def timed_out(self):
        return time.monotonic() >= self.expires


class _BoundedRenderer(EpsRenderer):
    """Retain the actual subprocess path, adding only a verification deadline."""

    def __init__(self):
        super().__init__()
        self.devices_used = set()

    def _capture_ghostscript(self, command, cancel_event):
        self.devices_used.update(argument.split("=", 1)[1]
                                 for argument in command if argument.startswith("-sDEVICE="))
        deadline = _Deadline(cancel_event)
        try:
            return super()._capture_ghostscript(command, deadline)
        except EpsRenderCancelledError:
            if deadline.timed_out():
                raise TimeoutError("Bundled Ghostscript exceeded the 30-second process limit") from None
            raise


def _require(condition, message):
    if not condition:
        raise RuntimeError(message)


def _fixture(eps):
    header = "%!PS-Adobe-3.0 EPSF-3.0" if eps else "%!PS-Adobe-3.0"
    return (header + "\n%%BoundingBox: 0 0 216 144\n%%Pages: 2\n%%EndComments\n"
            "<< /PageSize [216 144] >> setpagedevice\n"
            "%%Page: 1 1\n"
            "0 setgray /Helvetica findfont 12 scalefont setfont\n"
            "12 120 moveto (Helvetica first page) show\n"
            "/Times-Roman findfont 12 scalefont setfont\n"
            "12 100 moveto (Times scientific text) show\n"
            "/Symbol findfont 14 scalefont setfont 12 80 moveto (abgD) show\n"
            "1 0 0 setrgbcolor 30 20 40 25 rectfill\n"
            "0 0.6 0 setrgbcolor 2 setlinewidth 110 20 moveto 180 60 lineto stroke\n"
            "showpage\n%%Page: 2 2\n"
            "0 setgray /Helvetica findfont 12 scalefont setfont\n"
            "12 120 moveto (Helvetica second page) show\n"
            "0 0 1 setrgbcolor 20 20 50 35 rectfill showpage\n%%EOF\n")


def verify() -> dict:
    """Return measured results or raise; a missing private runtime is an error."""
    from PyQt6.QtGui import QImage
    from PyQt6.QtWidgets import QApplication
    from pypdf import PdfReader

    executable = bundled_ghostscript_path()
    _require(executable is not None, "The application does not contain a Ghostscript runtime")
    application = QApplication.instance()
    if application is None:
        # Only this standalone check chooses an offscreen Qt platform.
        with _environment({"QT_QPA_PLATFORM": "offscreen"}):
            application = QApplication([])

    checks = []
    required_devices = {"pdfwrite", "pngalpha", "nullpage", "ps2write", "eps2write"}
    with tempfile.TemporaryDirectory(prefix="eps_bundled_gs_") as directory:
        root = Path(directory) / "中文 documents with spaces"
        root.mkdir()
        # Deliberately conflicting parent settings must not affect the private
        # interpreter. Nothing is written to the user's config or registry.
        with _environment({
            "PATH": "", "GSWIN64C": str(root / "missing.exe"),
            "GSWIN32C": str(root / "missing32.exe"),
            "GS_LIB": str(root / "missing resources"),
            "GS_FONTPATH": str(root / "missing fonts"),
            "GS_DLL": str(root / "missing.dll"),
            "GS_DEVICE": "not_a_device", "GS_OPTIONS": "-sDEVICE=not_a_device",
        }):
            _require(find_ghostscript() == executable, "System discovery displaced the bundled runtime")
            environment = ghostscript_environment(executable)
            _require(environment is not None, "The bundled runtime did not receive its private environment")
            process_options = dict(capture_output=True, text=True, encoding="utf-8", errors="replace",
                                   timeout=30, env=environment,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            version = subprocess.run([str(executable), "-version"], **process_options)
            _require(version.returncode == 0, "Bundled Ghostscript cannot start: " + version.stderr)
            help_result = subprocess.run([str(executable), "-h"], **process_options)
            devices = set(help_result.stdout.split())
            _require(help_result.returncode == 0 and required_devices <= devices,
                     "The bundled interpreter is missing required output devices")
            checks.append("bundled discovery and polluted-environment isolation")

            resources = (
                "%rom%Resource/Font/NimbusSans-Regular",
                "%rom%Resource/Font/NimbusRoman-Regular",
                "%rom%Resource/Font/StandardSymbolsPS",
                "%rom%iccprofiles/default_rgb.icc",
                "%rom%iccprofiles/default_cmyk.icc",
                "%rom%iccprofiles/default_gray.icc",
            )
            resource_probe = " ".join(f"({path}) (r) file closefile" for path in resources)
            resource_result = subprocess.run(
                [str(executable), "-q", "-dSAFER", "-dNODISPLAY", "-dBATCH", "-c", resource_probe],
                **process_options,
            )
            _require(resource_result.returncode == 0,
                     "Required ROM fonts or ICC profiles are missing: " + resource_result.stderr)
            checks.append("embedded Helvetica/Times/Symbol substitutes and RGB/CMYK/gray ICC profiles")

            renderer = _BoundedRenderer()
            try:
                sources = []
                for suffix in (".eps", ".ps"):
                    source = root / ("多页 scientific figure" + suffix)
                    source.write_text(_fixture(suffix == ".eps"), encoding="ascii")
                    original = source.read_bytes()
                    sources.append(source)
                    output = root / ("preview" + suffix + ".pdf")
                    renderer.export_pdf(source, output)
                    with PdfReader(output) as pdf:
                        _require(len(pdf.pages) == 2, "Multipage conversion lost pages")
                        text = pdf.pages[0].extract_text()
                        _require("Helvetica first page" in text and "Times scientific text" in text,
                                 "Standard-font text did not survive vector conversion")
                        _require(not pdf.pages[0].images, "Vector conversion unexpectedly rasterized the page")
                        _require(abs(float(pdf.pages[0].mediabox.width) - 216) < .1
                                 and abs(float(pdf.pages[0].mediabox.height) - 144) < .1,
                                 "Vector conversion changed the page canvas")
                    _require(renderer.page_count(source) == 2, "Page counting disagrees with the converted document")
                    _require(source.read_bytes() == original, "Conversion changed its source document")
                checks.append("multipage EPS/PS, standard fonts and vector PDF output")

                direct = renderer.render(sources[0], dpi=600, guard_dimensions=True)
                try:
                    image = QImage(str(direct.png_path))
                    _require((image.width(), image.height()) == (1800, 1200), "pngalpha produced incorrect 600 DPI dimensions")
                    _require(image.pixelColor(0, 0).alpha() == 0, "pngalpha lost transparent background")
                finally:
                    renderer.cache.release(direct.png_path)
                target = root / "600 DPI transparent.png"
                renderer.export_png(sources[0], target, 600, "transparent")
                image = QImage(str(target))
                _require((image.width(), image.height()) == (1800, 1200), "PNG export dimensions are incorrect")
                _require(image.pixelColor(0, 0).alpha() == 0, "PNG export lost transparent background")
                _require(abs(image.dotsPerMeterX() * .0254 - 600) < .1, "PNG export lost its resolution metadata")
                checks.append("nullpage dimension guard, pngalpha and transparent 600 DPI export")

                transforms = TransformSnapshot(
                    replacements=(ColorReplacement("#FF0000", "#0000FF", 0),),
                    page_rotations=((1, 90),),
                )
                for suffix, count in ((".eps", 1), (".ps", 2)):
                    target = root / ("rotated recolored" + suffix)
                    renderer.export_document(sources[0], target, transforms, 2, 1, vector_text=True)
                    converted = renderer.convert_to_pdf(target)
                    try:
                        with PdfReader(converted.pdf_path) as pdf:
                            _require(len(pdf.pages) == count, "PostScript export lost the requested pages")
                            _require(not pdf.pages[0].images, "PostScript export rasterized simple vector content")
                        image = renderer.render_page_image(converted.pdf_path, 72)
                        _require((image.width(), image.height()) == (144, 216), "Export did not preserve page rotation and canvas")
                        blue = red = 0
                        for y in range(image.height()):
                            for x in range(image.width()):
                                color = image.pixelColor(x, y)
                                if color.alpha() > 200 and color.green() < 40:
                                    blue += color.blue() > 200 and color.red() < 40
                                    red += color.red() > 200 and color.blue() < 40
                        _require(blue > 200 and red == 0, "Vector color replacement was not retained by PostScript export")
                    finally:
                        renderer.cache.release(converted.pdf_path)
                checks.append("rotated/recolored vector EPS and multipage PS round trips")

                destination = root / "existing.pdf"
                sentinel = b"Existing output must survive a failed conversion."
                destination.write_bytes(sentinel)
                broken = root / "broken.eps"
                broken.write_text("%!PS\nundefined_verification_operator\n", encoding="ascii")
                try:
                    renderer.export_pdf(broken, destination)
                except EpsRenderError:
                    pass
                else:
                    raise RuntimeError("Damaged PostScript unexpectedly converted successfully")
                _require(destination.read_bytes() == sentinel, "Failed conversion overwrote an existing output")
                checks.append("clear failure without overwriting existing output")

                looping = root / "cancel.ps"
                looping.write_text("%!PS\n{} loop\n", encoding="ascii")
                cancellation = threading.Event()
                timer = threading.Timer(.5, cancellation.set)
                timer.start()
                try:
                    try:
                        renderer.convert_to_pdf(looping, cancel_event=cancellation)
                    except EpsRenderCancelledError:
                        pass
                    else:
                        raise RuntimeError("A running interpreter ignored cancellation")
                finally:
                    timer.cancel()
                    timer.join(timeout=2)
                checks.append("cancellation of a running interpreter")
                _require(required_devices <= renderer.devices_used, "Not every required device was exercised")
            finally:
                renderer.cache.cleanup()
    # Keep our QApplication alive through all QImage/QtPdf operations.
    application.processEvents()
    return {"version": version.stdout.strip(), "devices": sorted(required_devices),
            "checks": checks, "executable": str(executable)}


if __name__ == "__main__":
    print(json.dumps(verify(), ensure_ascii=False, indent=2))
