"""Light and dark look on top of Qt's Fusion style, so it is the same on Windows and every Linux desktop."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication

from .. import system

ACCENT = "#e5484d"
ACCENT_HOVER = "#ec5d5e"
ACCENT_PRESSED = "#ce2c31"

LIGHT = {
    "window": "#f6f6f7", "base": "#ffffff", "alt": "#f1f1f3", "text": "#1c1c1f", "muted": "#6b6b73",
    "button": "#ffffff", "border": "#d9d9de", "tooltip": "#1c1c1f", "tooltip_text": "#f6f6f7",
    "ok": "#1f8a4c", "warn": "#b4670a", "error": "#cd2b31", "info": "#2f6fd6",
}
DARK = {
    "window": "#18181b", "base": "#111113", "alt": "#1d1d21", "text": "#ececef", "muted": "#9b9ba4",
    "button": "#26262b", "border": "#36363d", "tooltip": "#ececef", "tooltip_text": "#18181b",
    "ok": "#3dd68c", "warn": "#f1a10d", "error": "#ff6369", "info": "#70b8ff",
}

_current = LIGHT


def colors() -> dict[str, str]:
    return _current


def system_is_dark() -> bool:
    hints = QGuiApplication.styleHints()
    return hints.colorScheme() == Qt.ColorScheme.Dark


def _palette(c: dict[str, str]) -> QPalette:
    p = QPalette()
    role = QPalette.ColorRole
    p.setColor(role.Window, QColor(c["window"]))
    p.setColor(role.WindowText, QColor(c["text"]))
    p.setColor(role.Base, QColor(c["base"]))
    p.setColor(role.AlternateBase, QColor(c["alt"]))
    p.setColor(role.Text, QColor(c["text"]))
    p.setColor(role.PlaceholderText, QColor(c["muted"]))
    p.setColor(role.Button, QColor(c["button"]))
    p.setColor(role.ButtonText, QColor(c["text"]))
    p.setColor(role.BrightText, QColor("#ffffff"))
    p.setColor(role.ToolTipBase, QColor(c["tooltip"]))
    p.setColor(role.ToolTipText, QColor(c["tooltip_text"]))
    p.setColor(role.Highlight, QColor(ACCENT))
    p.setColor(role.HighlightedText, QColor("#ffffff"))
    p.setColor(role.Link, QColor(c["info"]))
    p.setColor(role.Mid, QColor(c["border"]))
    p.setColor(role.Midlight, QColor(c["alt"]))
    p.setColor(role.Dark, QColor(c["border"]))
    p.setColor(role.Light, QColor(c["base"]))
    for r in (role.WindowText, role.Text, role.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, r, QColor(c["muted"]))
    return p


def _check_mark() -> str:
    """A white tick for checked boxes. Style sheets only take images from files, so draw one into the data folder."""
    path = system.data_dir() / "ui" / "check-v1.png"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        pm = QPixmap(32, 32)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#ffffff"), 4.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPolyline([QPointF(7, 17), QPointF(13, 23), QPointF(25, 9)])
        p.end()
        pm.save(str(path))
    return path.as_posix()


def _stylesheet(c: dict[str, str]) -> str:
    check = _check_mark()
    return f"""
    QCheckBox::indicator {{
        width: 14px; height: 14px; border: 1px solid {c['muted']}; border-radius: 4px; background: {c['base']};
    }}
    QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
    QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url({check}); }}
    QCheckBox::indicator:disabled {{ background: {c['alt']}; border-color: {c['border']}; }}
    QCheckBox::indicator:checked:disabled {{ background: {c['muted']}; border-color: {c['muted']}; }}
    QToolTip {{ padding: 4px 6px; border: 0; }}
    QPushButton {{
        background: {c['button']}; border: 1px solid {c['border']}; border-radius: 6px;
        padding: 5px 12px; min-height: 18px;
    }}
    QPushButton:hover {{ border-color: {c['muted']}; }}
    QPushButton:pressed {{ background: {c['alt']}; }}
    QPushButton:disabled {{ color: {c['muted']}; background: {c['alt']}; }}
    QPushButton#primary {{
        background: {ACCENT}; color: white; border: 1px solid {ACCENT}; font-weight: 600;
    }}
    QPushButton#primary:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
    QPushButton#primary:pressed {{ background: {ACCENT_PRESSED}; }}
    QPushButton#primary:disabled {{ background: {c['border']}; border-color: {c['border']}; color: {c['muted']}; }}
    QPushButton#segmentLeft, QPushButton#segmentRight {{ padding: 5px 16px; }}
    QPushButton#segmentLeft {{ border-top-right-radius: 0; border-bottom-right-radius: 0; }}
    QPushButton#segmentRight {{ border-top-left-radius: 0; border-bottom-left-radius: 0; border-left: 0; }}
    QPushButton#segmentLeft:checked, QPushButton#segmentRight:checked {{
        background: {ACCENT}; border-color: {ACCENT}; color: white; font-weight: 600;
    }}
    QPushButton#badge {{
        border: 0; background: transparent; padding: 2px 8px; color: {c['muted']};
    }}
    QPushButton#badge:hover {{ color: {c['text']}; text-decoration: underline; }}
    QPushButton#badgeAlert {{
        border: 0; border-radius: 10px; background: {ACCENT}; color: white; padding: 2px 10px; font-weight: 600;
    }}
    QLineEdit, QPlainTextEdit, QComboBox {{
        background: {c['base']}; border: 1px solid {c['border']}; border-radius: 6px; padding: 4px 6px;
        selection-background-color: {ACCENT};
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
    QComboBox::drop-down {{ border: 0; width: 18px; }}
    QTableView {{
        background: {c['base']}; border: 1px solid {c['border']}; border-radius: 6px;
        gridline-color: transparent; selection-background-color: {ACCENT};
    }}
    QHeaderView::section {{
        background: {c['alt']}; border: 0; border-bottom: 1px solid {c['border']}; padding: 5px 6px;
        color: {c['muted']}; font-weight: 600;
    }}
    QGroupBox {{
        border: 1px solid {c['border']}; border-radius: 8px; margin-top: 14px; padding: 10px 8px 8px 8px;
    }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {c['muted']}; }}
    QFrame#card {{ background: {c['base']}; border: 1px solid {c['border']}; border-radius: 8px; }}
    QLabel#muted {{ color: {c['muted']}; }}
    QLabel#heading {{ font-size: 15px; font-weight: 600; }}
    QProgressBar {{
        border: 0; border-radius: 4px; background: {c['alt']}; text-align: center; max-height: 8px;
    }}
    QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
    QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 6px; top: -1px; }}
    QStatusBar::item {{ border: 0; }}
    """


def apply(app: QApplication, mode: str) -> None:
    global _current
    dark = mode == "dark" or (mode == "system" and system_is_dark())
    _current = DARK if dark else LIGHT
    app.setStyle("Fusion")
    app.setPalette(_palette(_current))
    app.setStyleSheet(_stylesheet(_current))
