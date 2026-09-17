"""Isolated Maya GUI fixture: Guide/Group visibility/lock, both initial states."""
import json
import os
import sys
import traceback
from dataclasses import replace
from pathlib import Path

from maya import cmds
root = Path(__file__).resolve().parents[1]
if os.environ.get("BIFROST_GUIDE_CHECK_INSTALLED") != "1":
    sys.path.insert(0, str(root / "BifrostScales/scripts"))
from bifrost_scales.ui import BifrostScalesWindow
from bifrost_scales.qt_compat import QtCore
from bifrost_scales.settings import ScaleSettings, ScaleTypeSettings
from bifrost_scales.guides import GuideKind
from check_guide_checkbox_clicks import click_checkbox


def settle():
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(350, loop.quit)
    loop.exec()


def main():
    if os.environ.get("BIFROST_GUIDE_CHECK_INSTALLED") == "1":
        import bifrost_scales.scene as runtime
        assert "Documents/maya/modules" in Path(runtime.__file__).as_posix(), runtime.__file__
    target = cmds.polyPlane(name="GuideUndoTarget")[0]
    window = BifrostScalesWindow()
    window.auto_preview.setChecked(False)
    backend = window.backend
    # Authoring-only scene: no Native generation is needed for visibility/node lock.
    authored = ScaleSettings(target_count=24, lift=.07, inset=.2, squash=.3,
        expand=.4, tip_roundness=.5, tip_offset=.6, forward_offset=.7,
        scale_types=(ScaleTypeSettings(tip_offset=.4),))
    binding = backend.scene.create_system(target, authored)
    backend._binding = binding
    guide = backend.create_point_guide(GuideKind.DENSITY_POINT)
    group = backend.create_guide_group("Undo Group")
    window._load_settings(backend.read_settings())
    assert ScaleSettings.from_mapping(window._snapshot()) == authored
    window.type_name.setText("Retained Shape Fixture")
    window._scale_type_editor_changed()
    assert window._scale_types[0].tip_offset == .4
    snapshot = ScaleSettings.from_mapping(window._snapshot())
    assert replace(snapshot, scale_types=authored.scale_types) == authored
    window._refresh_guides()
    window.tabs.setCurrentIndex(1)
    window.show()
    settle()
    requests = []
    window._parameter_changed = lambda *args, **kwargs: requests.append(args)
    fingerprint = backend.read_guides(force=True).fingerprint()
    settings = backend.read_settings()
    results = []
    for node in (guide, group):
        for column, setter, index in ((2, backend.set_guide_item_visible, 0),
                                      (3, backend.set_guide_item_locked, 1)):
            for initial in (False, True):
                setter(node, initial)
                window._sync_guide_item_presentation()
                settle()
                cmds.flushUndo()  # Only this disposable fixture scene.
                item = window._guide_tree_items_by_node[node]
                click_checkbox(window.guide_tree, item, column)
                settle()
                assert backend.guide_item_presentation_state()[node][index] == (not initial)
                cmds.undo()
                settle()
                item = window._guide_tree_items_by_node[node]
                assert backend.guide_item_presentation_state()[node][index] == initial
                assert (item.checkState(column) == QtCore.Qt.Checked) == initial
                ordinary_redo = not cmds.undoInfo(query=True, redoQueueEmpty=True)
                setter(node, initial)  # Same-state repeat must preserve the redo queue.
                settle()
                noop_redo = not cmds.undoInfo(query=True, redoQueueEmpty=True)
                if noop_redo:
                    cmds.redo()
                    settle()
                    assert backend.guide_item_presentation_state()[node][index] == (not initial)
                    item = window._guide_tree_items_by_node[node]
                    assert (item.checkState(column) == QtCore.Qt.Checked) == (not initial)
                    assert cmds.undoInfo(query=True, undoName=True).startswith("Bifrost Scales Set Guide")
                    cmds.undo()
                    settle()
                    assert cmds.undoInfo(query=True, undoQueueEmpty=True), "One action must use one Undo"
                results.append({"kind": "guide" if node == guide else "group", "column": column,
                                "initial": initial, "ordinary_redo": ordinary_redo, "noop_preserves_redo": noop_redo})
    assert not requests, "Presentation changes must not request geometry evaluation"
    assert backend.read_guides(force=True).fingerprint() == fingerprint
    assert backend.read_settings() == settings
    window.close()
    return {"status": "PASS" if all(r["ordinary_redo"] and r["noop_preserves_redo"] for r in results) else "FAIL",
            "cases": results, "shape_requests": len(requests)}


if __name__ == "__main__":
    try:
        result = main()
    except Exception:
        result = {"status": "FAIL", "error": traceback.format_exc()}
    report = os.environ.get("BIFROST_GUIDE_CHECK_REPORT", "guide-presentation-undo.json")
    (root / "native/build" / report).write_text(json.dumps(result, indent=2), encoding="utf-8")
    cmds.quit(force=True)
