"""Entry point: `python -m ytdlp_gui [links...]`."""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)

    from . import APP_ID, APP_NAME, __version__, system

    if system.IS_WINDOWS:
        import ctypes

        # Own taskbar group and icon instead of the generic Python/PyInstaller one.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)

    from PySide6.QtWidgets import QApplication

    from .components import Components
    from .gui import icons, theme
    from .gui.main_window import MainWindow, extract_urls
    from .settings import Settings

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(APP_ID)
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(icons.app_icon())
    # Everything the app imports is loaded by now, so the bootloader's DLL path is no longer needed.
    system.reset_dll_search_path()

    settings = Settings.load()
    theme.apply(app, settings.theme)
    components = Components()
    components.ytdlp.channel = settings.ytdlp_channel

    window = MainWindow(settings, components, extract_urls(" ".join(argv[1:])))
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
