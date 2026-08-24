from pathlib import Path
import math

import bifrost_scales.cell_picker_maya as picker_maya


class _Point:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)


class _Vector:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        if hasattr(x, "x"):
            self.x = float(x.x)
            self.y = float(x.y)
            self.z = float(x.z)
        else:
            self.x = float(x)
            self.y = float(y)
            self.z = float(z)

    def length(self):
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)

    def normalize(self):
        length = self.length()
        self.x /= length
        self.y /= length
        self.z /= length


class _View:
    def __init__(self):
        self.calls = []

    def viewToWorld(self, *args):
        self.calls.append(args)
        assert len(args) == 4
        x, y, point, vector = args
        point.x = float(x)
        point.y = float(y)
        point.z = 5.0
        vector.x = 0.0
        vector.y = 0.0
        vector.z = -4.0


class _M3dView:
    view = _View()

    @classmethod
    def active3dView(cls):
        return cls.view


class _Omui:
    M3dView = _M3dView


class _Om:
    MPoint = _Point
    MVector = _Vector


def test_screen_ray_uses_output_argument_view_to_world(monkeypatch):
    monkeypatch.setattr(picker_maya, "omui", _Omui)
    monkeypatch.setattr(picker_maya, "om", _Om)
    provider = object.__new__(picker_maya.MayaCellMetadataProvider)

    origin, direction = provider.screen_ray(23, 47)

    assert origin == (23.0, 47.0, 5.0)
    assert direction == (0.0, 0.0, -1.0)
    assert len(_M3dView.view.calls[-1]) == 4


def test_picker_plugin_declares_python_api_2_contract():
    root = Path(__file__).resolve().parents[1]
    source = (root / "BifrostScales" / "plug-ins" / "bifrostScalesCellPicker.py").read_text(
        encoding="utf-8"
    )
    assert "maya_useNewAPI = True" in source
    assert "def doPtrMoved(self, event, draw_manager, frame_context)" in source
    assert "def doPress(self, event, draw_manager, frame_context)" in source
    assert "def abortAction(self)" in source


def test_picker_source_does_not_use_invalid_two_argument_view_to_world():
    source = Path(picker_maya.__file__).read_text(encoding="utf-8")
    assert "view.viewToWorld(int(x), int(y))" not in source
    assert "view.viewToWorld(int(x), int(y), point, vector)" in source


def test_pointer_callbacks_do_not_submit_overlay_primitives_directly():
    import ast

    root = Path(__file__).resolve().parents[1]
    source = (root / "BifrostScales" / "plug-ins" / "bifrostScalesCellPicker.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    context = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "BifrostScalesCellPickerContext"
    )
    methods = {
        node.name: node
        for node in context.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for name in ("doPtrMoved", "doPress"):
        calls = [
            node
            for node in ast.walk(methods[name])
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_draw"
        ]
        assert calls == []

    feedback_calls = [
        node
        for node in ast.walk(methods["drawFeedback"])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_draw"
    ]
    assert len(feedback_calls) == 1
