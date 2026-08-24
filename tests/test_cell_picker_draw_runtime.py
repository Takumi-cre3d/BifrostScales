from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types

from bifrost_scales.cell_picker_core import CellPickRecord, SpatialCellIndex
import bifrost_scales.cell_picker_maya as picker_maya


class _Point:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)


class _PointArray:
    def __init__(self):
        self.values = []

    def append(self, value):
        assert isinstance(value, _Point)
        self.values.append(value)

    def __len__(self):
        return len(self.values)


class _Color:
    def __init__(self, value):
        self.value = tuple(value)


class _BaseContext:
    def __init__(self):
        pass

    def setTitleString(self, _value):
        pass

    def setHelpString(self, _value):
        pass

    def setCursor(self, _value):
        pass


class _BaseContextCommand:
    def __init__(self):
        pass


class _Cursor:
    crossHairCursor = 1


class _DrawConstants:
    kNonSelectable = 11
    kLines = 12
    kPoints = 13


class _DrawManager:
    def __init__(self):
        self.calls = []

    def beginDrawable(self, selectability):
        self.calls.append(("beginDrawable", selectability))

    def endDrawable(self):
        self.calls.append(("endDrawable",))

    def beginDrawInXray(self):
        self.calls.append(("beginDrawInXray",))

    def endDrawInXray(self):
        self.calls.append(("endDrawInXray",))

    def setColor(self, color):
        self.calls.append(("setColor", color.value))

    def setLineWidth(self, value):
        self.calls.append(("setLineWidth", value))

    def setPointSize(self, value):
        self.calls.append(("setPointSize", value))

    def mesh(self, mode, points):
        assert isinstance(points, _PointArray)
        self.calls.append(("mesh", mode, len(points)))


class _Manager(picker_maya.CellPickerManager):
    def __init__(self):
        super().__init__()
        record = CellPickRecord(
            "0000000000000001",
            0,
            (0.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            1.0,
            (
                (-1.0, 0.0, -1.0),
                (1.0, 0.0, -1.0),
                (1.0, 0.0, 1.0),
                (-1.0, 0.0, 1.0),
            ),
        )
        self.index = SpatialCellIndex.build([record])
        self.selected_ids = [record.cell_id]


def _load_picker_plugin(monkeypatch, manager):
    maya = types.ModuleType("maya")
    api = types.ModuleType("maya.api")
    om = types.ModuleType("maya.api.OpenMaya")
    om.MPoint = _Point
    om.MPointArray = _PointArray
    om.MColor = _Color
    om.MFnPlugin = object
    omui = types.ModuleType("maya.api.OpenMayaUI")
    omui.MPxContext = _BaseContext
    omui.MPxContextCommand = _BaseContextCommand
    omui.MCursor = _Cursor
    omr = types.ModuleType("maya.api.OpenMayaRender")
    omr.MUIDrawManager = _DrawConstants
    maya.api = api
    api.OpenMaya = om
    api.OpenMayaUI = omui
    api.OpenMayaRender = omr
    monkeypatch.setitem(sys.modules, "maya", maya)
    monkeypatch.setitem(sys.modules, "maya.api", api)
    monkeypatch.setitem(sys.modules, "maya.api.OpenMaya", om)
    monkeypatch.setitem(sys.modules, "maya.api.OpenMayaUI", omui)
    monkeypatch.setitem(sys.modules, "maya.api.OpenMayaRender", omr)
    monkeypatch.setattr(picker_maya, "get_manager", lambda: manager)

    path = (
        Path(__file__).resolve().parents[1]
        / "BifrostScales"
        / "plug-ins"
        / "bifrostScalesCellPicker.py"
    )
    spec = importlib.util.spec_from_file_location("_bifrost_scales_picker_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module.get_manager = lambda: manager
    return module


def _assert_overlay_drawn(draw_manager, manager):
    assert ("beginDrawable", _DrawConstants.kNonSelectable) in draw_manager.calls
    assert ("beginDrawInXray",) in draw_manager.calls
    assert any(call[0] == "mesh" and call[1] == _DrawConstants.kLines for call in draw_manager.calls)
    assert any(call[0] == "mesh" and call[1] == _DrawConstants.kPoints for call in draw_manager.calls)
    assert ("endDrawInXray",) in draw_manager.calls
    assert ("endDrawable",) in draw_manager.calls
    assert manager.draw_feedback_count == 1
    assert manager.draw_primitive_count == 2
    assert manager.last_draw_error == ""


def test_draw_feedback_accepts_live_two_argument_dispatch(monkeypatch):
    manager = _Manager()
    module = _load_picker_plugin(monkeypatch, manager)
    context = module.BifrostScalesCellPickerContext()
    draw_manager = _DrawManager()

    context.drawFeedback(draw_manager, object())

    _assert_overlay_drawn(draw_manager, manager)


def test_draw_feedback_accepts_documented_three_argument_dispatch(monkeypatch):
    manager = _Manager()
    module = _load_picker_plugin(monkeypatch, manager)
    context = module.BifrostScalesCellPickerContext()
    draw_manager = _DrawManager()

    context.drawFeedback(object(), draw_manager, object())

    _assert_overlay_drawn(draw_manager, manager)


def test_draw_failure_does_not_clear_selection(monkeypatch):
    manager = _Manager()
    module = _load_picker_plugin(monkeypatch, manager)
    context = module.BifrostScalesCellPickerContext()

    class _FailingDrawManager(_DrawManager):
        def mesh(self, mode, points):
            raise RuntimeError("simulated viewport draw failure")

    context.drawFeedback(object(), _FailingDrawManager(), object())

    assert manager.selected_ids == ["0000000000000001"]
    assert "simulated viewport draw failure" in manager.last_draw_error
