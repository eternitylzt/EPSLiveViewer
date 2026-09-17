"""Keep initial windows inside the current screen's usable desktop area."""
from PyQt6.QtGui import QGuiApplication, QCursor


def fit_initial_window(widget, width=1200, height=800):
    screen = QGuiApplication.screenAt(QCursor.pos()) or widget.screen()
    if screen is None:
        widget.resize(width, height)
        return
    area = screen.availableGeometry()
    # Leave room for the native title bar, borders and taskbar.
    w, h = min(width, int(area.width()*.90)), min(height, int(area.height()*.86))
    widget.setMinimumSize(min(widget.minimumWidth(), w), min(widget.minimumHeight(), h))
    widget.resize(w, h)
    widget.move(area.x()+(area.width()-w)//2, area.y()+max(16,(area.height()-h)//2-16))
