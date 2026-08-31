from __future__ import annotations

import maya.api.OpenMaya as om
import maya.api.OpenMayaUI as omui
import maya.api.OpenMayaRender as omr

from bifrost_scales.cell_picker_maya import get_manager

# Maya must pass Python API 2.0 proxy objects to this plug-in.
maya_useNewAPI = True

COMMAND_NAME = "bifrostScalesCellPickerContext"


def _event_position(event):
    """Return Maya port coordinates for an MEvent."""
    value = getattr(event, "position", None)
    if callable(value):
        value = value()
    try:
        return int(value[0]), int(value[1])
    except Exception:
        pass
    getter = getattr(event, "getWindowPosition", None)
    if callable(getter):
        value = getter()
        return int(value[0]), int(value[1])
    raise RuntimeError("Maya did not provide a viewport event position")


def _modifier(event, name):
    value = getattr(event, name, False)
    try:
        return bool(value() if callable(value) else value)
    except Exception:
        return False


def _lifted_outline(manager, record):
    """Return the display outline slightly above the sampled surface.

    The generated Bifrost scale can overlap the source surface.  The actual
    overlay is also submitted in X-ray mode, but a small normal lift avoids
    precision artifacts at coincident positions on all viewport backends.
    """
    points = manager.outline_for(record)
    if not points:
        return []
    normal = record.normal
    lift = max(float(record.radius) * 0.025, float(manager.index.cell_size) * 0.004, 1.0e-5)
    return [
        (
            float(point[0]) + float(normal[0]) * lift,
            float(point[1]) + float(normal[1]) * lift,
            float(point[2]) + float(normal[2]) * lift,
        )
        for point in points
    ]


def _line_point_array(points):
    """Build an explicit MPointArray containing independent line segments."""
    result = om.MPointArray()
    for index in range(max(0, len(points) - 1)):
        a = points[index]
        b = points[index + 1]
        result.append(om.MPoint(float(a[0]), float(a[1]), float(a[2])))
        result.append(om.MPoint(float(b[0]), float(b[1]), float(b[2])))
    return result


def _center_point_array(record):
    result = om.MPointArray()
    lift = max(float(record.radius) * 0.03, 1.0e-5)
    result.append(
        om.MPoint(
            float(record.center[0]) + float(record.normal[0]) * lift,
            float(record.center[1]) + float(record.normal[1]) * lift,
            float(record.center[2]) + float(record.normal[2]) * lift,
        )
    )
    return result


class BifrostScalesCellPickerContext(omui.MPxContext):
    def __init__(self):
        super().__init__()
        self.setTitleString("Bifrost Scales Cell Picker")
        self.setHelpString(
            "Hover to highlight. Click to select. Shift adds. Ctrl removes. Esc exits."
        )
        try:
            self.setCursor(omui.MCursor.crossHairCursor)
        except Exception:
            pass

    def stringClassName(self):
        return "bifrostScalesCellPicker"

    def toolOnSetup(self, event):
        try:
            super().toolOnSetup(event)
        except Exception:
            pass
        manager = get_manager()
        manager.enabled = True
        manager.clear_interaction_error()
        manager.clear_draw_error()
        manager.notify()

    def toolOffCleanup(self):
        manager = get_manager()
        manager.enabled = False
        manager.hover = None
        manager.notify()
        try:
            super().toolOffCleanup()
        except Exception:
            pass

    def abortAction(self):
        try:
            get_manager().disable()
        except Exception as exc:
            get_manager().report_interaction_error("abort", exc)

    def _draw(self, draw_manager, *, feedback=False):
        """Submit hover/selection overlays through the VP2 draw manager.

        MUIDrawManager.lineStrip expects MPointArray and may be depth-tested
        against the generated Bifrost geometry.  We therefore submit explicit
        kLines meshes in X-ray mode, which Autodesk documents as the supported
        always-on-top path for kLines/kTriangles/kPoints.
        """
        if draw_manager is None:
            return
        manager = get_manager()
        if feedback:
            manager.note_draw_feedback()

        entries = []
        for record in manager.current_records():
            entries.append((record, om.MColor((0.10, 0.90, 1.00, 1.0)), 3.0, 7.0))
        if manager.hover is not None and manager.hover.cell_id not in manager.selected_ids:
            entries.append((manager.hover, om.MColor((1.00, 0.55, 0.05, 1.0)), 2.5, 6.0))

        if not entries:
            manager.note_draw_submit(0)
            return

        began_drawable = False
        began_xray = False
        primitive_count = 0
        manager.clear_draw_error()
        try:
            draw_manager.beginDrawable(omr.MUIDrawManager.kNonSelectable)
            began_drawable = True
            draw_manager.beginDrawInXray()
            began_xray = True
            for record, color, line_width, point_size in entries:
                outline = _lifted_outline(manager, record)
                line_points = _line_point_array(outline)
                if len(line_points) >= 2:
                    draw_manager.setColor(color)
                    draw_manager.setLineWidth(float(line_width))
                    draw_manager.mesh(omr.MUIDrawManager.kLines, line_points)
                    primitive_count += 1
                center_points = _center_point_array(record)
                draw_manager.setColor(color)
                draw_manager.setPointSize(float(point_size))
                draw_manager.mesh(omr.MUIDrawManager.kPoints, center_points)
                primitive_count += 1
        except Exception as exc:
            manager.report_draw_error("viewport overlay", exc)
        finally:
            if began_xray:
                try:
                    draw_manager.endDrawInXray()
                except Exception as exc:
                    manager.report_draw_error("end xray", exc)
            if began_drawable:
                try:
                    draw_manager.endDrawable()
                except Exception as exc:
                    manager.report_draw_error("end drawable", exc)
            manager.note_draw_submit(primitive_count)

    def doPtrMoved(self, event, draw_manager, frame_context):
        # Pointer events update only the logical hover state.  Submitting
        # MUIDrawManager primitives here as well as from drawFeedback leaves
        # orphaned immediate-mode commands behind on some Maya 2026 viewport
        # refresh paths (camera tumble, selection replacement, tool exit).
        # drawFeedback is the sole owner of overlay submission.
        del draw_manager
        del frame_context
        manager = get_manager()
        try:
            x, y = _event_position(event)
            manager.hover_at(x, y)
        except Exception as exc:
            manager.report_interaction_error("pointer move", exc)

    def doPress(self, event, draw_manager, frame_context):
        del draw_manager
        del frame_context
        manager = get_manager()
        try:
            x, y = _event_position(event)
            manager.hover_at(x, y)
            manager.click_hover(
                shift=_modifier(event, "isModifierShift"),
                control=_modifier(event, "isModifierControl"),
            )
        except Exception as exc:
            manager.report_interaction_error("click", exc)

    # Autodesk's Python API reference lists an event/draw-manager/frame-context
    # callback, while the Maya 2026 runtime can dispatch only draw-manager and
    # frame-context for this override. Optional arguments keep both wrappers
    # compatible without raising an exception every viewport refresh.
    def drawFeedback(
        self,
        event_or_draw_manager,
        draw_manager_or_context=None,
        frame_context=None,
    ):
        if frame_context is None:
            draw_manager = event_or_draw_manager
            frame_context = draw_manager_or_context
        else:
            draw_manager = draw_manager_or_context
        del frame_context
        self._draw(draw_manager, feedback=True)


class BifrostScalesCellPickerContextCommand(omui.MPxContextCommand):
    @staticmethod
    def creator():
        return BifrostScalesCellPickerContextCommand()

    def makeObj(self):
        return BifrostScalesCellPickerContext()


def initializePlugin(plugin):
    fn = om.MFnPlugin(plugin, "Bifrost Scales", "0.10.9", "Any")
    fn.registerContextCommand(
        COMMAND_NAME, BifrostScalesCellPickerContextCommand.creator
    )


def uninitializePlugin(plugin):
    try:
        get_manager().disable(restore_tool=False)
    except Exception:
        pass
    fn = om.MFnPlugin(plugin)
    fn.deregisterContextCommand(COMMAND_NAME)
