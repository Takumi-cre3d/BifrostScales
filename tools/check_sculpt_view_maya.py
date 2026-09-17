"""Deferred isolated Maya GUI check; no production scene is opened."""
import os
import sys
import traceback
from pathlib import Path

from maya import cmds, mel
from maya.api import OpenMaya as om

root = Path(__file__).resolve().parents[1]
if os.environ.get("BIFROST_SCULPT_CHECK_INSTALLED") != "1":
    sys.path.insert(0, str(root / "BifrostScales/scripts"))
sys.path.insert(0, str(root / "tools"))
from bifrost_scales.sculpt_editor import SculptEditor
from bifrost_scales.qt_compat import QtWidgets, QtCore, QtGui


def check_view_isolation(editor, target):
    """An overlapping scene mesh must not contribute pixels to the patch view."""
    images = []
    scene_images = []
    scene_panel = cmds.getPanel(type="modelPanel")[-1]
    scene_state = (cmds.modelEditor(scene_panel, query=True, viewSelected=True),
                   cmds.modelEditor(scene_panel, query=True, filter=True))
    for visible in (True, False):
        cmds.setAttr(target + ".visibility", visible)
        cmds.refresh(force=True)
        path = root / ("native/build/sculpt-isolation-%s.png" % visible)
        cmds.playblast(editorPanelName=editor.panel, completeFilename=str(path),
                       format="image", compression="png", widthHeight=(512, 512),
                       frame=1, viewer=False, forceOverwrite=True, percent=100,
                       showOrnaments=False, offScreen=True)
        images.append(QtGui.QImage(str(path)))
        scene_path = root / ("native/build/sculpt-scene-%s.png" % visible)
        cmds.playblast(editorPanelName=scene_panel, completeFilename=str(scene_path),
                       format="image", compression="png", widthHeight=(512, 512),
                       frame=1, viewer=False, forceOverwrite=True, percent=100,
                       showOrnaments=False, offScreen=True)
        scene_images.append(QtGui.QImage(str(scene_path)))
    cmds.setAttr(target + ".visibility", True)
    assert not images[0].isNull() and images[0] == images[1], "Scene mesh is rendered in the sculpt-only view"
    assert scene_images[0] != scene_images[1], "Scene viewport must still display the comparison mesh"
    assert scene_state == (cmds.modelEditor(scene_panel, query=True, viewSelected=True),
                           cmds.modelEditor(scene_panel, query=True, filter=True))


def check_patch_membership(editor):
    objects = cmds.modelEditor(editor.panel, query=True, viewObjects=True)
    members = cmds.sets(objects, query=True) or []
    expected = {
        editor.function().fullPathName(),
        cmds.ls(editor.direction_marker, long=True)[0],
    }
    assert set(cmds.ls(members, long=True)) == expected, members


def check_direction_marker(editor):
    images = []
    for visible in (True, False):
        cmds.setAttr(editor.direction_marker + ".visibility", visible)
        cmds.refresh(force=True)
        path = root / ("native/build/sculpt-direction-%s.png" % visible)
        cmds.playblast(editorPanelName=editor.panel, completeFilename=str(path),
                       format="image", compression="png", widthHeight=(512, 512),
                       frame=1, viewer=False, forceOverwrite=True, percent=100,
                       showOrnaments=False, offScreen=True)
        images.append(QtGui.QImage(str(path)))
    cmds.setAttr(editor.direction_marker + ".visibility", True)
    assert not images[0].isNull() and images[0] != images[1], "Forward marker is not rendered"


def main():
    if os.environ.get("BIFROST_SCULPT_CHECK_INSTALLED") == "1":
        import bifrost_scales.sculpt_editor as runtime
        assert "Documents/maya/modules" in Path(runtime.__file__).as_posix(), runtime.__file__
    from check_sculpt_editor_maya import main as regression
    regression()
    target = cmds.polyCube(name="SculptViewTarget")[0]
    cmds.select(target)
    cmds.setToolTo("selectSuperContext")
    panels = cmds.getPanel(type="modelPanel")
    before = {p: (cmds.modelPanel(p, q=True, camera=True), cmds.modelEditor(p, q=True, filter=True)) for p in panels}
    camera_before = cmds.xform("persp", q=True, matrix=True, worldSpace=True)
    applied = []
    script_log = root / "native/build/sculpt-view-script-editor.log"
    script_log.unlink(missing_ok=True)
    cmds.scriptEditorInfo(historyFilename=str(script_log), writeHistory=True)
    editor = SculptEditor({}, applied.append, owner_key="test:global")
    editor.run = lambda action: action()  # Test errors must not open a modal dialog.
    editor.show()
    app = QtWidgets.QApplication.instance()
    app.processEvents()
    assert editor.panel and editor.view_widget.isVisible()
    assert cmds.modelEditor(editor.panel, q=True, control=True)
    mel.eval("updateRendererUI;")
    cmds.setFocus(editor.panel)
    cmds.refresh(force=True)
    cmds.playblast(editorPanelName=editor.panel, completeFilename=str(root / "native/build/sculpt-panel-render.png"),
        format="image", compression="png", widthHeight=(512,512), frame=1,
        viewer=False, forceOverwrite=True, percent=100, showOrnaments=False, offScreen=True)
    assert all(not b.icon().isNull() for b in editor.brushes.buttons())
    assert cmds.ls(selection=True) == [target]
    assert editor.direction_marker and cmds.objExists(editor.direction_marker)
    marker_points = cmds.xform(
        editor.direction_marker + ".cv[*]",
        query=True, translation=True, worldSpace=True,
    )
    assert max(marker_points[2::3]) == .70
    assert any("前方" in label.text() for label in editor.findChildren(QtWidgets.QLabel))
    check_direction_marker(editor)
    check_view_isolation(editor, target)
    check_patch_membership(editor)
    patch = editor.function().fullPathName()
    camera, marker, panel = editor.camera, editor.direction_marker, editor.panel
    assert cmds.modelEditor(panel, query=True, filter=True) == editor.view_filter
    for p in panels:
        visible = cmds.lsThroughFilter(cmds.modelEditor(p, query=True, filter=True)) or []
        assert patch not in (cmds.ls(visible, long=True) or []), (p, visible)
        assert marker not in (cmds.ls(visible, long=True) or []), (p, visible)
        target_shape = cmds.listRelatives(target, shapes=True, fullPath=True)[0]
        assert target_shape in (cmds.ls(visible, long=True) or []), (p, visible)
    cmds.setAttr(target+".translateX", 2)
    undo_before = cmds.undoInfo(query=True, undoName=True)
    for command in ("SetMeshSculptTool", "SetMeshGrabTool", "SetMeshSmoothTool"):
        editor.tool(command)
        assert patch in cmds.ls(selection=True, long=True)
        editor.leave_brush()
        assert cmds.ls(selection=True) == [target]
        assert cmds.currentCtx() == "selectSuperContext"
    editor.choose_brush("SetMeshGrabTool")
    assert cmds.currentCtx() == "selectSuperContext"
    editor.eventFilter(editor.view_widget, QtCore.QEvent(QtCore.QEvent.Enter))
    assert editor.editing
    mel.eval("updateRendererUI;")
    editor.eventFilter(editor.view_widget, QtCore.QEvent(QtCore.QEvent.Leave))
    mel.eval("updateRendererUI;")
    assert cmds.currentCtx() == "selectSuperContext" and cmds.ls(selection=True) == [target]
    assert cmds.undoInfo(query=True, undoName=True) == undo_before
    points = editor.function().getPoints()
    points[544].y += .2
    editor.function().setPoints(points)
    editor.commit()
    assert len(applied) == 1
    editor.view_widget.grab().save(str(root / "native/build/sculpt-embedded-view.png"))
    editor.grab().save(str(root / "native/build/sculpt-embedded-ui.png"))
    editor.close()
    app.processEvents()
    assert not cmds.objExists(camera) and not cmds.objExists(marker)
    assert not cmds.modelEditor(panel, exists=True)
    assert cmds.objExists(patch)
    assert cmds.xform("persp", q=True, matrix=True, worldSpace=True) == camera_before
    assert {p: (cmds.modelPanel(p, q=True, camera=True), cmds.modelEditor(p, q=True, filter=True)) for p in panels} == before
    reopened = SculptEditor({}, applied.append, owner_key="test:global")
    reopened.run = lambda action: action()
    reopened.show()
    app.processEvents()
    assert reopened.function().fullPathName() == patch
    check_patch_membership(reopened)
    reopened.commit()
    assert applied[-1] == applied[-2]
    reopened.reject()  # Escape also releases native resources, not only the title-bar X.
    assert reopened.panel is None
    assert cmds.undoInfo(query=True, undoName=True) == undo_before or cmds.undoInfo(query=True, undoName=True) == "Restore Sculpt Boundary"
    other = SculptEditor({}, applied.append, owner_key="test:type")
    other.run = lambda action: action()
    other.show()
    assert other.function().fullPathName() != patch
    get_item = QtWidgets.QInputDialog.getItem
    try:
        QtWidgets.QInputDialog.getItem = lambda *args: ("64", True)
        other.new_patch()
    finally:
        QtWidgets.QInputDialog.getItem = get_item
    assert other.function().numVertices == 4225
    check_patch_membership(other)
    assert cmds.objExists(patch)
    cmds.file(new=True, force=True)
    assert other.panel is None and not other.scene_callbacks
    cmds.scriptEditorInfo(writeHistory=False)
    history = script_log.read_text(encoding="utf-8", errors="replace")
    assert "updateModelPanelBar ||" not in history and "cleanupModelPanelBar ||" not in history, history
    assert ": Syntax error" not in history, history
    print("Embedded view / icons / brushes / apply / camera-filter restoration / owned draft reopen PASS")


if __name__ == "__main__":
    report = root / "native/build/sculpt-view-result.txt"
    try:
        main()
        report.write_text("PASS\n", encoding="utf-8")
    except Exception:
        report.write_text(traceback.format_exc(), encoding="utf-8")
    finally:
        cmds.quit(force=True)
