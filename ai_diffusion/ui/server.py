from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from krita import Krita
from PyQt5.QtCore import Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import eventloop, util
from ..backend import model_licenses, pov, resources, server
from ..backend.comfy_client import ComfyClient
from ..backend.network import DownloadProgress
from ..backend.resources import CustomNode, ModelResource
from ..backend.server import Server, ServerBackend, ServerState
from ..localization import translate as _
from ..model.connection import ConnectionState
from ..model.root import root
from ..platform_tools import get_cuda_devices, is_macos, is_windows
from ..settings import Settings, settings
from ..style import Arch
from ..util import ensure
from ..vnccs_pose import vnccs_component
from .model_licenses import confirm_krea2_terms
from .theme import SignalBlocker, add_header, green, grey, highlight, red, set_text_clipped, yellow


class PackageState(Enum):
    installed = 0
    selected = 1
    available = 2
    disabled = 3


@dataclass
class PackageItem:
    label: QLabel
    status: QLabel | QCheckBox
    package: str | ModelResource | CustomNode
    state: PackageState


class PackageGroupWidget(QWidget):
    changed = pyqtSignal()

    def __init__(
        self,
        name: str,
        packages: list[str] | list[ModelResource] | list[CustomNode],
        description: str | None = None,
        is_expanded=True,
        is_checkable=False,
        parent=None,
        package_labels: dict[str, str] | None = None,
    ):
        super().__init__(parent)
        self._backend = settings.server_backend
        self._is_checkable = False
        self._package_labels = package_labels or {}

        self._layout = QGridLayout()
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setColumnMinimumWidth(0, 300)
        self.setLayout(self._layout)

        self._header = QToolButton(self)
        self._header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._header.setContentsMargins(0, 0, 0, 0)
        self._header.setText(name)
        self._header.setCheckable(True)
        self._header.setChecked(is_expanded)
        self._header.setStyleSheet("font-weight:bold; border:none;")
        self._layout.addWidget(self._header, 0, 0)
        self._header.toggled.connect(self._update_visibility)

        self._status = QLabel(self)
        self._layout.addWidget(self._status, 0, 1)

        self._desc: QLabel | None = None
        if description:
            desc = self._desc = QLabel(self)
            desc.setText(description)
            desc.setContentsMargins(20, 0, 0, 0)
            desc.setWordWrap(True)
            desc.setTextFormat(Qt.TextFormat.RichText)
            desc.setOpenExternalLinks(True)
            self._layout.addWidget(desc, 1, 0, 1, 2)

        self._is_checkable = is_checkable
        self._items: list[PackageItem] = [self.add_item(p) for p in packages]
        self._update_visibility()

    def _update_item_visibility(self, item: PackageItem):
        supported = _backend_supports(self.backend, item)
        item.label.setVisible(supported and self._header.isChecked())
        item.status.setVisible(supported and self._header.isChecked())

    def _update_visibility(self):
        self._header.setArrowType(
            Qt.ArrowType.DownArrow if self._header.isChecked() else Qt.ArrowType.RightArrow
        )
        if self._desc:
            self._desc.setVisible(self._header.isChecked())
        for item in self._items:
            self._update_item_visibility(item)

    def expand(self):
        if not self._header.isChecked():
            self._header.setChecked(True)

    def add_item(self, package: str | ModelResource | CustomNode):
        item = PackageItem(
            package=package,
            state=PackageState.available,
            label=QLabel(
                self._package_labels.get(self._package_id(package), self._package_name(package)),
                self,
            ),
            status=QCheckBox(_("Install"), self) if self.is_checkable else QLabel(self),
        )
        item.label.setContentsMargins(20, 0, 0, 0)
        if self._package_labels:
            item.label.setWordWrap(True)
        if self.is_checkable:
            item.status.setChecked(False)
            item.status.toggled.connect(self._handle_checkbox_toggle)
        self._layout.addWidget(item.label, self._layout.rowCount(), 0)
        self._layout.addWidget(item.status, self._layout.rowCount() - 1, 1)
        return item

    @property
    def is_checkable(self):
        return self._is_checkable

    @property
    def values(self):
        return [item.state for item in self._items]

    @values.setter
    def values(self, values: list[PackageState]):
        for item, value in zip(self._items, values):
            item.state = value
        self._update()

    def _update(self):
        for item in self._items:
            self._update_item_visibility(item)
            self._update_workload(item)
            if item.state is PackageState.installed:
                item.status.setText(_("Installed"))
                item.status.setStyleSheet(f"color:{green}")
            elif item.state is PackageState.available:
                item.status.setText(_("Not installed"))
                item.status.setStyleSheet("")
            if self.is_checkable:
                if item.state is PackageState.selected:
                    item.status.setText(_("Not installed"))
                    item.status.setStyleSheet("")
                elif item.state is PackageState.disabled:
                    item.status.setText(_("Not supported"))
                    item.status.setStyleSheet(f"color:{grey}")
                with SignalBlocker(item.status):
                    item.status.setChecked(
                        item.state in [PackageState.selected, PackageState.installed]
                    )
                    item.status.setEnabled(item.state is not PackageState.disabled)
        self._update_status()

    def _update_workload(self, item: PackageItem):
        enabled = _backend_supports(self.backend, item)
        if not enabled and item.state in [PackageState.selected, PackageState.available]:
            item.state = PackageState.disabled
        elif enabled and item.state is PackageState.disabled:
            item.state = PackageState.available

    @property
    def package_names(self):
        return [self._package_id(item.package) for item in self._items]

    @property
    def selected_packages(self):
        return [
            self._package_id(item.package)
            for item in self._items
            if item.state is PackageState.selected
        ]

    @property
    def backend(self):
        return self._backend

    @backend.setter
    def backend(self, backend: ServerBackend):
        self._backend = backend
        self._update()

    def set_installed(self, installed: list[bool]):
        for item, is_installed in zip(self._items, installed):
            if is_installed:
                item.state = PackageState.installed
            elif item.state is PackageState.installed:
                item.state = PackageState.available
        self._update()

    def _update_status(self):
        items = [i for i in self._items if _backend_supports(self.backend, i)]
        available = sum(item.state is PackageState.available for item in items)
        if all(item.state is PackageState.installed for item in items):
            self._status.setText(_("All installed"))
            self._status.setStyleSheet(f"color:{green}")
        elif self.is_checkable:
            selected = sum(item.state is PackageState.selected for item in items)
            if selected > 0:
                self._status.setText(
                    f"{selected} of {selected + available} " + _("packages selected")
                )
                self._status.setStyleSheet(f"color:{yellow}")
            else:
                self._status.setText(f"{available} " + _("packages available"))
                self._status.setStyleSheet(f"color:{grey}")
        else:
            self._status.setText(f"{available} " + _("packages require installation"))
            self._status.setStyleSheet(f"color:{yellow}")

    def _handle_checkbox_toggle(self):
        for item in self._items:
            if item.state in [PackageState.available, PackageState.selected]:
                item.state = (
                    PackageState.selected if item.status.isChecked() else PackageState.available
                )
        self._update()
        self.changed.emit()

    def _package_name(self, package: str | ModelResource | CustomNode):
        return package if isinstance(package, str) else package.name

    def _package_id(self, package: str | ModelResource | CustomNode):
        if isinstance(package, ModelResource):
            return package.id.string
        return self._package_name(package)


def _backend_supports(backend: ServerBackend, item: PackageItem | ModelResource):
    if isinstance(item, PackageItem) and isinstance(item.package, ModelResource):
        item = item.package
    return (
        not isinstance(item, ModelResource)
        or item.requirements is not resources.ModelRequirements.cuda
        or backend is ServerBackend.cuda
    )


class CustomPackageTab(QWidget):
    title = _("Models")

    selected_models_changed = pyqtSignal()

    def __init__(self, server: Server, parent=None):
        super().__init__(parent)
        self._server = server

        layout = QVBoxLayout()
        self.setLayout(layout)

        self._required_group = PackageGroupWidget(
            _("Core components"),
            ["Python", "ComfyUI", _("Custom nodes"), _("Required models")],
            is_expanded=False,
            parent=self,
        )
        layout.addWidget(self._required_group)

        models = [
            m
            for m in resources.default_checkpoints + resources.optional_models
            if m.id.kind not in (resources.ResourceKind.text_encoder, resources.ResourceKind.vae)
        ]
        families = [
            (_("Stable Diffusion 1.5"), (Arch.sd15,)),
            (_("Stable Diffusion XL"), (Arch.sdxl,)),
            (_("Illustrious/NoobAI XL"), (Arch.illu, Arch.illu_v)),
            ("Flux", (Arch.flux, Arch.flux_k, Arch.chroma)),
            ("Flux 2", (Arch.flux2_4b, Arch.flux2_9b)),
            ("Z-Image", (Arch.zimage,)),
            ("Krea 2", (Arch.krea2,)),
            ("MOSS Image", (Arch.moss,)),
            ("MiniMax H3 Image", (Arch.minimax_h3_image,)),
        ]
        grouped = {arch for _, family in families for arch in family}
        families.extend((arch.value, (arch,)) for arch in Arch if arch not in grouped)
        self._packages: list[PackageGroupWidget] = []
        for name, family in families:
            packages = [m for m in models if m.arch in family]
            if not packages:
                continue
            description = None
            if family == (Arch.krea2,):
                description = (
                    _(
                        "Edit V2 weights are free for non-commercial use. Review the model terms before installing."
                    )
                    + ' <a href="https://www.krea.ai/krea-2-licensing">Krea 2 Community License</a>'
                    + "<br>"
                    + _(
                        "Select Live Generation to install the 2-step preview adapter and any missing Krea 2 Turbo models."
                    )
                    + ' <a href="https://huggingface.co/lvladikov/Krea2-Turbo-Distill-2step-LoRA">'
                    + _("Model card")
                    + "</a>"
                )
            if family == (Arch.minimax_h3_image,):
                description = _(
                    "Select Live Generation to install the 2-step pDMD LoRA and missing H3 models."
                )
            self._packages.append(
                PackageGroupWidget(
                    name,
                    packages,
                    description=description,
                    is_checkable=True,
                    is_expanded=False,
                    parent=self,
                )
            )
        self._packages.append(
            PackageGroupWidget(
                _("Upscalers (super-resolution)"),
                resources.upscale_models,
                is_checkable=True,
                is_expanded=False,
                parent=self,
            )
        )
        for group in self._packages:
            group.changed.connect(self.selected_models_changed.emit)
            layout.addWidget(group)

        layout.addStretch()

        self.update_installed()

    def update_installed(self):
        has_missing_nodes = any(
            node.name in self._server.missing_resources for node in resources.required_custom_nodes
        )
        has_missing_models = any(
            model.id.string in self._server.missing_resources
            for model in resources.required_models
            if model.arch is Arch.all
        )
        installed_status = [
            self._server.has_python,
            self._server.has_comfy,
            not has_missing_nodes,
            not has_missing_models,
        ]
        self._required_group.set_installed(installed_status)

        for widget in self._packages:
            widget.backend = self._server.backend
            widget.set_installed([self._server.is_installed(p) for p in widget.package_names])

    def update_backend(self):
        for widget in self._packages:
            widget.backend = self._server.backend

    @property
    def selected_models(self):
        return [model for widget in self._packages for model in widget.selected_packages]

    @selected_models.setter
    def selected_models(self, value: list[str]):
        for widget in self._packages:
            selected = [p for p in widget.package_names if p in value]
            states: list[PackageState] = []
            for state, pkg in zip(widget.values, widget.package_names):
                if state is PackageState.installed:
                    states.append(PackageState.installed)
                elif pkg in selected:
                    states.append(PackageState.selected)
                else:
                    states.append(PackageState.available)
            if states != widget.values:
                widget.values = states


class ComponentsTab(QWidget):
    title = _("Additional components")
    changed = pyqtSignal()

    def __init__(self, srv: Server, parent=None):
        super().__init__(parent)
        self._server = srv
        layout = QVBoxLayout(self)
        self._checkboxes: dict[str, QCheckBox] = {}
        descriptions = {
            pov.pov_component: _(
                "Six camera viewpoints for one or two people. Requires NVIDIA CUDA and about 4.4 GB of additional model downloads."
            ),
            "LoRA Browser metadata": _(
                "Installs ComfyUI-LoRA-Manager and its Python dependencies for previews, tags and metadata."
            ),
            vnccs_component: _(
                "Installs the original VNCCS editor and mannequin (about 53 MB), plus Impact Pack "
                "and RES4LYF for the Krea 2 second pass."
            ),
        }
        for name in (
            *[pkg.name for pkg in resources.selectable_custom_nodes if pkg.name != "Krea 2 Edit"],
            vnccs_component,
        ):
            box = QCheckBox(name, self)
            box.setChecked(
                srv.pose_studio_selected
                if name == vnccs_component
                else name in settings.server_components
            )
            box.setToolTip(descriptions[name])
            self._checkboxes[name] = box
            layout.addWidget(box)
            desc = QLabel(descriptions[name], self)
            desc.setWordWrap(True)
            layout.addWidget(desc)
            if name == pov.pov_component:
                box.toggled.connect(self._toggle_pov)
            else:
                box.toggled.connect(self._save)
        self.eagle_setup = QCheckBox(_("Download and launch Eagle setup"), self)
        layout.addWidget(self.eagle_setup)
        desc = QLabel(
            _(
                "Eagle is a separate desktop app with a 30-day trial. Setup downloads automatically; finish its installer and choose a library, then keep Eagle running to export images."
            ),
            self,
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self.eagle_setup.setEnabled(is_windows or is_macos)
        self.eagle_setup.toggled.connect(self.changed)
        layout.addStretch()

    def _toggle_pov(self, enabled: bool):
        if enabled:
            description = _(
                "Install Make POVs and accept the component licenses below? Models are downloaded from public sources and run locally."
            )
            terms = (
                '<a href="https://www.krea.ai/krea-2-licensing">Krea 2 Community License</a><br>'
                '<a href="https://huggingface.co/Blendcap/sam-3d-body/blob/fa738e386f37c7c00ed3befb46cf995f4ed3131c/LICENSE">SAM License</a><br>'
                '<a href="https://github.com/facebookresearch/dinov3/blob/6876159a11b4df116f30f667f8c9888617df0751/LICENSE.md">DINOv3 License</a>'
            )
            dialog = QMessageBox(
                QMessageBox.Question,
                _("Make POVs"),
                f"<p>{description}</p>{terms}",
                QMessageBox.Yes | QMessageBox.No,
                self,
            )
            dialog.setDefaultButton(QMessageBox.No)
            if dialog.exec_() != QMessageBox.Yes:
                box = self._checkboxes[pov.pov_component]
                blocked = box.blockSignals(True)
                box.setChecked(False)
                box.blockSignals(blocked)
                return
        self._save()

    def _save(self):
        automatic = [name for name in settings.server_components if name == "Krea 2 Edit"]
        settings.server_components = automatic + [
            name for name, box in self._checkboxes.items() if box.isChecked()
        ]
        settings.save()
        self.changed.emit()

    @property
    def requires_install(self):
        return (
            self.eagle_setup.isChecked()
            or self._server.needs_vnccs_assets
            or bool(self._server.pov_model_dependencies())
            or any(
                not self._server.component_installed(pkg)
                for pkg in self._server.selected_custom_nodes
            )
        )


class ServerWidget(QWidget):
    state_changed = pyqtSignal()

    def __init__(self, srv: Server, parent=None):
        super().__init__(parent)
        self._server = srv
        self._error = ""
        self._selected_models: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        add_header(layout, Settings._server_path)

        self._location_edit = QLineEdit(self)
        self._location_edit.textChanged.connect(self._change_location)

        self._location_select = QToolButton(self)
        self._location_select.setIcon(Krita.instance().icon("document-open"))
        self._location_select.clicked.connect(self._select_location)

        location_layout = QHBoxLayout()
        location_layout.addWidget(self._location_edit)
        location_layout.addWidget(self._location_select)
        layout.addLayout(location_layout)

        self._status_label = QLabel(self)
        self._status_label.setStyleSheet("font-weight:bold")
        self._status_label.setWordWrap(True)

        self._progress_bar = QProgressBar(self)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setVisible(False)
        self._progress_bar.setMaximumHeight(16)

        self._progress_info = QLabel(self)
        self._progress_info.setStyleSheet("font-style:italic")
        self._progress_info.setVisible(False)

        self._backend_select = QComboBox(self)
        self._backend_select.addItems([b.value[0] for b in ServerBackend.supported()])
        self._backend_select.currentIndexChanged.connect(self._change_backend)

        self._launch_button = QPushButton("Launch", self)
        self._launch_button.setMinimumWidth(150)
        self._launch_button.setMinimumHeight(35)
        self._launch_button.clicked.connect(self._launch)

        self._manage_button = QToolButton(self)
        self._manage_button.setText(_("Manage"))
        self._manage_button.setPopupMode(QToolButton.InstantPopup)
        self._manage_button.setMinimumWidth(150)

        menu = QMenu(self)
        verify_action = menu.addAction(_("Verify"))
        ensure(verify_action).triggered.connect(self.verify_models)
        reinstall_action = menu.addAction(_("Re-install"))
        ensure(reinstall_action).triggered.connect(self.reinstall)
        delete_action = menu.addAction(_("Delete"))
        ensure(delete_action).triggered.connect(self.uninstall)
        self._manage_button.setMenu(menu)

        anchor = _("View log files")
        open_log_button = QLabel(f"<a href='file://{util.log_dir}'>{anchor}</a>", self)
        open_log_button.setToolTip(str(util.log_dir))
        open_log_button.linkActivated.connect(self._open_logs)

        status_layout = QVBoxLayout()
        status_layout.addWidget(self._status_label)
        status_layout.addWidget(self._backend_select, 0, Qt.AlignmentFlag.AlignLeft)
        status_layout.addWidget(self._progress_bar)
        status_layout.addWidget(self._progress_info)
        status_layout.addStretch()

        buttons_layout = QVBoxLayout()
        buttons_layout.addWidget(self._launch_button)
        buttons_layout.addWidget(self._manage_button)
        buttons_layout.addWidget(open_log_button, 0, Qt.AlignmentFlag.AlignRight)

        launch_layout = QHBoxLayout()
        launch_layout.addLayout(status_layout, 1)
        launch_layout.addLayout(buttons_layout, 0)
        layout.addLayout(launch_layout)

        self._custom_tab = CustomPackageTab(srv, self)
        self._custom_tab.selected_models_changed.connect(self._update_selections)

        self._components_tab = ComponentsTab(srv, self)
        self._components_tab.changed.connect(self.update_ui)

        tabs = QTabWidget(self)
        for tab in [self._custom_tab, self._components_tab]:
            scroll = QScrollArea(tabs)
            scroll.setWidget(tab)
            scroll.setWidgetResizable(True)
            scroll.setFrameStyle(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            tabs.addTab(scroll, tab.title)

        layout.addWidget(tabs, 1)

        root.connection.state_changed.connect(self.update_ui)
        self.update_ui()

    def _change_location(self):
        if settings.server_path != self._location_edit.text():
            self._server.path = Path(self._location_edit.text())
            self._server.check_install()
            settings.server_path = self._location_edit.text()
            settings.save()
            self.update_ui()
            self._custom_tab.update_installed()
            self.state_changed.emit()

    def _select_location(self):
        path = self._server.path
        if not path.exists():
            path = path.parent
        if not path.exists():
            path = Path(Settings._server_path.default)
            path.mkdir(parents=True, exist_ok=True)
        path = QFileDialog.getExistingDirectory(
            self, _("Select Directory"), str(path), QFileDialog.ShowDirsOnly
        )
        if path:
            path = Path(path)
            if path != Path(Settings._server_path.default) and not (path / "ComfyUI").exists():
                path = path / "ComfyUI"
            self._location_edit.setText(str(path))

    def _change_backend(self):
        backends = ServerBackend.supported()
        try:
            backend = backends[self._backend_select.currentIndex()]
        except Exception:
            backend = backends[0]
        if settings.server_backend != backend:
            self._server.backend = backend
            settings.server_backend = backend
            settings.save()
            self._server.check_install()
            self._custom_tab.update_backend()
            self.update_ui()
            self.state_changed.emit()

    def _open_logs(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(util.log_dir)))

    def _check_cuda_support(self):
        if self._server.backend is ServerBackend.cuda and not get_cuda_devices():
            question = _(
                "The CUDA backend requires a NVIDIA GPU, but no compatible devices were found. Do you want to continue with installation anyway?"
            )
            answer = QMessageBox.warning(
                self,
                _("No CUDA Devices Found"),
                question,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.StandardButton.No,
            )
            return answer == QMessageBox.StandardButton.Yes
        return True

    def _launch(self):
        self._error = ""
        if self.requires_install:
            if not self._check_cuda_support():
                return
            eventloop.run(self._install())
        elif self._server.state is ServerState.update_required:
            eventloop.run(self._upgrade())
        elif self._server.state is ServerState.stopped:
            eventloop.run(self._start())
        elif self._server.state is ServerState.running:
            eventloop.run(self._stop())

    async def _start(self):
        self._launch_button.setEnabled(False)
        self._status_label.setText(_("Starting server..."))
        self._status_label.setStyleSheet("color:orange;font-weight:bold")
        try:
            url = await self._server.start()
            self.update_ui()
            self.state_changed.emit()
            self._status_label.setText(_("Server running - Connecting..."))
            self._status_label.setStyleSheet(f"color:{yellow};font-weight:bold")
            await root.connection._connect(ComfyClient(url))
        except Exception as e:
            self.show_error(e)
        self.update_ui()
        self.state_changed.emit()

    async def _stop(self):
        self._launch_button.setEnabled(False)
        self._status_label.setText(_("Stopping server..."))
        self._status_label.setStyleSheet(f"color:{yellow};font-weight:bold")
        try:
            if root.connection.state is ConnectionState.connected:
                await root.connection.disconnect()
            await self._server.stop()
        except Exception as e:
            self.show_error(e)
        self.update_ui()
        self.state_changed.emit()

    async def _install(self):
        try:
            if model_licenses.requires_acceptance(self.selected_models) and not confirm_krea2_terms(
                self
            ):
                return
            self._server.enable_model_components(self.selected_models)
            await self._prepare_for_install()

            if self._server.state is ServerState.update_required:
                await self._server.upgrade(self._handle_progress)

            if self._server.state in [ServerState.not_installed, ServerState.missing_resources]:
                await self._server.install(self._handle_progress)
            await self._server.install_components(self._handle_progress)
            if self._components_tab.eagle_setup.isChecked():
                from ..eagle import prepare_eagle_installer

                await prepare_eagle_installer(self._handle_progress)
                self._components_tab.eagle_setup.setChecked(False)
            self._custom_tab.update_installed()

            models = list(
                dict.fromkeys([*self.selected_models, *self._server.pov_model_dependencies()])
            )
            if models:
                await self._server.download(models, self._handle_progress)

            self.selected_models = []
            self._custom_tab.update_installed()
            self.update_ui()

            await self._start()

        except Exception as e:
            self.show_error(e)
        self.update_ui()

    async def _upgrade(self):
        try:
            assert self._server.state in [ServerState.update_required, ServerState.running]

            await self._prepare_for_install()
            await self._server.upgrade(self._handle_progress)
            self.update_ui()
            await self._start()

        except Exception as e:
            self.show_error(e)
        self.update_ui()

    async def _prepare_for_install(self):
        if self._server.state is ServerState.running:
            await self._stop()

        self._launch_button.setEnabled(False)
        self._manage_button.setEnabled(False)
        self._status_label.setStyleSheet(f"color:{highlight};font-weight:bold")
        self._backend_select.setVisible(False)
        self._progress_bar.setVisible(True)
        self._progress_info.setVisible(True)
        self._progress_info.setText("")

    def _handle_progress(self, report: server.InstallationProgress):
        self._status_label.setText(f"{report.stage}...")
        set_text_clipped(self._progress_info, report.message)
        if isinstance(report.progress, DownloadProgress) and report.progress.total > 0:
            self._progress_bar.setMaximum(100)
            self._progress_bar.setValue(int(report.progress.value * 100))
            self._progress_bar.setFormat(
                f"{report.progress.received:.0f} MB of {report.progress.total:.0f} MB -"
                f" {report.progress.speed:.1f} MB/s"
            )
            self._progress_bar.setTextVisible(True)
        elif isinstance(report.progress, DownloadProgress):  # download, but unknown total size
            self._progress_bar.setMaximum(0)
            self._progress_bar.setValue(0)
            self._progress_bar.setFormat(
                f"{report.progress.received:.0f} MB - {report.progress.speed:.1f} MB/s"
            )
            self._progress_bar.setTextVisible(True)
        elif isinstance(report.progress, tuple):
            self._progress_bar.setMinimum(0)
            self._progress_bar.setMaximum(report.progress[1])
            self._progress_bar.setValue(report.progress[0])
            self._progress_bar.setFormat(f"{report.progress[0]} / {report.progress[1]}")
            self._progress_bar.setTextVisible(True)
        else:
            self._progress_bar.setMaximum(0)
            self._progress_bar.setValue(0)
            self._progress_bar.setTextVisible(False)

    def verify_models(self):
        self._error = ""
        eventloop.run(self._verify_models())

    async def _verify_models(self):
        await self._prepare_for_install()
        try:
            bad_models = await self._server.verify(self._handle_progress)

            if not bad_models:
                QMessageBox.information(
                    self,
                    _("Verification Complete"),
                    _("All model files were verified successfully."),
                )
            else:
                failed_files = "\n".join([
                    f"• {status.file.path} - {status.info or status.state.name}"
                    for status in bad_models
                ])

                msg_box = QMessageBox(
                    QMessageBox.Warning,
                    _("Verification Failed"),
                    _("The following files failed verification:")
                    + f"\n\n{failed_files}\n\n"
                    + _("Would you like to delete and re-download these files?"),
                    QMessageBox.Yes | QMessageBox.No,
                    self,
                )

                if msg_box.exec_() == QMessageBox.Yes:
                    await self._server.fix_models(bad_models, self._handle_progress)
        except Exception as e:
            self.show_error(e)
        finally:
            self._progress_bar.setVisible(False)
            self._progress_info.setVisible(False)
            self.update_ui()

    def reinstall(self):
        self._error = ""
        eventloop.run(self._reinstall())

    async def _reinstall(self):
        msg_box = QMessageBox(
            QMessageBox.Question,
            _("Confirm Reinstallation"),
            _(
                "This will reinstall the server components while keeping your downloaded models. Continue?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            self,
        )

        if msg_box.exec_() != QMessageBox.Yes:
            return

        if model_licenses.requires_acceptance(self.selected_models) and not confirm_krea2_terms(
            self
        ):
            return
        await self._prepare_for_install()
        try:
            self._server.enable_model_components(self.selected_models)
            await self._server.uninstall(self._handle_progress, delete_models=False)
            await self._server.install(self._handle_progress)
            if len(self.selected_models) > 0:
                await self._server.download(self.selected_models, self._handle_progress)
        except Exception as e:
            self.show_error(e)
        finally:
            self.update_ui()

    def uninstall(self):
        self._error = ""
        eventloop.run(self._uninstall())

    async def _uninstall(self):
        msg_box = QMessageBox(
            QMessageBox.Warning,
            _("Confirm Deletion"),
            _("WARNING: This will delete the entire server installation INCLUDING ALL MODELS!")
            + "\n\n"
            + _("This action cannot be undone.")
            + "\n\n"
            + _("Are you absolutely sure you want to continue?"),
            QMessageBox.Cancel,
            self,
        )
        msg_box.addButton(_("Delete"), QMessageBox.DestructiveRole)
        msg_box.setDefaultButton(QMessageBox.Cancel)
        if msg_box.exec_() != 0:  # Destructive role returns 0
            return

        if model_licenses.requires_acceptance(self.selected_models) and not confirm_krea2_terms(
            self
        ):
            return
        await self._prepare_for_install()
        try:
            await self._server.uninstall(self._handle_progress, delete_models=True)
        except Exception as e:
            self.show_error(e)
        finally:
            self._progress_bar.setVisible(False)
            self._progress_info.setVisible(False)
            self.update_ui()

    def update_ui(self):
        if self._location_edit.text() != settings.server_path:
            self._location_edit.setText(settings.server_path)
        backends = ServerBackend.supported()
        try:
            index = backends.index(settings.server_backend)
        except Exception:
            index = 0
        self._backend_select.setCurrentIndex(index)
        self._progress_bar.setVisible(False)
        self._progress_info.setVisible(False)
        self._backend_select.setVisible(True)
        self._launch_button.setEnabled(True)
        self._manage_button.setEnabled(True)
        self._location_edit.setEnabled(True)

        state = self._server.state
        if state is ServerState.not_installed:
            self._status_label.setText(_("Server is not installed"))
            self._status_label.setStyleSheet(f"color:{red};font-weight:bold")
            self._manage_button.setEnabled(False)
        elif state is ServerState.missing_resources:
            self._status_label.setText(_("Server is missing required components"))
            self._status_label.setStyleSheet(f"color:{red};font-weight:bold")
            self._manage_button.setEnabled(False)
        elif state in [ServerState.installing, ServerState.verifying, ServerState.uninstalling]:
            self._location_edit.setEnabled(False)
            self._progress_bar.setVisible(True)
            self._progress_info.setVisible(True)
            self._backend_select.setVisible(False)
            self._launch_button.setEnabled(False)
            self._manage_button.setEnabled(False)
        elif state is ServerState.update_required:
            text = _("Upgrade required") + f": v{self._server.version} -> v{resources.version}"
            if self._server.version == "incomplete":
                text = _("Previous installation is incomplete")
            self._status_label.setText(text)
            self._status_label.setStyleSheet(f"color:{yellow};font-weight:bold")
            self._launch_button.setText(_("Upgrade"))
        elif state is ServerState.stopped:
            self._status_label.setText(_("Server stopped"))
            self._status_label.setStyleSheet(f"color:{red};font-weight:bold")
            self._launch_button.setText(_("Launch"))
        elif state is ServerState.starting:
            self._status_label.setText(_("Starting server..."))
            self._status_label.setStyleSheet(f"color:{yellow};font-weight:bold")
            self._launch_button.setText(_("Launch"))
            self._launch_button.setEnabled(False)
            self._manage_button.setEnabled(False)
            self._location_edit.setEnabled(False)
        elif state is ServerState.running:
            connection_state = root.connection.state
            if connection_state is ConnectionState.disconnected:
                self._status_label.setText(_("Server running - Disconnected"))
                self._status_label.setStyleSheet(f"color:{grey};font-weight:bold")
            elif connection_state is ConnectionState.connecting:
                self._status_label.setText(_("Server running - Connecting..."))
                self._status_label.setStyleSheet(f"color:{yellow};font-weight:bold")
            elif connection_state is ConnectionState.connected:
                self._status_label.setText(_("Server running - Connected"))
                self._status_label.setStyleSheet(f"color:{green};font-weight:bold")
            elif connection_state is ConnectionState.error:
                text = _("Server running - Connection error")
                error = root.connection.error or "Unknown error"
                self._status_label.setText(f"<b>{text}:</b> {error}")
                self._status_label.setStyleSheet(f"color:{red}")
            self._launch_button.setText(_("Stop"))
            self._location_edit.setEnabled(False)

        if self.requires_install:
            self._launch_button.setText(_("Install"))
            if not self._server.version and not self._server.can_install:
                self._status_label.setText(
                    _(
                        "Invalid location: directory is not empty, but no previous installation was found"
                    )
                )
                self._status_label.setStyleSheet(f"color:{red};font-weight:bold")
                self._launch_button.setEnabled(False)
            elif not self._server.has_comfy and len(self.selected_models) == 0:
                self._status_label.setText(_("Please select models for installation"))
                self._status_label.setStyleSheet(f"color:{yellow};font-weight:bold")
                self._launch_button.setEnabled(False)
            else:
                self._launch_button.setEnabled(True)

        self.show_error(self._error)

    def show_error(self, error: str | Exception):
        if isinstance(error, Exception):
            self._error = str(error) or repr(error)
        else:
            self._error = error
        if self._error:
            error_text = "<b>Error:</b> " + self._error.replace("\n", "<br>")
            self._status_label.setText(error_text)
            self._status_label.setStyleSheet(f"color:{red}")

    def _update_selections(self):
        self.selected_models = self._custom_tab.selected_models
        self.update_ui()

    @property
    def requires_install(self):
        state = self._server.state
        install_required = state in [ServerState.not_installed, ServerState.missing_resources]
        install_optional = state in [
            ServerState.stopped,
            ServerState.running,
            ServerState.update_required,
        ] and (len(self.selected_models) > 0 or self._components_tab.requires_install)
        return install_required or install_optional

    @property
    def selected_models(self):
        return self._server.resolve_model_dependencies(self._selected_models)

    @selected_models.setter
    def selected_models(self, value: list[str]):
        self._selected_models = value
        if self._custom_tab.selected_models != value:
            self._custom_tab.selected_models = value
