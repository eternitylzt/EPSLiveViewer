"""Non-destructive page transformation state and QImage color processing."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Iterable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage, QTransform


@dataclass(frozen=True)
class ColorReplacement:
    """Replace pixels near one RGB color with another while preserving alpha."""

    source: str
    target: str
    tolerance: int = 8

    def __post_init__(self) -> None:
        source = QColor(self.source)
        target = QColor(self.target)
        if not source.isValid() or not target.isValid():
            raise ValueError("Invalid replacement color")
        object.__setattr__(self, "source", source.name().upper())
        object.__setattr__(self, "target", target.name().upper())
        object.__setattr__(self, "tolerance", max(0, min(255, int(self.tolerance))))


@dataclass
class DocumentTransforms:
    """Session-only transforms for one source document.

    Color operations apply to the whole document. Rotation is stored per page
    because multi-page PostScript commonly mixes portrait and landscape plots.
    """

    inverted: bool = False
    replacements: tuple[ColorReplacement, ...] = ()
    page_rotations: dict[int, int] = field(default_factory=dict)

    def rotation_for(self, page_number: int) -> int:
        return self.page_rotations.get(max(1, int(page_number)), 0) % 360

    def rotate_page(self, page_number: int, degrees: int) -> int:
        page = max(1, int(page_number))
        rotation = (self.rotation_for(page) + int(degrees)) % 360
        if rotation:
            self.page_rotations[page] = rotation
        else:
            self.page_rotations.pop(page, None)
        return rotation

    def snapshot(self) -> "TransformSnapshot":
        return TransformSnapshot(
            self.inverted,
            tuple(self.replacements),
            tuple(sorted(self.page_rotations.items())),
        )


@dataclass(frozen=True)
class TransformSnapshot:
    inverted: bool = False
    replacements: tuple[ColorReplacement, ...] = ()
    page_rotations: tuple[tuple[int, int], ...] = ()

    def rotation_for(self, page_number: int) -> int:
        page = max(1, int(page_number))
        for stored_page, rotation in self.page_rotations:
            if stored_page == page:
                return rotation % 360
        return 0

    def has_color_adjustments(self) -> bool:
        return self.inverted or bool(self.replacements)


def apply_color_adjustments(
    source: QImage,
    inverted: bool = False,
    replacements: Iterable[ColorReplacement] = (),
    cancel_event: threading.Event | None = None,
) -> QImage:
    """Return a color-adjusted copy using the fixed invert-then-replace order."""
    mappings = tuple(replacements)
    if not inverted and not mappings:
        return QImage(source)

    image = source.convertToFormat(QImage.Format.Format_RGBA8888)
    if inverted:
        image.invertPixels(QImage.InvertMode.InvertRgb)
    if not mappings:
        return image

    prepared: list[tuple[int, int, int, int, int, int, int]] = []
    for mapping in mappings:
        src = QColor(mapping.source)
        dst = QColor(mapping.target)
        prepared.append(
            (
                src.red(),
                src.green(),
                src.blue(),
                dst.red(),
                dst.green(),
                dst.blue(),
                mapping.tolerance,
            )
        )

    bits = image.bits()
    bits.setsize(image.sizeInBytes())
    pixels = memoryview(bits).cast("B")
    stride = image.bytesPerLine()
    width_bytes = image.width() * 4
    for row in range(image.height()):
        if cancel_event is not None and cancel_event.is_set():
            break
        start = row * stride
        for offset in range(start, start + width_bytes, 4):
            if pixels[offset + 3] == 0:
                continue
            red, green, blue = pixels[offset], pixels[offset + 1], pixels[offset + 2]
            for sr, sg, sb, tr, tg, tb, tolerance in prepared:
                if (
                    abs(red - sr) <= tolerance
                    and abs(green - sg) <= tolerance
                    and abs(blue - sb) <= tolerance
                ):
                    pixels[offset] = tr
                    pixels[offset + 1] = tg
                    pixels[offset + 2] = tb
                    break
    return image


def adjusted_color(
    color: QColor,
    inverted: bool,
    replacements: Iterable[ColorReplacement],
) -> QColor:
    red, green, blue = color.red(), color.green(), color.blue()
    if inverted:
        red, green, blue = 255 - red, 255 - green, 255 - blue
    for mapping in replacements:
        source = QColor(mapping.source)
        if (
            abs(red - source.red()) <= mapping.tolerance
            and abs(green - source.green()) <= mapping.tolerance
            and abs(blue - source.blue()) <= mapping.tolerance
        ):
            target = QColor(mapping.target)
            red, green, blue = target.red(), target.green(), target.blue()
            break
    return QColor(red, green, blue, color.alpha())


def rotate_image(source: QImage, degrees: int) -> QImage:
    rotation = int(degrees) % 360
    if rotation == 0:
        return QImage(source)
    return source.transformed(
        QTransform().rotate(rotation),
        mode=Qt.TransformationMode.FastTransformation,
    )


def apply_page_transforms(
    source: QImage,
    transforms: TransformSnapshot,
    page_number: int,
    cancel_event: threading.Event | None = None,
) -> QImage:
    adjusted = apply_color_adjustments(
        source,
        transforms.inverted,
        transforms.replacements,
        cancel_event,
    )
    return rotate_image(adjusted, transforms.rotation_for(page_number))
