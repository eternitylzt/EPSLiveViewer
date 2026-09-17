"""Resolution-independent brand mark and lightweight toolbar line icons."""
import math
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap


def logo_pixmap(size=128):
    pixmap = QPixmap(size,size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size/128,size/128)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#132B45"))
    p.drawRoundedRect(QRectF(4,4,120,120),28,28)
    p.setPen(QPen(QColor("#A3B9CE"),3,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(28,29),QPointF(28,99))
    p.drawLine(QPointF(28,99),QPointF(102,99))
    path = QPainterPath(QPointF(29,78))
    path.cubicTo(40,78,40,42,52,42)
    path.cubicTo(66,42,64,88,78,88)
    path.cubicTo(87,88,92,38,104,31)
    p.setPen(QPen(QColor("#46DAC6"),5,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
    p.drawPath(path)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#FFFFFF"))
    p.drawEllipse(QPointF(104,31),4,4)
    p.end()
    return pixmap


def tool_icon(name, color):
    """Draw in logical coordinates at several sizes; no font-icon dependency."""
    icon = QIcon()
    for size in (24,32,48,64):
        pm = QPixmap(size,size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(size/24,size/24)
        p.setPen(QPen(color,1.7,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
        def line(x1,y1,x2,y2):
            p.drawLine(QPointF(x1,y1),QPointF(x2,y2))
        if name == "home":
            path=QPainterPath(QPointF(3,11));path.lineTo(12,3);path.lineTo(21,11)
            path.moveTo(6,9);path.lineTo(6,21);path.lineTo(10,21);path.lineTo(10,15)
            path.lineTo(14,15);path.lineTo(14,21);path.lineTo(18,21);path.lineTo(18,9)
            p.drawPath(path)
        elif name in ("zoom_in","zoom_out"):
            p.drawEllipse(QRectF(3,3,12,12))
            line(14,14,21,21)
            line(6,9,12,9)
            if name == "zoom_in": line(9,6,9,12)
        elif name in ("previous_file","next_file","previous_page","next_page"):
            angle = {"previous_file":180,"next_file":0,"previous_page":270,"next_page":90}[name]
            p.translate(12,12);p.rotate(angle)
            line(-8,0,8,0);line(3,-5,8,0);line(3,5,8,0)
        elif name in ("rotate_left","rotate_right","reload"):
            if name == "rotate_left": p.translate(24,0);p.scale(-1,1)
            p.drawArc(QRectF(5,5,14,14),30*16,290*16)
            line(19,3,19,9);line(13,9,19,9)
        elif name == "fit":
            for x,y,sx,sy in ((3,3,1,1),(21,3,-1,1),(3,21,1,-1),(21,21,-1,-1)):
                line(x,y,x+5*sx,y);line(x,y,x,y+5*sy)
        elif name == "invert_colors":
            p.drawEllipse(QRectF(4,4,16,16))
            p.setBrush(color)
            p.drawPie(QRectF(4,4,16,16),90*16,180*16)
        elif name == "replace_colors":
            p.setBrush(QColor("#46BBA9"));p.drawRoundedRect(QRectF(2,3,8,8),2,2)
            p.setBrush(QColor("#F2AC64"));p.drawRoundedRect(QRectF(14,13,8,8),2,2)
            line(5,16,10,16);line(8,14,10,16);line(8,18,10,16)
        elif name == "make_video":
            p.drawRoundedRect(QRectF(3,4,18,16),2,2)
            path=QPainterPath(QPointF(10,8));path.lineTo(16,12);path.lineTo(10,16);path.closeSubpath()
            p.drawPath(path)
        elif name == "compare":
            p.drawRect(QRectF(3,4,18,16));line(12,4,12,20)
        elif name in ("edit_text","select_text"):
            line(5,5,19,5);line(12,5,12,19);line(8,19,16,19)
            if name == "edit_text":
                p.setPen(QPen(QColor("#009B89"),2))
                line(17,19,22,14)
        elif name == "open":
            path=QPainterPath(QPointF(3,19));path.lineTo(3,5);path.lineTo(10,5);path.lineTo(12,8);path.lineTo(21,8);path.lineTo(21,19);path.closeSubpath()
            p.drawPath(path);line(3,11,21,11)
        elif name == "file_info":
            p.drawEllipse(QRectF(3,3,18,18));line(12,11,12,17);line(12,7,12,7.2)
        else:
            p.drawRoundedRect(QRectF(4,3,16,18),2,2)
            label={"save_png":"P","save_pdf":"D","save_postscript":"S","save_edits":"✓"}.get(name,"…")
            f=QFont("Arial");f.setPixelSize(11);f.setBold(True);p.setFont(f)
            p.drawText(QRectF(4,3,16,18),Qt.AlignmentFlag.AlignCenter,label)
        p.end()
        icon.addPixmap(pm)
    return icon
