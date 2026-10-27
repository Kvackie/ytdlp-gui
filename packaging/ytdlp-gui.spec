# PyInstaller spec: one self-contained executable (ytdlp-gui.exe on Windows, ytdlp-gui on Linux).
# Build from the repo root:  pyinstaller packaging/ytdlp-gui.spec
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent

# Qt modules the app never uses; leaving them out keeps the file much smaller.
excludes = [
    "tkinter",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets", "PySide6.QtXml", "PySide6.QtConcurrent", "PySide6.QtPrintSupport",
    "PySide6.QtUiTools", "PySide6.QtSvgWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "pytest", "pytestqt",
]

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="ytdlp-gui",
    console=False,
    icon=str(ROOT / "packaging" / ("icon.ico" if sys.platform == "win32" else "icon.png")),
    version=str(ROOT / "build" / "version_info.txt") if sys.platform == "win32" else None,
    upx=False,
    strip=False,
)
