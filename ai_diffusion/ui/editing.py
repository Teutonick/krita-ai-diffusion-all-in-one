from __future__ import annotations

from typing import cast

from PyQt5.QtCore import QEvent, QMetaObject, QObject, Qt, QTimer, QUuid
from PyQt5.QtGui import QMouseEvent, QStandardItemModel
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..backend.client import is_style_supported, resolve_arch
from ..backend.resources import Arch
from ..localization import translate as _
from ..model.model import DocumentModel
from ..model.properties import Binding
from ..model.root import root
from ..style import Styles
from ..util import ensure
from . import theme


class EditControls(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._model: DocumentModel | None = None
        self._connections: list[QMetaObject.Connection] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.task = QComboBox(self)
        self.task.addItem(_("Generate"), False)
        self.task.addItem(_("Edit image"), True)
        self.task.setToolTip(
            _("Generate a new image, or edit an existing image with instructions.")
        )
        self.task.currentIndexChanged.connect(self._set_task)
        self.source = QComboBox(self)
        self.source.setMinimumWidth(0)
        self.source.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.source.setMinimumContentsLength(8)
        self.source.setToolTip(
            _("The primary image to edit. Additional prompt references do not replace this source.")
        )
        self.source.currentIndexChanged.connect(self._set_source)
        self.use_layer = QToolButton(self)
        self.use_layer.setText(_("Use active layer"))
        self.use_layer.clicked.connect(self._use_active_layer)
        row.addWidget(QLabel(_("Task:"), self))
        row.addWidget(self.task)
        row.addWidget(self.source, 1)
        row.addWidget(self.use_layer)
        layout.addLayout(row)
        root.connection.models_changed.connect(self._sync)

    @property
    def model(self):
        return self._model

    @model.setter
    def model(self, model: DocumentModel):
        Binding.disconnect_all(self._connections)
        self._model = model
        self._connections = [
            model.style_changed.connect(self._sync),
            model.edit_mode_changed.connect(self._sync),
            model.edit_source_layer_id_changed.connect(self._sync),
            model.layers.changed.connect(self._sync),
            model.layers.active_changed.connect(self._sync),
        ]
        self._sync()

    def _sync(self, *_args):
        model = self._model
        self.setEnabled(model is not None and model.has_document)
        if model is None or not model.has_document:
            self.task.setToolTip(_("Open a document to choose an edit source."))
            return
        editing = model.is_editing
        with theme.SignalBlocker(self.task), theme.SignalBlocker(self.source):
            self.task.setCurrentIndex(1 if editing else 0)
            ensure(cast(QStandardItemModel, self.task.model()).item(1)).setEnabled(model.can_edit)
            ensure(cast(QStandardItemModel, self.task.model()).item(0)).setEnabled(
                not resolve_arch(model.style, root.connection.client_if_connected).is_edit
            )
            self.source.clear()
            self.source.addItem(_("Source: visible canvas (without preview)"), "")
            for layer in model.layers.images:
                self.source.addItem(_("Layer:") + " " + layer.name, layer.id_string)
            index = self.source.findData(model.edit_source_layer_id)
            if index < 0:
                self.source.addItem(
                    _("Missing source layer — choose another"), model.edit_source_layer_id
                )
                index = self.source.count() - 1
            self.source.setCurrentIndex(index)
        self.source.setEnabled(editing)
        self.source.setToolTip(
            _("The primary image to edit. Additional prompt references do not replace this source.")
            + "\n"
            + self.source.currentText()
        )
        self.use_layer.setEnabled(model.can_edit and model.layers.active.type.is_image)
        if editing:
            extra = model._edit_loras([])
            loras = model.active_style.get_models([]).loras + extra
            names = ", ".join(l.name.replace("\\", "/").split("/")[-1] for l in loras)
            reference_hint = (
                _("Krea 2: source is image 1; use at most one additional @reference.")
                if model.arch is Arch.krea2
                else _("The source is image 1; @references add other images.")
            )
            if model.arch is Arch.minimax_h3_image:
                reference_hint = _(
                    "Select an area in Krita to apply the edit only there. "
                    "Without a selection, the edit applies to the whole image."
                )
            self.task.setToolTip(
                _("Edit preset:")
                + " "
                + model.active_style.name
                + (" · LoRA: " + names if names else "")
                + "\n"
                + _("Write the change to make.")
                + " "
                + reference_hint
                + " "
                + _("Results appear in history.")
            )
        else:
            self.task.setToolTip(
                _(
                    "Generate: describe a new image. To change an existing image, select Edit image and choose its source."
                )
            )

    def _set_task(self):
        if self._model is None:
            return
        enabled = bool(self.task.currentData())
        if not enabled and self._model.style.edit_kind and self._model.arch is Arch.krea2:
            style = Styles.list().find("built-in/krea2-turbo.json")
            if style is not None and is_style_supported(style, root.connection.client_if_connected):
                self._model.style = style
        self._model.set_editing(enabled)
        if not enabled:
            self._model.strength = 1.0
        self._sync()

    def _set_source(self):
        if self._model is not None:
            self._model.edit_source_layer_id = self.source.currentData() or ""

    def _use_active_layer(self):
        if self._model is not None:
            try:
                self._model.edit_layer(self._model.layers.active)
            except Exception as e:
                self._model.report_error(str(e))


class LayerPromptActions(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pending = False
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def eventFilter(self, a0, a1):
        watched, event = a0, a1
        if event is None:
            return False
        if event.type() in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.ContextMenu,
        ):
            widget = watched
            while isinstance(widget, QWidget):
                if widget.objectName() == "listLayers":
                    if event.type() == QEvent.Type.ContextMenu or (
                        isinstance(event, QMouseEvent)
                        and event.button() == Qt.MouseButton.RightButton
                    ):
                        self._pending = True
                        QTimer.singleShot(0, self._clear_pending)
                    break
                widget = widget.parentWidget()
        elif event.type() == QEvent.Type.Show and isinstance(watched, QMenu) and self._pending:
            self._pending = False
            model = root.model_for_active_document()
            if model is not None and not watched.property("aiDiffusionLayerActions"):
                layer = model.layers.active
                if layer.type.is_image:
                    layer_id = layer.id_string
                    watched.setProperty("aiDiffusionLayerActions", True)
                    watched.addSeparator()
                    watched.addAction(
                        _("Add Layer Reference to AI Prompt"),
                        lambda: self._run(model, layer_id, False),
                    )
                    action = ensure(
                        watched.addAction(
                            _("Edit This Layer with AI"),
                            lambda: self._run(model, layer_id, True),
                        )
                    )
                    action.setEnabled(model.can_edit)
        return False

    def _clear_pending(self):
        self._pending = False

    def _run(self, model: DocumentModel, layer_id: str, edit: bool):
        try:
            layer = model.layers.updated().find(QUuid(layer_id))
            if layer is not None:
                model.edit_layer(layer) if edit else model.add_layer_reference(layer)
        except Exception as e:
            model.report_error(str(e))
