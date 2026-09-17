"""Generate release icon formats from the shared vector drawing (build-time)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt6.QtWidgets import QApplication
from PIL import Image
from branding import logo_pixmap

if __name__ == "__main__":
    app = QApplication([])
    folder = Path(__file__).resolve().parents[1] / "resources"
    logo_pixmap(1024).save(str(folder / "logo.png"))
    image = Image.open(folder / "logo.png")
    image.save(folder / "icon.ico", sizes=[(n,n) for n in (16,24,32,48,64,128,256)])
    image.save(folder / "icon.icns")
