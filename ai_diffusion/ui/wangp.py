from collections.abc import Callable
from html import escape
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..backend.network import NetworkError
from ..backend.wangp import WanGPClient
from ..backend.wangp_launcher import can_launch, launch_and_connect, launch_command, mcp_unavailable
from ..localization import translate as _
from ..settings import settings
from .settings import wangp_mcp_hint


def _show_help(parent: QWidget, title: str, markup: str, actions: list[str]):
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    layout = QVBoxLayout(dialog)
    label = QLabel(markup, dialog)
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setOpenExternalLinks(True)
    label.setWordWrap(True)
    layout.addWidget(label)
    buttons = QDialogButtonBox(dialog)
    buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
    buttons.rejected.connect(dialog.reject)
    for index, name in enumerate(actions, 1):
        button = QPushButton(name, buttons)
        buttons.addButton(button, QDialogButtonBox.ButtonRole.ActionRole)
        button.clicked.connect(lambda _checked, index=index: dialog.done(index))
    layout.addWidget(buttons)
    dialog.resize(520, dialog.sizeHint().height())
    return dialog.exec_()


async def connect_wangp(
    parent: QWidget, status: Callable[[str], None], is_closed: Callable[[], bool]
):
    client = WanGPClient(settings.wangp_mcp_url)
    while not is_closed():
        try:
            status(_("Connecting to WanGP…"))
            await client.connect(timeout=4)
            return client
        except NetworkError as e:
            if not mcp_unavailable(e):
                raise
        if is_closed():
            return None

        running = escape(_("Is WanGP running?"))
        mcp = escape(_("Is MCP enabled?"))
        guidance = escape(
            _("If WanGP is closed, start it. If it is already open, check the MCP setting below.")
        )
        local = can_launch(client.url)
        actions = [_("Check MCP again")]
        if local:
            actions.append(_("Launch WanGP"))
            if settings.wangp_installation_path:
                actions.append(_("Choose another folder"))
        choice = _show_help(
            parent,
            _("Cannot reach WanGP MCP"),
            f"<p><b>{running}</b></p><p>{guidance}</p><p><b>{mcp}</b></p>{wangp_mcp_hint()}",
            actions,
        )
        if choice in (2, 3):
            installation = choose_wangp_installation(parent, client.url, change_folder=choice == 3)
            if installation is None:
                status("")
                return None
            root, command = installation
            status(_("Starting WanGP and waiting for MCP…"))
            await launch_and_connect(root, client, command)
            return client
        if choice != 1:
            status("")
            return None
    return None


def choose_wangp_installation(parent: QWidget, url: str, *, change_folder: bool = False):
    previous = settings.wangp_installation_path.strip()
    folder = "" if change_folder else previous
    while True:
        if not folder:
            folder = QFileDialog.getExistingDirectory(
                parent, _("Select the Wan2GP folder containing wgp.py"), previous
            )
            if not folder:
                return None
        root = Path(folder)
        try:
            command = launch_command(root, url)
        except (OSError, ValueError) as e:
            instruction = escape(
                _("Choose the Wan2GP folder that contains wgp.py and its environment.")
            )
            docs = escape(_("Official WanGP installation guide"))
            url_docs = "https://github.com/deepbeepmeep/WanGP/blob/main/docs/INSTALLATION.md"
            choice = _show_help(
                parent,
                _("WanGP installation not found"),
                f'<p>{escape(str(e))}</p><p>{instruction}</p><p><a href="{url_docs}">{docs}</a></p>',
                [_("Choose another folder")],
            )
            if choice != 1:
                return None
            folder = ""
            continue
        settings.wangp_installation_path = folder
        settings.save()
        return root, command
