from PyQt5.QtWidgets import QComboBox, QWidget

from ..localization import translate as _

SFW = "safe"
NSFW = "nsfw"
ALL = "all"


def content_rating_combo(parent: QWidget):
    combo = QComboBox(parent)
    combo.addItem(_("SFW Only"), SFW)
    combo.addItem(_("NSFW Only"), NSFW)
    combo.addItem(_("All"), ALL)
    combo.setToolTip(
        _("Filter by preview rating. Unrated items are only shown when All is selected.")
    )
    return combo


def matches_content_rating(mode: str, level: int):
    return mode == ALL or (mode == SFW and 0 < level < 8) or (mode == NSFW and level >= 8)
