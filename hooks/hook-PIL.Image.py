"""Only in-memory channel math is used; Qt handles image file codecs."""

hiddenimports = []
excludedimports = [
    "numpy",  # Not used by our Pillow channel operations; avoid ambient installs.
    "PIL.AvifImagePlugin", "PIL._avif", "PIL.WebPImagePlugin", "PIL._webp",
    "PIL.ImageTk", "PIL._imagingtk", "PIL.ImageFont", "PIL._imagingft",
]
