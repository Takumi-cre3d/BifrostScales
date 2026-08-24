from __future__ import annotations

from types import SimpleNamespace

import pytest

from bifrost_scales import draw_context
from bifrost_scales.guides import GuideKind

from fake_maya import FakeCmds


class FakeProjector:
    def __init__(self):
        self.closed = False

    def project(self, x, y):
        if x < 0 or y < 0:
            return None
        return (float(x) * 0.1, 0.0, float(y) * 0.1)

    def close(self):
        self.closed = True


class FakeBackend:
    def __init__(self):
        self.binding = SimpleNamespace(target_mesh="targetShape")
        self.adopted = []

    def adopt_curve_guide(self, kind, curve_transform):
        self.adopted.append((GuideKind(kind), curve_transform))
        return curve_transform


@pytest.fixture(autouse=True)
def _stop_active_draw():
    draw_context.stop_draw(cancel=True, reason="test setup")
    yield
    draw_context.stop_draw(cancel=True, reason="test teardown")


def test_surface_draw_registers_multiple_strokes_without_leaving_the_tool():
    cmds = FakeCmds()
    backend = FakeBackend()
    projector = FakeProjector()
    created = []
    cancelled = []
    states = []

    session = draw_context.start_draw(
        backend,
        GuideKind.DENSITY_CURVE,
        cmds_module=cmds,
        projector=projector,
        on_created=lambda node, kind: created.append((node, kind)),
        on_cancelled=cancelled.append,
        on_state_changed=lambda active, kind: states.append((active, kind)),
        min_screen_distance=4.0,
    )
    context = session.context_name
    assert cmds.currentCtx() == context
    assert draw_context.is_drawing()
    assert cmds.contexts[context]["undoMode"] == "step"
    assert cmds.contexts[context]["stepsCount"] == 1000000

    cmds.set_context_point(context, anchor=(10, 10, 0))
    cmds.trigger_context(context, "press")
    cmds.set_context_point(context, drag=(20, 10, 0))
    cmds.trigger_context(context, "drag")
    # This event is below the four-pixel sampling threshold.
    cmds.set_context_point(context, drag=(22, 10, 0))
    cmds.trigger_context(context, "drag")
    cmds.set_context_point(context, drag=(30, 15, 0))
    cmds.trigger_context(context, "drag")
    cmds.set_context_point(context, drag=(40, 20, 0))
    cmds.trigger_context(context, "release")

    assert len(backend.adopted) == 1
    first_kind, first_curve = backend.adopted[0]
    assert first_kind == GuideKind.DENSITY_CURVE
    assert created == [(first_curve, GuideKind.DENSITY_CURVE)]
    assert cancelled == []
    assert states == [(True, GuideKind.DENSITY_CURVE)]
    first_shapes = cmds.listRelatives(first_curve, shapes=True, type="nurbsCurve")
    first_points = cmds.cv_points[first_shapes[0]]
    assert len(first_points) == 4
    assert first_points[0] == (1.0, 0.0, 1.0)
    assert first_points[-1] == (4.0, 0.0, 2.0)
    assert projector.closed is False
    assert cmds.currentCtx() == context
    assert draw_context.is_drawing()
    assert context in cmds.contexts

    cmds.set_context_point(context, anchor=(50, 30, 0))
    cmds.trigger_context(context, "press")
    cmds.set_context_point(context, drag=(60, 35, 0))
    cmds.trigger_context(context, "drag")
    cmds.set_context_point(context, drag=(70, 40, 0))
    cmds.trigger_context(context, "release")

    assert len(backend.adopted) == 2
    second_kind, second_curve = backend.adopted[1]
    assert second_kind == GuideKind.DENSITY_CURVE
    assert created[-1] == (second_curve, GuideKind.DENSITY_CURVE)
    assert session.created_count == 2
    assert draw_context.is_drawing()
    assert cmds.currentCtx() == context

    draw_context.stop_draw(cancel=True, reason="drawing finished")
    assert cancelled == ["drawing finished"]
    assert states == [
        (True, GuideKind.DENSITY_CURVE),
        (False, GuideKind.DENSITY_CURVE),
    ]
    assert not draw_context.is_drawing()
    # Context destruction is intentionally deferred until Maya's tool-change
    # callback has returned.
    assert context in cmds.contexts
    cmds.run_deferred()
    assert projector.closed is True
    assert cmds.currentCtx() == "selectSuperContext"
    assert context not in cmds.contexts
    assert cmds.objExists(first_curve)
    assert cmds.objExists(second_curve)


def test_surface_draw_cancel_deletes_the_temporary_stroke():
    cmds = FakeCmds()
    backend = FakeBackend()
    projector = FakeProjector()
    cancelled = []

    session = draw_context.start_draw(
        backend,
        GuideKind.DIRECTION_CURVE,
        cmds_module=cmds,
        projector=projector,
        on_cancelled=cancelled.append,
    )
    context = session.context_name
    cmds.set_context_point(context, anchor=(5, 5, 0))
    cmds.trigger_context(context, "press")
    cmds.set_context_point(context, drag=(15, 5, 0))
    cmds.trigger_context(context, "drag")
    temporary = session.preview_curve
    assert temporary and cmds.objExists(temporary)

    draw_context.stop_draw(cancel=True, reason="cancelled by user")

    assert not draw_context.is_drawing()
    assert cmds.objExists(temporary)
    cmds.run_deferred()
    assert not cmds.objExists(temporary)
    assert backend.adopted == []
    assert cancelled == ["cancelled by user"]
    assert projector.closed is True
    assert not draw_context.is_drawing()


def test_surface_draw_requires_two_hits_on_the_target_mesh():
    cmds = FakeCmds()
    backend = FakeBackend()
    projector = FakeProjector()
    cancelled = []

    session = draw_context.start_draw(
        backend,
        GuideKind.DENSITY_CURVE,
        cmds_module=cmds,
        projector=projector,
        on_cancelled=cancelled.append,
    )
    context = session.context_name
    cmds.set_context_point(context, anchor=(-1, -1, 0))
    cmds.trigger_context(context, "press")
    cmds.set_context_point(context, drag=(10, 10, 0))
    cmds.trigger_context(context, "release")

    assert backend.adopted == []
    assert cancelled == []
    assert draw_context.is_drawing()
    assert cmds.currentCtx() == context
    assert projector.closed is False

    # A valid next stroke is accepted without clicking the tool button again.
    cmds.set_context_point(context, anchor=(20, 20, 0))
    cmds.trigger_context(context, "press")
    cmds.set_context_point(context, drag=(30, 20, 0))
    cmds.trigger_context(context, "release")
    assert len(backend.adopted) == 1
    assert draw_context.is_drawing()


def test_maya_mesh_ray_projector_uses_view_ray_and_closest_intersection():
    class Point:
        def __init__(self, x=0.0, y=0.0, z=0.0):
            self.x = float(x)
            self.y = float(y)
            self.z = float(z)

    class Vector(Point):
        def normalize(self):
            length = (self.x * self.x + self.y * self.y + self.z * self.z) ** 0.5
            self.x /= length
            self.y /= length
            self.z /= length

    class PathNode:
        def hasFn(self, _kind):
            return False

    class Path:
        def node(self):
            return PathNode()

    class SelectionList:
        def __init__(self):
            self.values = []

        def add(self, value):
            self.values.append(value)

        def getDagPath(self, index):
            assert self.values[index] == "targetShape"
            return Path()

    class MeshFunction:
        last = None

        def __init__(self, path):
            self.path = path
            self.calls = []
            self.freed = False
            MeshFunction.last = self

        def autoUniformGridParams(self):
            return "acceleration"

        def closestIntersection(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return (Point(1.5, 2.5, 3.5), 1.0, 0, 0, 0.25, 0.75)

        def freeCachedIntersectionAccelerator(self):
            self.freed = True

    class FakeOM:
        MSelectionList = SelectionList
        MFnMesh = MeshFunction
        MPoint = Point
        MVector = Vector
        MFloatPoint = Point
        MFloatVector = Vector

        class MFn:
            kTransform = 1

        class MSpace:
            kWorld = 4

    class View:
        def viewToWorld(self, x, y, source, direction):
            source.x, source.y, source.z = float(x), float(y), 10.0
            direction.x, direction.y, direction.z = 0.0, 0.0, -5.0

    class M3dView:
        @staticmethod
        def active3dView():
            return View()

    class FakeOMUI:
        pass

    FakeOMUI.M3dView = M3dView

    projector = draw_context.MayaMeshRayProjector(
        "targetShape",
        om_module=FakeOM,
        omui_module=FakeOMUI,
    )
    assert projector.project(120, 75) == (1.5, 2.5, 3.5)
    function = MeshFunction.last
    args, kwargs = function.calls[0]
    assert args[2] == FakeOM.MSpace.kWorld
    assert args[4] is False
    assert kwargs["accelParams"] == "acceleration"
    assert kwargs["tolerance"] == 1.0e-6
    projector.close()
    assert function.freed is True


def test_switching_away_from_the_draw_tool_cancels_the_temporary_curve():
    cmds = FakeCmds()
    backend = FakeBackend()
    projector = FakeProjector()
    cancelled = []

    session = draw_context.start_draw(
        backend,
        GuideKind.DENSITY_CURVE,
        cmds_module=cmds,
        projector=projector,
        on_cancelled=cancelled.append,
    )
    context = session.context_name
    cmds.set_context_point(context, anchor=(5, 5, 0))
    cmds.trigger_context(context, "press")
    cmds.set_context_point(context, drag=(15, 5, 0))
    cmds.trigger_context(context, "drag")
    temporary = session.preview_curve
    assert temporary and cmds.objExists(temporary)

    cmds.setToolTo("moveSuperContext")

    assert backend.adopted == []
    assert cmds.objExists(temporary)
    assert context in cmds.contexts
    assert cancelled == ["Guide Curve描画ツールを終了しました"]
    assert not draw_context.is_drawing()
    cmds.run_deferred()
    assert not cmds.objExists(temporary)
    assert context not in cmds.contexts


def test_tool_polling_stops_when_a_context_switch_skips_finalize():
    class NoFinalizeCmds(FakeCmds):
        def setToolTo(self, name):
            self.current_context = str(name)
            return self.current_context

    cmds = NoFinalizeCmds()
    backend = FakeBackend()
    projector = FakeProjector()
    cancelled = []
    session = draw_context.start_draw(
        backend,
        GuideKind.FLOW_CURVE,
        cmds_module=cmds,
        projector=projector,
        on_cancelled=cancelled.append,
    )
    context = session.context_name
    cmds.set_context_point(context, anchor=(5, 5, 0))
    cmds.trigger_context(context, "press")
    cmds.set_context_point(context, drag=(15, 5, 0))
    cmds.trigger_context(context, "drag")
    temporary = session.preview_curve

    cmds.setToolTo("rotateSuperContext")
    assert draw_context.is_drawing()
    assert draw_context.sync_active_tool() is False
    assert not draw_context.is_drawing()
    assert cancelled == [
        "別のMayaツールへ切り替わったためGuide Curve描画を終了しました"
    ]
    cmds.run_deferred()
    assert not cmds.objExists(temporary)
    assert context not in cmds.contexts
    assert projector.closed is True


def test_context_is_never_deleted_inside_maya_finalize_callback():
    class GuardedCmds(FakeCmds):
        def __init__(self):
            super().__init__()
            self.in_finalize = False

        def setToolTo(self, name):
            previous = self.current_context
            self.current_context = str(name)
            if previous != self.current_context and previous in self.contexts:
                callback = self.contexts[previous].get("finalize")
                if callable(callback):
                    self.in_finalize = True
                    try:
                        callback()
                    finally:
                        self.in_finalize = False
            return self.current_context

        def deleteUI(self, name, **kwargs):
            assert not self.in_finalize
            return super().deleteUI(name, **kwargs)

    cmds = GuardedCmds()
    session = draw_context.start_draw(
        FakeBackend(),
        GuideKind.FLOW_CURVE,
        cmds_module=cmds,
        projector=FakeProjector(),
    )
    context = session.context_name
    cmds.setToolTo("moveSuperContext")
    assert context in cmds.contexts
    cmds.run_deferred()
    assert context not in cmds.contexts


def test_each_draw_stroke_is_one_undo_chunk_and_cancel_closes_it():
    cmds = FakeCmds()
    session = draw_context.start_draw(
        FakeBackend(),
        GuideKind.FLOW_CURVE,
        cmds_module=cmds,
        projector=FakeProjector(),
    )
    context = session.context_name
    cmds.set_context_point(context, anchor=(10, 10, 0))
    cmds.trigger_context(context, "press")
    cmds.set_context_point(context, drag=(20, 10, 0))
    cmds.trigger_context(context, "release")
    assert cmds.undo_events == [
        ("open", "Bifrost Scales Draw Guide Curve"),
        ("close", ""),
    ]
    assert cmds.undo_chunk_depth == 0

    cmds.set_context_point(context, anchor=(30, 10, 0))
    cmds.trigger_context(context, "press")
    cmds.set_context_point(context, drag=(40, 10, 0))
    cmds.trigger_context(context, "drag")
    draw_context.stop_draw(cancel=True)
    assert cmds.undo_chunk_depth == 1
    cmds.run_deferred()
    assert cmds.undo_chunk_depth == 0
    assert cmds.undo_events[-1] == ("close", "")


def test_created_callback_failure_does_not_rollback_the_adopted_guide():
    cmds = FakeCmds()
    backend = FakeBackend()
    projector = FakeProjector()
    errors = []

    def broken_callback(_node, _kind):
        raise RuntimeError("UI was already closed")

    session = draw_context.start_draw(
        backend,
        GuideKind.DIRECTION_CURVE,
        cmds_module=cmds,
        projector=projector,
        on_created=broken_callback,
        on_error=errors.append,
    )
    context = session.context_name
    cmds.set_context_point(context, anchor=(10, 10, 0))
    cmds.trigger_context(context, "press")
    cmds.set_context_point(context, drag=(20, 10, 0))
    cmds.trigger_context(context, "release")

    assert len(backend.adopted) == 1
    assert cmds.objExists(backend.adopted[0][1])
    assert errors == []
    assert draw_context.is_drawing()
    assert cmds.currentCtx() == context


def test_failed_tool_activation_removes_the_partial_context():
    class FailingCmds(FakeCmds):
        def setToolTo(self, name):
            if str(name).startswith("bifrostScalesCurveDrawContext_"):
                raise RuntimeError("tool activation failed")
            return super().setToolTo(name)

    cmds = FailingCmds()
    backend = FakeBackend()
    projector = FakeProjector()

    with pytest.raises(RuntimeError, match="tool activation failed"):
        draw_context.start_draw(
            backend,
            GuideKind.DENSITY_CURVE,
            cmds_module=cmds,
            projector=projector,
        )

    assert cmds.contexts == {}
    assert projector.closed is True
    assert not draw_context.is_drawing()


def test_live_preview_curve_is_visible_and_forced_to_refresh_during_drag():
    cmds = FakeCmds()
    backend = FakeBackend()
    session = draw_context.start_draw(
        backend,
        GuideKind.FLOW_CURVE,
        cmds_module=cmds,
        projector=FakeProjector(),
    )
    context = session.context_name
    cmds.set_context_point(context, anchor=(10, 10, 0))
    cmds.trigger_context(context, "press")
    cmds.set_context_point(context, drag=(25, 15, 0))
    cmds.trigger_context(context, "drag")

    assert session.preview_curve
    shape = cmds.listRelatives(
        session.preview_curve, shapes=True, type="nurbsCurve"
    )[0]
    assert cmds.getAttr(shape + ".alwaysDrawOnTop") is True
    assert cmds.getAttr(shape + ".overrideDisplayType") == 0
    assert cmds.getAttr(shape + ".lineWidth") == 4.0
    assert cmds.refresh_count > 0
