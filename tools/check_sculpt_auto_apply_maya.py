"""Run deferred in an isolated Maya GUI, with the same inputs for manual/auto."""
import json
import os
import sys
import time
import traceback
from pathlib import Path
from statistics import median

from maya import cmds
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "tools"))
if os.environ.get("BIFROST_SCULPT_CHECK_INSTALLED") != "1":
    sys.path.insert(0, str(root / "BifrostScales/scripts"))
from bifrost_scales.sculpt_editor import SculptEditor
from bifrost_scales.qt_compat import QtCore, QtGui, QtWidgets


def settle():
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(350, loop.quit)
    loop.exec()


def mouse(widget, kind, modifiers=QtCore.Qt.NoModifier):
    buttons = QtCore.Qt.LeftButton if kind == QtCore.QEvent.MouseButtonPress else QtCore.Qt.NoButton
    event = QtGui.QMouseEvent(kind, QtCore.QPointF(10, 10), QtCore.QPointF(10, 10),
                             QtCore.Qt.LeftButton, buttons, modifiers)
    QtWidgets.QApplication.sendEvent(widget, event)


def product_path():
    from bifrost_scales.ui import BifrostScalesWindow
    cmds.file(new=True, force=True)
    plugin_loaded_before = cmds.pluginInfo("bifrostGraph", query=True, loaded=True)
    target = cmds.polyPlane(width=4, height=4, subdivisionsX=4, subdivisionsY=4)[0]
    window = BifrostScalesWindow()
    reports = []
    try:
        window.show()
        window.auto_preview_budget.setChecked(False)
        window.target_count.setValue(24)
        window.interactive_budget.setValue(24)
        window.settled_budget.setValue(24)
        window.size.setValue(1.0)
        window.scheduler.request_finished.connect(
            lambda revision, mode, report: reports.append((mode, report))
        )
        cmds.select(target, replace=True)
        window.create_system_button.click()
        assert window.backend.binding is not None, window.log.toPlainText()
        original = window.backend.read_settings()
        preview = window.backend.binding.preview_transform
        initial_vertices = cmds.getAttr(preview+".bsVertexCount")

        window.edit_sculpt.click()
        settle()
        editor = window._sculpt_editor
        editor.run = lambda action: action()
        points = editor.function().getPoints()
        n = editor.surface["resolution"]
        points[(n//2)*(n+1)+n//2].y += .2
        points[(n//2)*(n+1)+n//2].x += .75  # Past the editing disk's .5 radius.
        points[0].x -= .1  # Boundary contact must remain part of one Apply undo.
        editor.function().setPoints(points)
        expected = editor.capture()
        next(button for button in editor.findChildren(QtWidgets.QPushButton)
             if button.text() == "適用").click()
        settle()
        assert window.backend.read_settings().sculpt_surface == expected
        assert window._sculpt_surface == expected
        sculpt_vertices = cmds.getAttr(preview+".bsVertexCount")
        assert sculpt_vertices > initial_vertices
        assert cmds.undoInfo(query=True, undoName=True) == "Bifrost Scales Interior Sculpt"
        cmds.undo()
        settle()
        assert window.backend.read_settings().sculpt_surface == original.sculpt_surface
        assert window._sculpt_surface == original.sculpt_surface
        assert cmds.getAttr(preview+".bsVertexCount") == initial_vertices
        cmds.redo()
        settle()
        assert window.backend.read_settings().sculpt_surface == expected
        assert window._sculpt_surface == expected
        assert cmds.getAttr(preview+".bsVertexCount") == sculpt_vertices

        editor.close()
        window.scale_type_list.setCurrentRow(0)
        window.edit_type_sculpt.click()
        settle()
        editor = window._sculpt_editor
        editor.run = lambda action: action()
        points = editor.function().getPoints()
        points[(n//2)*(n+1)+n//2].z += .75
        editor.function().setPoints(points)
        expected_type = editor.capture()
        next(button for button in editor.findChildren(QtWidgets.QPushButton)
             if button.text() == "適用").click()
        settle()
        stored = window.backend.read_settings()
        assert stored.sculpt_surface == expected
        assert stored.scale_types[0].sculpt_surface == expected_type
        assert len(reports) == 2 and all(mode == "settled" for mode, _report in reports), reports
        settings_node = window.backend.binding.settings_node
        saved_vertices = cmds.getAttr(preview+".bsVertexCount")
        scene = root / "native/build/sculpt-product-roundtrip.mb"
        scene.unlink(missing_ok=True)
        cmds.file(rename=str(scene))
        cmds.file(save=True, type="mayaBinary", force=True)
        cmds.file(new=True, force=True)
        cmds.file(str(scene), open=True, force=True, prompt=False, ignoreVersion=True)
        assert not cmds.ls("BifrostScales_SculptForward*", long=True)
        assert not cmds.ls("BifrostScales_SculptCamera*", long=True)
        window._refresh_systems(preferred=settings_node)
        settle()
        reloaded = window.backend.read_settings()
        assert reloaded.sculpt_surface == expected
        assert reloaded.scale_types[0].sculpt_surface == expected_type
        assert cmds.getAttr(window.backend.binding.preview_transform+".bsVertexCount") == saved_vertices
        window.edit_sculpt.click()
        settle()
        assert window._sculpt_editor.capture() == expected
        window._sculpt_editor.close()
        window.scale_type_list.setCurrentRow(0)
        window.edit_type_sculpt.click()
        settle()
        assert window._sculpt_editor.capture() == expected_type
        return {"settled_evaluations": len(reports), "scales": reports[-1][1].scale_count,
                "vertices": [initial_vertices, sculpt_vertices],
                "save_reload": True,
                "plugin_loaded_before": plugin_loaded_before,
                "plugin_loaded_after": cmds.pluginInfo("bifrostGraph", query=True, loaded=True)}
    finally:
        window.close()
        if window.backend.binding is not None:
            window.backend.delete_system()
        if cmds.objExists(target):
            cmds.delete(target)
        window.deleteLater()
        QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        QtWidgets.QApplication.processEvents()
        cmds.file(new=True, force=True)


def main():
    from check_sculpt_view_maya import main as regression
    regression()
    calls = []
    editor = SculptEditor({}, calls.append)
    editor.run = lambda action: action()
    editor.show()
    QtWidgets.QApplication.processEvents()
    child = QtWidgets.QWidget(editor.view_widget)
    editor.tool("SetMeshSculptTool")
    assert not editor.auto_apply.isChecked()
    rest = editor.function().getPoints()
    changed = editor.function().getPoints()
    changed[544].y += .15
    editor.function().setPoints(changed)
    mouse(child, QtCore.QEvent.MouseButtonPress)
    mouse(child, QtCore.QEvent.MouseButtonRelease)
    settle()
    assert not calls, "Default manual mode must not apply"
    editor.commit()
    expected = calls[-1]
    editor.function().setPoints(rest)
    editor.commit()
    calls.clear()
    editor.auto_apply.setChecked(True)
    for _ in range(3):
        mouse(child, QtCore.QEvent.MouseButtonPress)
        editor.function().setPoints(changed)
        settle()
        assert not calls, "Never apply during a held stroke"
        mouse(child, QtCore.QEvent.MouseButtonRelease)
    settle()
    assert calls == [expected], "Identical input must match manual output; coalesce consecutive releases"
    mouse(child, QtCore.QEvent.MouseButtonPress)
    mouse(child, QtCore.QEvent.MouseButtonRelease)
    settle()
    assert len(calls) == 1, "No-op click must not publish"
    editor.function().setPoints(rest)
    mouse(child, QtCore.QEvent.MouseButtonPress, QtCore.Qt.AltModifier)
    mouse(child, QtCore.QEvent.MouseButtonRelease, QtCore.Qt.AltModifier)
    settle()
    assert len(calls) == 1, "Camera navigation must not apply"
    editor.function().setPoints(changed)
    # Exercise Maya's actual sculpt implementation, not only MFnMesh edits.
    before = editor.points()
    context = cmds.currentCtx()
    cmds.sculptMeshCacheCtx(context, edit=True, size=.2, strength=.1,
                            makeStroke=[(0, 0, 1024, .3, .3), (0, 0, 1026, .3, .3)])
    assert editor.points() != before, "Native brush stroke must deform the patch"
    native_expected = editor.capture()
    mouse(child, QtCore.QEvent.MouseButtonPress)
    mouse(child, QtCore.QEvent.MouseButtonRelease)
    settle()
    assert len(calls) == 2
    assert calls[-1] == native_expected
    # Undo disables auto so the pending publish cannot undo the user's undo.
    mouse(child, QtCore.QEvent.MouseButtonPress)
    mouse(child, QtCore.QEvent.MouseButtonRelease)
    cmds.undo()
    settle()
    assert not editor.auto_apply.isChecked() and len(calls) == 2
    editor.auto_apply.setChecked(True)
    editor.function().setPoints(rest)
    def fail(surface):
        raise ValueError("保存先が変更されています")
    editor.apply_surface = fail
    mouse(child, QtCore.QEvent.MouseButtonPress)
    mouse(child, QtCore.QEvent.MouseButtonRelease)
    settle()
    assert not editor.auto_apply.isChecked() and "保存先" in editor.status.text()
    editor.apply_surface = calls.append
    # Disabling or manually applying cancels the queued automatic duplicate.
    editor.auto_apply.setChecked(True)
    mouse(child, QtCore.QEvent.MouseButtonPress)
    mouse(child, QtCore.QEvent.MouseButtonRelease)
    editor.auto_apply.setChecked(False)
    settle()
    assert len(calls) == 2
    editor.auto_apply.setChecked(True)
    mouse(child, QtCore.QEvent.MouseButtonPress)
    mouse(child, QtCore.QEvent.MouseButtonRelease)
    editor.commit()
    settle()
    assert len(calls) == 3
    editor.auto_apply.setChecked(True)
    mouse(child, QtCore.QEvent.MouseButtonPress)
    mouse(child, QtCore.QEvent.MouseButtonRelease)
    editor.close()
    settle()
    assert len(calls) == 3 and not editor._apply_timer.isActive()
    timings = {}
    for n in (32, 64, 128):
        sample = SculptEditor({"schema": "vector-surface/3", "resolution": n}, calls.append)
        sample.create_or_update()
        durations = []
        for _ in range(3):
            start = time.perf_counter()
            sample.capture()
            durations.append((time.perf_counter() - start) * 1000)
        timings[str(n)] = round(median(durations), 2)
        sample.close()
    product = product_path()
    return {"status": "PASS", "capture_median_ms": timings, "product_path": product,
            "checks": "manual parity, default off, drag zero, coalescing, no-op, camera, native stroke, Undo pause, error pause, close cancellation, Global and Type UI apply"}


if __name__ == "__main__":
    report = root / "native/build/sculpt-auto-result.json"
    try:
        result = main()
    except Exception:
        result = {"status": "FAIL", "error": traceback.format_exc()}
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    cmds.quit(force=True)
