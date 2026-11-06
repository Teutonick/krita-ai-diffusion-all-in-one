from dataclasses import replace

from PyQt5.QtWidgets import QApplication, QWidget

from ai_diffusion.image import Bounds
from ai_diffusion.model.jobs import JobParams
from ai_diffusion.ui.generation import HistoryWidget
from ai_diffusion.ui.region import InstructionDialog


def test_history_groups_matching_runs_and_wildcard_batch():
    first = JobParams(Bounds(0, 0, 64, 64), "prompt", metadata={"steps": 20}, seed=1, batch_id="a")
    same = replace(first, seed=2, batch_id="b")
    different = replace(same, metadata={"steps": 30})
    wildcard = replace(first, name="different evaluated prompt", batch_id="a")
    assert HistoryWidget._same_batch(first, same)
    assert not HistoryWidget._same_batch(first, different)
    assert HistoryWidget._same_batch(first, wildcard)
    assert HistoryWidget._same_batch(first, replace(same, batch_id=""))


def test_instruction_dialog_focuses_input():
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.show()
    dialog = InstructionDialog("previous instruction", parent)
    dialog.show()
    dialog.activateWindow()
    app.processEvents()
    assert dialog._edit.hasFocus()
    assert dialog._edit.textCursor().selectedText() == "previous instruction"
    dialog.close()
    parent.close()
