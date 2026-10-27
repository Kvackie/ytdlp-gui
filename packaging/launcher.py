"""PyInstaller entry point (it needs a script, not `python -m`).

`ytdlp-gui --self-test result.json [--install]` checks that the frozen build works without opening a
window: bundled modules, TLS certificates, the GUI (offscreen) and, with --install, a real download and
run of yt-dlp into a throwaway data folder. The result is written to the given file.
"""
import json
import os
import sys
import tempfile


def self_test(out_path: str, install: bool) -> int:
    results: dict[str, str] = {}
    ok = True

    def check(name, fn):
        nonlocal ok
        try:
            results[name] = str(fn())
        except Exception as exc:  # noqa: BLE001 - report every failure
            ok = False
            results[name] = f"FAILED: {type(exc).__name__}: {exc}"

    os.environ["YTDLP_GUI_DATA"] = tempfile.mkdtemp(prefix="ytdlp-gui-selftest-")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    def modules():
        import lzma
        import tarfile
        import zipfile

        return ", ".join(m.__name__ for m in (lzma, tarfile, zipfile))

    def certificates():
        from ytdlp_gui import net

        count = len(net.ssl_context().get_ca_certs())
        assert count > 0, "no CA certificates found"
        return f"{count} CA certificates"

    def command_line():
        from pathlib import Path

        from ytdlp_gui.options import DownloadOptions, ToolPaths, build_args

        args = build_args(DownloadOptions(mode="audio", audio_format="mp3"), ["https://example.com"],
                          ToolPaths(Path("yt-dlp")))
        assert "--audio-format" in args
        return len(args)

    def gui():
        from PySide6.QtWidgets import QApplication

        from ytdlp_gui.components import Components
        from ytdlp_gui.gui import theme
        from ytdlp_gui.gui.main_window import MainWindow
        from ytdlp_gui.settings import Settings

        app = QApplication.instance() or QApplication([])
        theme.apply(app, "dark")
        settings = Settings.load()
        settings.setup_done = True
        MainWindow._startup = lambda self: None
        window = MainWindow(settings, Components())
        window.show()
        app.processEvents()
        title = window.windowTitle()
        window.close()
        return f"{app.platformName()} / {title}"

    def ytdlp_install():
        from ytdlp_gui.components import Components

        comps = Components()
        release = comps.ytdlp.latest()
        comps.ytdlp.install(release)  # verifies the checksum and runs `yt-dlp --version`
        return f"{release.asset} {comps.ytdlp.installed_version()}"

    check("modules", modules)
    check("certificates", certificates)
    check("command_line", command_line)
    check("gui", gui)
    if install:
        check("ytdlp_install", ytdlp_install)
    results["ok"] = str(ok)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--self-test":
        sys.exit(self_test(sys.argv[2], "--install" in sys.argv[3:]))
    from ytdlp_gui.__main__ import main

    sys.exit(main())
