"""Run deferred in an isolated Maya GUI; never use a production scene."""
from pathlib import Path
import sys
import os
import traceback

import maya.standalone
if os.environ.get("BIFROST_SCALES_MAYA_INITIALIZED") != "1":
    maya.standalone.initialize(name="python")
from maya import cmds
from maya.api import OpenMaya as om
print("Sculpt check: Maya initialized", flush=True)

root = Path(__file__).resolve().parents[1]
if os.environ.get("BIFROST_SCULPT_CHECK_INSTALLED") != "1":
    sys.path.insert(0, str(root / "BifrostScales/scripts"))
from bifrost_scales.qt_compat import QtWidgets
from bifrost_scales.sculpt_editor import SculptEditor
from bifrost_scales.sculpt_surface import sample_surface
print("Sculpt check: imports ready", flush=True)


def main():
    print("Sculpt check: starting Qt", flush=True)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    print("Sculpt check: creating dialog", flush=True)
    applied = []
    editor = SculptEditor({}, applied.append)
    editor.create_or_update()
    print("Sculpt check: created mesh", flush=True)
    fn = editor.function()
    assert fn.numVertices == 1089 and fn.numPolygons == 2048
    assert editor.disk
    rest = fn.getPoints()
    for j in range(33):
        for i in range(33):
            if min(i,j,32-i,32-j) == 0:
                p = rest[j*33+i]
                assert abs((p.x*p.x+p.z*p.z)**.5-.5) < 1e-6
    cmds.setAttr("persp.translate", 0, 1.8, 0, type="double3")
    cmds.setAttr("persp.rotate", -90, 0, 0, type="double3")
    cmds.playblast(completeFilename=str(root / "native/build/disk-sculpt-preview.png"),
        format="image", compression="png", widthHeight=(512,512), frame=1,
        viewer=False, forceOverwrite=True, percent=100, showOrnaments=False, offScreen=True)
    points = fn.getPoints()
    points[544].x += .7
    points[544].y += .2
    points[544].z -= .3
    points[0].y += .1  # Boundary edit before the very first System apply.
    fn.setPoints(points)
    editor.commit()
    assert all(abs(a-b) < 1e-6 for a,b in zip(sample_surface(applied[-1], .5, .5), (.7, -.3, .2)))
    editor.create_or_update()
    editor.commit()
    assert abs(sample_surface(applied[-1], .5, .5)[2]-.2) < 1e-6
    assert abs(editor.function().getPoints()[0].y) < 1e-7
    assert not hasattr(editor, "curves")
    resumed = SculptEditor({}, applied.append)
    resumed.resume()
    resumed.commit()
    assert applied[-1] == applied[-2]
    points = fn.getPoints()
    points[0].y += .1
    fn.setPoints(points)
    resumed.commit()
    assert sample_surface(applied[-1], 0, 0) == (0., 0., 0.)
    editor.close()
    resumed.close()
    app.processEvents()
    assert cmds.objExists(fn.fullPathName()), "Closing must preserve sculpt drafts"
    reopened = SculptEditor({}, applied.append)
    reopened.resume()
    reopened.commit()
    assert sample_surface(applied[-1], 0, 0) == (0., 0., 0.)
    for tool in ("SetMeshSculptTool", "SetMeshGrabTool", "SetMeshSmoothTool"):
        reopened.tool(tool)
    reopened.close()
    legacy = SculptEditor({"schema": "vector-surface/1", "resolution": 8}, applied.append)
    legacy.create_or_update()
    old_fn = legacy.function()
    old_points = old_fn.getPoints()
    old_points[0].y += .3
    old_fn.setPoints(old_points)
    legacy.close()
    migrated = SculptEditor({}, applied.append)
    migrated.resume()  # Reconnect does not reject an already moved border.
    question = QtWidgets.QMessageBox.question
    QtWidgets.QMessageBox.question = lambda *args: QtWidgets.QMessageBox.Yes
    try:
        migrated.upgrade()
    finally:
        QtWidgets.QMessageBox.question = question
    migrated.commit()
    assert applied[-1]["schema"] == "vector-surface/3"
    assert sample_surface(applied[-1], 0, 0) == (0., 0., 0.)
    assert abs(migrated.function().getPoints()[0].y) < 1e-7
    assert all(a.isEquivalent(b, 1e-6) for a, b in zip(list(old_fn.getPoints())[1:],list(old_points)[1:]))
    migrated.close()
    from bifrost_scales.ui import BifrostScalesWindow
    from bifrost_scales.settings import ScaleSettings, ScaleTypeSettings
    window = BifrostScalesWindow()
    window._load_settings(ScaleSettings(sculpt_surface=applied[-1], normal_offset=.001), refresh_scene=False)
    assert window._snapshot()["sculpt_surface"] == applied[-1]
    assert window._snapshot()["sculpt_settled_resolution"] == 8
    assert abs(window.normal_offset.value()-.1) < 1e-9
    assert abs(window._snapshot()["normal_offset"]-.001) < 1e-9
    assert not hasattr(window, "width_curve") and not hasattr(window, "type_width")
    assert not hasattr(window, "profile_curve") and not hasattr(window, "type_length")
    window._load_settings(ScaleSettings(scale_types=(ScaleTypeSettings(offset=.1, width_multiplier=1.6, length_multiplier=1.2),)), refresh_scene=False)
    window._scale_type_selection_changed(0)
    assert window.type_offset.value() == 10.
    window.type_offset.setValue(.1)
    window._scale_type_editor_changed()
    assert abs(window._scale_types[0].offset-.001) < 1e-9
    assert window._scale_types[0].width_multiplier == 1.6
    assert window._scale_types[0].length_multiplier == 1.2
    window.close()
    # Layout-less patches from earlier versions remain square and keep their deltas.
    from bifrost_scales.sculpt_surface import normalize_surface, editor_points
    from bifrost_scales.sculpt_editor import grid_faces
    import json
    old_surface = normalize_surface({"schema":"vector-surface/3","resolution":4})
    old_mesh = om.MFnMesh().create([om.MPoint(*p) for p in editor_points(old_surface)], [4]*16, grid_faces(4))
    old_name = om.MFnDagNode(old_mesh).fullPathName()
    old_shape = cmds.listRelatives(old_name,shapes=True,fullPath=True)[0]
    cmds.addAttr(old_shape,longName="bifrostSculptSurface",dataType="string")
    cmds.setAttr(old_shape+".bifrostSculptSurface",json.dumps(old_surface),type="string")
    cmds.select(old_name,replace=True)
    recovered = SculptEditor({},applied.append)
    recovered.resume()
    assert not recovered.disk
    recovered.commit()
    assert all(p == (0.,0.,0.) for p in applied[-1]["deltas"])
    recovered.close()
    print("Sculpt editor: first-apply boundary / reopen / tools / legacy migration / draft retention PASS", flush=True)


if __name__ == "__main__":
    try:
        main()
        (root / "native/build/sculpt-editor-result.txt").write_text("PASS\n", encoding="utf-8")
    except Exception:
        (root / "native/build/sculpt-editor-result.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    finally:
        if os.environ.get("BIFROST_SCULPT_GUI_CHECK") == "1":
            cmds.quit(force=True)
        elif os.environ.get("BIFROST_SCALES_MAYA_INITIALIZED") != "1":
            maya.standalone.uninitialize()
