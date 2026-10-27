"""Render the app icon to packaging/icon.ico and icon.png (run once; the files are committed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QGuiApplication  # noqa: E402

app = QGuiApplication([])
from ytdlp_gui.gui.icons import render  # noqa: E402

here = Path(__file__).parent
render(256).save(str(here / "icon.png"))
render(256).save(str(here / "icon.ico"))
print("written", sorted(p.name for p in here.glob("icon.*")))
