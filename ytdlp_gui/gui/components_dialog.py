"""Shows the managed tools (yt-dlp, FFmpeg, Deno); installs, updates and removes them.

Also serves as the first-run setup screen.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, system
from ..components import YTDLP_CHANNELS, App, Component
from ..settings import Settings
from .queue_model import human_bytes
from .updates import UpdateService


class ComponentCard(QFrame):
    def __init__(self, comp: Component, service: UpdateService, setup: bool, parent: QWidget):
        super().__init__(parent)
        self.comp = comp
        self.service = service
        self.setObjectName("card")
        self.failed = ""

        self.check = QCheckBox()
        # A copy already installed on the system (e.g. Debian's ffmpeg package) is used as is.
        self.check.setChecked(comp.offered() and not comp.is_managed())
        self.check.setEnabled(comp.supported() and not comp.required)
        self.check.setVisible(setup and comp.offered())
        if comp.required:
            self.check.setToolTip("Required")

        title = QLabel(f"<b>{comp.title}</b>")
        self.status = QLabel()
        self.status.setObjectName("muted")
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        desc = QLabel(comp.description)
        desc.setObjectName("muted")
        desc.setWordWrap(True)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.phase = QLabel()
        self.phase.setObjectName("muted")

        self.action = QPushButton()
        self.action.clicked.connect(self._on_action)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self._on_remove)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(lambda: service.cancel_install(comp.key))
        for b in (self.action, self.remove_btn, self.cancel_btn):
            b.setVisible(not setup)

        head = QHBoxLayout()
        head.addWidget(self.check)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.action)
        head.addWidget(self.remove_btn)
        head.addWidget(self.cancel_btn)

        progress_row = QHBoxLayout()
        progress_row.addWidget(self.bar, 1)
        progress_row.addWidget(self.phase)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)
        lay.addLayout(head)
        lay.addWidget(desc)
        lay.addWidget(self.status)
        lay.addLayout(progress_row)
        self._setup = setup
        self.refresh()

    def set_progress(self, phase: str, done: int, total: int) -> None:
        self.bar.setVisible(True)
        self.phase.setVisible(True)
        if total:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(done * 1000 / total))
            self.phase.setText(f"{phase} — {human_bytes(done)} of {human_bytes(total)}")
        else:
            self.bar.setRange(0, 0)
            self.phase.setText(phase)

    def refresh(self) -> None:
        comp, service = self.comp, self.service
        installing = service.installing(comp.key)
        self.bar.setVisible(installing)
        self.phase.setVisible(installing)
        if not installing:
            self.bar.setRange(0, 1000)
            self.bar.setValue(0)

        latest = service.latest.get(comp.key)
        app = comp.key == App.key
        if app and comp.restart_pending:
            text = f"Version {__version__}  ·  <b>{comp.restart_pending} is installed</b>, restart to use it"
        elif app and not comp.supported():
            text = f"Version {__version__}  ·  updates itself only in the released Windows and Linux builds"
        elif not comp.supported() and not comp.path():
            text = "No build is available for this system. Install it with your package manager."
        elif comp.is_managed():
            text = f"{'Version' if app else 'Installed'}: {comp.installed_version() or 'unknown version'}"
            if service.update_available(comp.key):
                text += f"  ·  <b>update available</b> ({latest.version})"
            elif latest:
                text += "  ·  up to date"
        elif comp.system_path():
            text = "Installed on this system"
        else:
            text = f"Not installed  ·  download {comp.download_size}"
        if self.failed:
            text += f"<br><span style='color:#e5484d'>{self.failed}</span>"
        elif comp.key in service.errors:
            text += f"<br>Update check failed: {service.errors[comp.key]}"
        self.status.setText(text)

        if not self._setup:
            self.cancel_btn.setVisible(installing)
            self.remove_btn.setVisible(comp.is_managed() and not installing and not app)
            if app:
                # Only ever "Update", never a reinstall; then "Restart" to switch to the new version.
                self.action.setVisible(bool(comp.restart_pending)
                                       or (service.update_available(comp.key) and not installing))
                self.action.setText("Restart" if comp.restart_pending else "Update")
            else:
                self.action.setVisible(comp.offered() and not installing)
                if not comp.is_managed():
                    self.action.setText("Install")
                elif service.update_available(comp.key):
                    self.action.setText("Update")
                else:
                    self.action.setText("Reinstall")
            self.action.setObjectName("primary" if self.action.text() != "Reinstall" else "")
            self.action.style().unpolish(self.action)
            self.action.style().polish(self.action)

    def _on_action(self) -> None:
        self.failed = ""
        if self.comp.key == App.key and self.comp.restart_pending:
            self.service.restart_requested.emit()
            return
        if not self.service.install(self.comp.key):
            QMessageBox.information(self, "Downloads running",
                                    "Wait for the running downloads to finish (or cancel them) before updating.")
        self.refresh()

    def _on_remove(self) -> None:
        if self.comp.required and not self.comp.system_path():
            answer = QMessageBox.question(self, "Remove yt-dlp",
                                          "Without yt-dlp nothing can be downloaded. Remove it anyway?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        if not self.service.remove(self.comp.key):
            QMessageBox.information(self, "Busy", "Wait for the running downloads to finish first.")
        self.refresh()


class ComponentsDialog(QDialog):
    def __init__(self, service: UpdateService, settings: Settings, setup: bool = False, parent=None):
        super().__init__(parent)
        self.service = service
        self.settings = settings
        self.setup = setup
        self.setWindowTitle("Set up yt-dlp GUI" if setup else "Tools & updates")
        self.setMinimumWidth(620)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        heading = QLabel("Welcome!" if setup else "Tools & updates")
        heading.setObjectName("heading")
        lay.addWidget(heading)
        intro = QLabel(
            "yt-dlp GUI runs yt-dlp and a few helper tools. They are downloaded once from their official "
            "GitHub releases, checked against the published checksums, and kept up to date for you."
            if setup else
            "The app and its tools are updated from their official GitHub releases. Tools already installed "
            "on this system are used as they are."
        )
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        lay.addWidget(intro)

        shown = service.components.tools() if setup else service.components.all()
        self.cards = {c.key: ComponentCard(c, service, setup, self) for c in shown}
        for card in self.cards.values():
            lay.addWidget(card)
            card.check.toggled.connect(self.refresh)

        # Update preferences
        prefs = QHBoxLayout()
        prefs.addWidget(QLabel("yt-dlp channel:"))
        self.channel = QComboBox()
        for name in YTDLP_CHANNELS:
            self.channel.addItem(name.capitalize(), name)
        self.channel.setCurrentIndex(max(0, self.channel.findData(settings.ytdlp_channel)))
        self.channel.setToolTip("Stable is tested; Nightly gets fixes for broken sites sooner.")
        self.channel.currentIndexChanged.connect(self._on_channel)
        prefs.addWidget(self.channel)
        prefs.addStretch(1)
        self.check_btn = QPushButton("Check for updates")
        self.check_btn.clicked.connect(lambda: service.check())
        self.check_btn.setVisible(not setup)
        prefs.addWidget(self.check_btn)
        lay.addLayout(prefs)

        self.auto_check = QCheckBox("Check for updates when the app starts")
        self.auto_check.setChecked(settings.check_updates)
        self.auto_check.toggled.connect(lambda v: setattr(settings, "check_updates", v))
        self.auto_install = QCheckBox("Install yt-dlp and Deno updates automatically")
        self.auto_install.setChecked(settings.auto_update)
        self.auto_install.toggled.connect(lambda v: setattr(settings, "auto_update", v))
        lay.addWidget(self.auto_check)
        lay.addWidget(self.auto_install)

        self.info = QLabel()
        self.info.setObjectName("muted")
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.info.linkActivated.connect(lambda _: system.open_path(system.bin_dir()))
        lay.addWidget(self.info)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        if setup:
            self.skip_btn = QPushButton("Skip")
            self.skip_btn.clicked.connect(self.reject)
            self.go_btn = QPushButton("Download and install")
            self.go_btn.setObjectName("primary")
            self.go_btn.setDefault(True)
            self.go_btn.clicked.connect(self._install_selected)
            buttons.addWidget(self.skip_btn)
            buttons.addWidget(self.go_btn)
        else:
            close = QPushButton("Close")
            close.clicked.connect(self.accept)
            buttons.addWidget(close)
        lay.addLayout(buttons)

        self._waiting: set[str] = set()
        service.progress.connect(self._on_progress)
        service.installed.connect(self._on_installed)
        service.install_failed.connect(self._on_failed)
        service.checked.connect(self.refresh)
        service.check_started.connect(self.refresh)
        service.busy_changed.connect(self.refresh)
        self.refresh()
        if not setup and not service.latest and not service.checking:
            service.check()

    def refresh(self) -> None:
        for card in self.cards.values():
            card.refresh()
        self.check_btn.setEnabled(not self.service.checking)
        self.check_btn.setText("Checking…" if self.service.checking else "Check for updates")
        last = self.settings.last_update_check
        checked = time.strftime("%Y-%m-%d %H:%M", time.localtime(last)) if last else "never"
        self.info.setText(f"Last checked: {checked}.  <a href='#'>Open the tools folder</a>")
        if self.setup:
            self.go_btn.setEnabled(not self.service.installing())
            if not self.service.installing() and self.go_btn.text() != "Retry":
                wanted = any(c.check.isChecked() for c in self.cards.values())
                self.go_btn.setText("Download and install" if wanted else "Continue")

    def _on_channel(self) -> None:
        channel = self.channel.currentData()
        self.settings.ytdlp_channel = channel
        self.service.set_channel(channel)
        if not self.setup:
            self.service.check()
        self.refresh()

    def _on_progress(self, key: str, phase: str, done: int, total: int) -> None:
        if key in self.cards:
            self.cards[key].set_progress(phase, done, total)

    def _on_installed(self, key: str, _auto: bool) -> None:
        self._waiting.discard(key)
        if key in self.cards:
            self.cards[key].failed = ""
        self.refresh()
        if self.setup and not self._waiting and not any(c.failed for c in self.cards.values()):
            self.settings.setup_done = True
            self.accept()

    def _on_failed(self, key: str, error: str) -> None:
        self._waiting.discard(key)
        if key in self.cards:
            self.cards[key].failed = error
        self.refresh()
        if self.setup and not self._waiting:
            self.go_btn.setText("Retry")

    def _install_selected(self) -> None:
        keys = [k for k, card in self.cards.items() if card.check.isChecked() and card.comp.supported()]
        for key in keys:
            self.cards[key].failed = ""
            if self.service.install(key):
                self._waiting.add(key)
        if not keys:
            self.settings.setup_done = True
            self.accept()
        self.refresh()

    def reject(self) -> None:
        if self.setup:
            self.settings.setup_done = True  # don't nag on every start; the Tools dialog stays available
        for key in list(self._waiting):
            self.service.cancel_install(key)
        super().reject()
