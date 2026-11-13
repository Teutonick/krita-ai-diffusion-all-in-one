from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QHBoxLayout, QLineEdit, QPlainTextEdit, QToolButton, QWidget

from ..backend.dictation import dictation, supported
from ..localization import translate as _
from ..settings import settings


def _microphone_icon(color: QColor):
    pixmap = QPixmap(20, 20)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(color, 1.5))
    painter.drawRoundedRect(7, 2, 6, 10, 3, 3)
    painter.drawArc(4, 3, 12, 12, 180 * 16, 180 * 16)
    painter.drawLine(10, 15, 10, 18)
    painter.drawLine(7, 18, 13, 18)
    painter.end()
    return QIcon(pixmap)


class DictationButton(QToolButton):
    def __init__(self, edit: QPlainTextEdit | QLineEdit):
        super().__init__(edit)
        self._edit = edit
        self._token = object()
        self.setAccessibleName(_("Dictate text"))
        self.setAutoRaise(True)
        self.setCheckable(True)
        self.clicked.connect(self._toggle)
        dictation.changed.connect(self._refresh)
        dictation.recognized.connect(self._insert)
        settings.changed.connect(self._setting_changed)
        edit.installEventFilter(self)
        token = self._token
        self.destroyed.connect(lambda: dictation.cancel(token))
        self._refresh()

    def cancel(self):
        dictation.cancel(self._token)

    def eventFilter(self, a0, a1):
        obj, event = a0, a1
        if (
            obj is self._edit
            and event is not None
            and event.type() in (QEvent.Type.Hide, QEvent.Type.EnabledChange)
        ):
            if event.type() == QEvent.Type.Hide or not self._edit.isEnabled():
                self.cancel()
        return False

    def _setting_changed(self, key, value):
        if key == "dictation_enabled":
            self._refresh()

    def _refresh(self):
        active = dictation.target is self._token
        recording = active and dictation.recording
        self.setVisible(supported and settings.dictation_enabled)
        self.setChecked(recording)
        self.setEnabled(dictation.available or recording)
        self.setIcon(
            _microphone_icon(
                QColor("#df4545") if recording else self.palette().buttonText().color()
            )
        )
        self.setToolTip(
            _("Start dictation")
            if dictation.available and dictation.status == _("Ready")
            else dictation.status
        )

    def _toggle(self):
        if dictation.target is self._token:
            dictation.finish()
        else:
            dictation.start(self._token)
        self._refresh()

    def _insert(self, target, text: str):
        if target is not self._token or not self._edit.isVisible() or self._edit.isReadOnly():
            return
        if isinstance(self._edit, QLineEdit):
            self._edit.insert(text)
        else:
            self._edit.insertPlainText(text)
        self._edit.setFocus()


def dictation_row(edit: QPlainTextEdit | QLineEdit):
    row = QWidget(edit.parentWidget())
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    button = DictationButton(edit)
    layout.addWidget(edit, 1)
    layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignTop)
    return row, button
