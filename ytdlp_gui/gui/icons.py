"""The app icon, drawn in code so no image files have to be bundled."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap

from .theme import ACCENT


def render(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 64.0

    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0, QColor("#ff7a59"))
    grad.setColorAt(1, QColor(ACCENT))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(grad))
    p.drawRoundedRect(QRectF(2 * s, 2 * s, 60 * s, 60 * s), 14 * s, 14 * s)

    # Down arrow into a tray.
    white = QColor("#ffffff")
    p.setBrush(white)
    arrow = QPainterPath()
    arrow.moveTo(QPointF(27 * s, 12 * s))
    arrow.lineTo(QPointF(37 * s, 12 * s))
    arrow.lineTo(QPointF(37 * s, 29 * s))
    arrow.lineTo(QPointF(45 * s, 29 * s))
    arrow.lineTo(QPointF(32 * s, 43 * s))
    arrow.lineTo(QPointF(19 * s, 29 * s))
    arrow.lineTo(QPointF(27 * s, 29 * s))
    arrow.closeSubpath()
    p.drawPath(arrow)

    pen = QPen(white, 5 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    tray = QPainterPath()
    tray.moveTo(QPointF(14 * s, 40 * s))
    tray.lineTo(QPointF(14 * s, 50 * s))
    tray.lineTo(QPointF(50 * s, 50 * s))
    tray.lineTo(QPointF(50 * s, 40 * s))
    p.drawPath(tray)
    p.end()
    return pm


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(render(size))
    return icon
