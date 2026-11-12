from __future__ import annotations

from importlib import import_module
from queue import Empty

from PyQt5.QtCore import QTimer, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPushButton, QVBoxLayout, QWidget

from ..image import Extent
from ..localization import translate as _
from ..vnccs_pose import VnccsSession, render_vnccs_pose


class VnccsPoseStudioDialog(QDialog):
    def __init__(self, value: str, extent: Extent, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle(_("VNCCS Pose Studio"))
        self.state = ""
        self._view: QWidget | None = None
        self.session = VnccsSession(value, extent)
        self.finished.connect(self._finish)
        layout = QVBoxLayout(self)
        url = QUrl(self.session.url)
        self.info = QLabel(
            _("Edit the mannequin in VNCCS, then choose Use Pose in Krita to apply the render."),
            self,
        )
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self._external = QPushButton(_("Open in Browser"), self)
        self._external.clicked.connect(self._open_external)
        try:
            browser_type = import_module("PyQt5.QtWebEngineWidgets").QWebEngineView
            view = browser_type(self)
            self._view = view
            layout.addWidget(view, 1)
            self.resize(1200, 820)
            view.load(url)
        except (ImportError, RuntimeError):
            self.resize(460, 130)
            self._open_external()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, parent=self)
        buttons.addButton(self._external, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._receive)
        self._timer.start(100)

    def _open_external(self):
        if self._external.isEnabled() and QDesktopServices.openUrl(QUrl(self.session.url)):
            self._external.setEnabled(False)
            self._release_view()

    def _release_view(self):
        if self._view is not None:
            self._view.hide()
            self._view.deleteLater()
            self._view = None

    def _receive(self):
        try:
            value = self.session.results.get_nowait()
        except Empty:
            return
        try:
            valid = render_vnccs_pose(value) is not None
        except (ValueError, RuntimeError):
            valid = False
        if valid:
            self.state = value
            self.accept()
        else:
            self.info.setText(
                _("Could not read the VNCCS pose render. Open the editor and try again.")
            )

    def _finish(self):
        self._timer.stop()
        self._release_view()
        self.session.close()
