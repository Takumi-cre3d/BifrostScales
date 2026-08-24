"""Interactive surface-curve drawing for Bifrost Scales guides.

The context is intentionally owned by this standalone package.  It projects
viewport mouse positions onto the bound target mesh, displays a live linear
NURBS stroke, and adopts that stroke as an owned guide when the mouse is
released.
"""

from __future__ import annotations

import math
import uuid
from typing import Any, Callable, Protocol

from .guides import GuideKind

Vec3 = tuple[float, float, float]
CreatedCallback = Callable[[str, GuideKind], None]
StateCallback = Callable[[bool, GuideKind], None]
MessageCallback = Callable[[str], None]


class SurfaceProjector(Protocol):
    def project(self, x: int, y: int) -> Vec3 | None:
        """Project one viewport pixel onto the target surface."""

    def close(self) -> None:
        """Release any host-side acceleration data."""


class MayaMeshRayProjector:
    """Convert viewport pixels to target-mesh intersections with Maya API 2.0."""

    def __init__(
        self,
        target_mesh: str,
        om_module: Any | None = None,
        omui_module: Any | None = None,
        max_distance: float = 1.0e10,
    ) -> None:
        if om_module is None:
            import maya.api.OpenMaya as om_module  # type: ignore
        if omui_module is None:
            import maya.api.OpenMayaUI as omui_module  # type: ignore
        self.om = om_module
        self.omui = omui_module
        self.max_distance = float(max_distance)
        selection = self.om.MSelectionList()
        selection.add(str(target_mesh))
        path = selection.getDagPath(0)
        try:
            if path.node().hasFn(self.om.MFn.kTransform):
                path.extendToShape()
        except Exception:
            pass
        self.path = path
        self.function = self.om.MFnMesh(path)
        try:
            self.acceleration = self.function.autoUniformGridParams()
        except Exception:
            self.acceleration = None
        self._closed = False

    def project(self, x: int, y: int) -> Vec3 | None:
        if self._closed:
            return None
        view = self.omui.M3dView.active3dView()
        source = self.om.MPoint()
        direction = self.om.MVector()
        view.viewToWorld(int(x), int(y), source, direction)
        try:
            direction.normalize()
        except Exception:
            length = math.sqrt(
                float(direction.x) ** 2
                + float(direction.y) ** 2
                + float(direction.z) ** 2
            )
            if length <= 1.0e-12:
                return None
            direction = self.om.MVector(
                float(direction.x) / length,
                float(direction.y) / length,
                float(direction.z) / length,
            )
        ray_source = self.om.MFloatPoint(
            float(source.x),
            float(source.y),
            float(source.z),
        )
        ray_direction = self.om.MFloatVector(
            float(direction.x),
            float(direction.y),
            float(direction.z),
        )
        arguments = (
            ray_source,
            ray_direction,
            self.om.MSpace.kWorld,
            self.max_distance,
            False,
        )
        try:
            if self.acceleration is None:
                hit = self.function.closestIntersection(*arguments)
            else:
                hit = self.function.closestIntersection(
                    *arguments,
                    accelParams=self.acceleration,
                    tolerance=1.0e-6,
                )
        except (RuntimeError, ValueError):
            return None
        except TypeError:
            # Some Maya Python builds expose the same API with positional-only
            # optional arguments.  Falling back without the accelerator keeps
            # the drawing tool usable rather than failing the entire stroke.
            try:
                hit = self.function.closestIntersection(*arguments)
            except (RuntimeError, ValueError):
                return None
        if not hit:
            return None
        point = hit[0]
        return (float(point.x), float(point.y), float(point.z))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.acceleration is not None:
            try:
                self.function.freeCachedIntersectionAccelerator()
            except Exception:
                pass


def _distance_squared_2d(a: tuple[int, int], b: tuple[int, int]) -> float:
    return float((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def _distance_squared_3d(a: Vec3, b: Vec3) -> float:
    return float(
        (a[0] - b[0]) ** 2
        + (a[1] - b[1]) ** 2
        + (a[2] - b[2]) ** 2
    )


class SurfaceCurveDrawSession:
    """Persistent target-surface guide drawing tool.

    Each press-drag-release sequence registers one owned guide while this
    Maya tool context remains active for the next stroke.
    """

    def __init__(
        self,
        backend: Any,
        kind: GuideKind | str,
        cmds_module: Any | None = None,
        projector: SurfaceProjector | None = None,
        on_created: CreatedCallback | None = None,
        on_cancelled: MessageCallback | None = None,
        on_error: MessageCallback | None = None,
        on_state_changed: StateCallback | None = None,
        min_screen_distance: float = 4.0,
        max_points: int = 512,
    ) -> None:
        if cmds_module is None:
            import maya.cmds as cmds_module  # type: ignore
        self.cmds = cmds_module
        self.backend = backend
        self.kind = GuideKind(kind)
        if not self.kind.is_curve:
            raise ValueError("Surface drawing requires a curve guide kind")
        binding = getattr(backend, "binding", None)
        if binding is None:
            raise ValueError("Systemを先に作成してください")
        target_mesh = str(getattr(binding, "target_mesh", "") or "")
        if not target_mesh:
            raise ValueError("SystemにTarget Meshがありません")
        self.projector = projector or MayaMeshRayProjector(target_mesh)
        self.on_created = on_created
        self.on_cancelled = on_cancelled
        self.on_error = on_error
        self.on_state_changed = on_state_changed
        self.min_screen_distance_sq = max(0.0, float(min_screen_distance)) ** 2
        self.max_points = max(2, min(4096, int(max_points)))
        self.context_name = "bifrostScalesCurveDrawContext_{}".format(
            uuid.uuid4().hex[:10]
        )
        self.previous_context = ""
        self.points: list[Vec3] = []
        self.screen_points: list[tuple[int, int]] = []
        self.preview_curve = ""
        self.started = False
        self.stopping = False
        self.created_count = 0
        self._pressed = False
        self._cleanup_scheduled = False
        self._cleanup_complete = False
        self._stroke_undo_open = False
        self._stroke_undo_owner = ""

    def start(self) -> "SurfaceCurveDrawSession":
        if self.started:
            return self
        try:
            if hasattr(self.cmds, "currentCtx"):
                self.previous_context = str(self.cmds.currentCtx() or "")
            self.cmds.draggerContext(
                self.context_name,
                pressCommand=self._on_press,
                dragCommand=self._on_drag,
                releaseCommand=self._on_release,
                finalize=self._on_finalize,
                cursor="crossHair",
                space="screen",
                projection="viewPlane",
                stepsCount=1000000,
                undoMode="step",
                helpString=(
                    "Target Mesh上をドラッグ。マウスを離すたびにGuide Curveを登録。"
                    "Qまたは他のツールへ切り替えると終了。"
                ),
            )
            self.started = True
            self.cmds.setToolTo(self.context_name)
            self._set_draw_string(
                "Target Mesh上をドラッグ。ストロークごとにGuideを登録"
            )
            self._notify(self.on_state_changed, True, self.kind)
            return self
        except Exception:
            self._cleanup_failed_start()
            raise

    def stop(
        self,
        cancel: bool = True,
        restore_tool: bool = True,
        reason: str = "Guide Curve描画ツールを終了しました",
        defer_cleanup: bool = True,
    ) -> None:
        """Stop the tool without destroying its Maya context in ``finalize``.

        Maya can invoke a dragger-context ``finalize`` callback while its tool
        manager is still changing contexts.  Deleting that same context from
        inside the callback is unsafe in some Maya builds.  State/callbacks are
        therefore updated immediately, while destructive host cleanup is
        deferred until the tool-manager callback has returned.
        """

        if self.stopping:
            return
        self.stopping = True
        self.started = False
        self._pressed = False
        _clear_active(self)
        if cancel:
            self._notify(self.on_cancelled, reason)
        self._notify(self.on_state_changed, False, self.kind)
        try:
            if restore_tool and self.previous_context and hasattr(self.cmds, "setToolTo"):
                try:
                    current = (
                        str(self.cmds.currentCtx() or "")
                        if hasattr(self.cmds, "currentCtx")
                        else ""
                    )
                    if not current or current == self.context_name:
                        self.cmds.setToolTo(self.previous_context)
                except Exception:
                    pass
        finally:
            self._schedule_stop_cleanup(defer=defer_cleanup)

    def sync_active_tool(self) -> bool:
        """Stop safely when Maya changed tools without calling ``finalize``."""

        if not self.started or self.stopping:
            return False
        if not hasattr(self.cmds, "currentCtx"):
            return True
        try:
            current = str(self.cmds.currentCtx() or "")
        except Exception:
            return True
        if current == self.context_name:
            return True
        self.stop(
            cancel=True,
            restore_tool=False,
            reason="別のMayaツールへ切り替わったためGuide Curve描画を終了しました",
            defer_cleanup=True,
        )
        return False

    def _on_press(self, *_args: Any) -> None:
        try:
            self._discard_current_stroke()
            self._end_stroke_undo()
            self._begin_stroke_undo()
            self._pressed = True
            x, y = self._query_screen_point(anchor=True)
            if self._record(x, y, force=True):
                self._set_draw_string("ドラッグ中: Guide Curveを描画")
            else:
                self._set_draw_string("Target Mesh上から開始してください")
        except Exception as exc:
            self._fail(exc)

    def _on_drag(self, *_args: Any) -> None:
        if not self._pressed or self.stopping:
            return
        try:
            x, y = self._query_screen_point(anchor=False)
            if self._record(x, y):
                self._set_draw_string("Guide points: {}".format(len(self.points)))
        except Exception as exc:
            self._fail(exc)

    def _on_release(self, *_args: Any) -> None:
        if not self._pressed or self.stopping:
            return
        try:
            x, y = self._query_screen_point(anchor=False)
            self._record(x, y, force=True)
            if len(self.points) < 2 or not self.preview_curve:
                self._discard_current_stroke()
                self._end_stroke_undo()
                self._set_draw_string(
                    "Target Mesh上をドラッグして2点以上入力してください"
                )
                return
            node = str(self.backend.adopt_curve_guide(self.kind, self.preview_curve))
            self.preview_curve = ""
            self.points = []
            self.screen_points = []
            self._pressed = False
            self.created_count += 1
        except Exception as exc:
            self._fail(exc)
            return
        self._end_stroke_undo()
        self._notify(self.on_created, node, self.kind)
        self._set_draw_string(
            "Guide Curveを登録しました ({})。続けて描画できます".format(
                self.created_count
            )
        )

    def _on_finalize(self, *_args: Any) -> None:
        if self.stopping:
            return
        self.stop(
            cancel=True,
            restore_tool=False,
            reason="Guide Curve描画ツールを終了しました",
            defer_cleanup=True,
        )

    def _query_screen_point(self, anchor: bool) -> tuple[int, int]:
        query_flag = {"anchorPoint": True} if anchor else {"dragPoint": True}
        values = self.cmds.draggerContext(
            self.context_name,
            query=True,
            **query_flag,
        )
        if values is None or len(values) < 2:
            raise RuntimeError("Viewport pointer position could not be read")
        return int(round(float(values[0]))), int(round(float(values[1])))

    def _record(self, x: int, y: int, force: bool = False) -> bool:
        if len(self.points) >= self.max_points:
            return False
        screen = (int(x), int(y))
        if (
            not force
            and self.screen_points
            and _distance_squared_2d(screen, self.screen_points[-1])
            < self.min_screen_distance_sq
        ):
            return False
        point = self.projector.project(screen[0], screen[1])
        if point is None:
            return False
        normalized = (float(point[0]), float(point[1]), float(point[2]))
        if self.points and _distance_squared_3d(normalized, self.points[-1]) <= 1.0e-16:
            return False
        self.points.append(normalized)
        self.screen_points.append(screen)
        self._update_preview_curve()
        return True

    def _update_preview_curve(self) -> None:
        if len(self.points) < 2:
            return
        if self.preview_curve and self.cmds.objExists(self.preview_curve):
            result = self.cmds.curve(
                self.preview_curve,
                replace=True,
                degree=1,
                point=list(self.points),
                worldSpace=True,
            )
            if result:
                self.preview_curve = str(result)
        else:
            if self.kind == GuideKind.FLOW_CURVE:
                name = "bifrostScalesFlowCurveGuide#"
            elif self.kind.stage == "density":
                name = "bifrostScalesDensityCurveGuide#"
            else:
                name = "bifrostScalesDirectionCurveGuide#"
            self.preview_curve = str(
                self.cmds.curve(
                    degree=1,
                    point=list(self.points),
                    worldSpace=True,
                    name=name,
                )
            )
            self._style_preview_curve()
        self._schedule_refresh()

    def _style_preview_curve(self) -> None:
        if not self.preview_curve or not self.cmds.objExists(self.preview_curve):
            return
        shapes = self.cmds.listRelatives(
            self.preview_curve,
            shapes=True,
            noIntermediate=True,
            fullPath=True,
            type="nurbsCurve",
        ) or []
        if self.kind == GuideKind.FLOW_CURVE:
            color = (0.15, 0.85, 0.85)
        elif self.kind.stage == "density":
            color = (0.2, 0.85, 0.35)
        else:
            color = (0.2, 0.55, 1.0)
        for shape in shapes:
            for plug, value, kwargs in (
                (shape + ".overrideEnabled", True, {}),
                (shape + ".overrideRGBColors", True, {}),
                (shape + ".overrideColorRGB", color, {"type": "double3"}),
                (shape + ".overrideDisplayType", 0, {}),
                (shape + ".alwaysDrawOnTop", True, {}),
                (shape + ".lineWidth", 4.0, {}),
            ):
                try:
                    if isinstance(value, tuple):
                        self.cmds.setAttr(plug, *value, **kwargs)
                    else:
                        self.cmds.setAttr(plug, value, **kwargs)
                except Exception:
                    pass

    def _discard_current_stroke(self) -> None:
        """Delete only the unfinished stroke and keep registered guides."""

        self._delete_preview_curve()
        self.points = []
        self.screen_points = []
        self._pressed = False

    def _delete_preview_curve(self) -> None:
        if self.preview_curve and self.cmds.objExists(self.preview_curve):
            try:
                self.cmds.delete(self.preview_curve)
            except Exception:
                pass
        self.preview_curve = ""

    def _set_draw_string(self, text: str) -> None:
        try:
            self.cmds.draggerContext(
                self.context_name,
                edit=True,
                drawString=str(text),
            )
        except Exception:
            pass

    def _schedule_refresh(self) -> None:
        try:
            self.projector.omui.M3dView.scheduleRefreshAllViews()  # type: ignore[attr-defined]
            return
        except Exception:
            pass
        try:
            self.cmds.refresh(currentView=True, force=True)
        except Exception:
            pass

    def _close_projector(self) -> None:
        try:
            self.projector.close()
        except Exception:
            pass

    def _begin_stroke_undo(self) -> None:
        if self._stroke_undo_open:
            return
        begin = getattr(self.backend, "begin_undo_chunk", None)
        if callable(begin):
            try:
                begin("Bifrost Scales Draw Guide Curve")
                self._stroke_undo_open = True
                self._stroke_undo_owner = "backend"
                return
            except Exception:
                pass
        try:
            self.cmds.undoInfo(
                openChunk=True,
                chunkName="Bifrost Scales Draw Guide Curve",
            )
        except TypeError:
            try:
                self.cmds.undoInfo(openChunk=True)
            except Exception:
                return
        except Exception:
            return
        self._stroke_undo_open = True
        self._stroke_undo_owner = "cmds"

    def _end_stroke_undo(self) -> None:
        if not self._stroke_undo_open:
            return
        owner = self._stroke_undo_owner
        self._stroke_undo_open = False
        self._stroke_undo_owner = ""
        if owner == "backend":
            end = getattr(self.backend, "end_undo_chunk", None)
            if callable(end):
                try:
                    end()
                    return
                except Exception:
                    pass
        try:
            self.cmds.undoInfo(closeChunk=True)
        except Exception:
            pass

    def _schedule_stop_cleanup(self, defer: bool) -> None:
        if self._cleanup_scheduled or self._cleanup_complete:
            return
        self._cleanup_scheduled = True

        def cleanup() -> None:
            self._cleanup_scheduled = False
            self._finish_stop_cleanup()

        if defer:
            try:
                import maya.utils as maya_utils  # type: ignore

                maya_utils.executeDeferred(cleanup)
                return
            except Exception:
                pass
            try:
                eval_deferred = getattr(self.cmds, "evalDeferred")
                eval_deferred(cleanup)
                return
            except Exception:
                pass
        cleanup()

    def _finish_stop_cleanup(self) -> None:
        if self._cleanup_complete:
            return
        self._cleanup_complete = True
        try:
            self._discard_current_stroke()
        finally:
            self._end_stroke_undo()
            self._close_projector()
            try:
                if hasattr(self.cmds, "deleteUI"):
                    self.cmds.deleteUI(self.context_name, toolContext=True)
            except Exception:
                pass

    def _cleanup_failed_start(self) -> None:
        """Remove a partially-created context without emitting user callbacks."""

        self._delete_preview_curve()
        self._end_stroke_undo()
        self._close_projector()
        try:
            current = (
                str(self.cmds.currentCtx() or "")
                if hasattr(self.cmds, "currentCtx")
                else ""
            )
            if (
                current == self.context_name
                and self.previous_context
                and hasattr(self.cmds, "setToolTo")
            ):
                self.cmds.setToolTo(self.previous_context)
        except Exception:
            pass
        try:
            if hasattr(self.cmds, "deleteUI"):
                self.cmds.deleteUI(self.context_name, toolContext=True)
        except Exception:
            pass
        self.started = False
        self._pressed = False
        _clear_active(self)

    def _notify(self, callback: Callable[..., Any] | None, *args: Any) -> None:
        """Run a UI callback without allowing it to corrupt host state."""

        if callback is None:
            return
        try:
            callback(*args)
        except Exception as exc:
            message = "Bifrost Scales callback failed: {}: {}".format(
                type(exc).__name__, exc
            )
            try:
                self.cmds.warning(message)
            except Exception:
                print(message)

    def _fail(self, exc: Exception) -> None:
        message = "{}: {}".format(type(exc).__name__, exc)
        self._notify(self.on_error, message)
        self.stop(
            cancel=True,
            restore_tool=True,
            reason="Guide Curve描画に失敗しました",
            defer_cleanup=True,
        )


_ACTIVE_SESSION: SurfaceCurveDrawSession | None = None


def _clear_active(session: SurfaceCurveDrawSession) -> None:
    global _ACTIVE_SESSION
    if _ACTIVE_SESSION is session:
        _ACTIVE_SESSION = None


def start_draw(
    backend: Any,
    kind: GuideKind | str,
    **kwargs: Any,
) -> SurfaceCurveDrawSession:
    """Activate a persistent target-surface guide drawing context."""

    global _ACTIVE_SESSION
    stop_draw(cancel=True, reason="新しいGuide Curve描画へ切り替えました")
    session = SurfaceCurveDrawSession(backend=backend, kind=kind, **kwargs)
    _ACTIVE_SESSION = session
    try:
        return session.start()
    except Exception:
        _clear_active(session)
        raise


def stop_draw(
    cancel: bool = True,
    reason: str = "Guide Curve描画ツールを終了しました",
) -> None:
    """Stop the active drawing context, if any."""

    session = _ACTIVE_SESSION
    if session is not None:
        session.stop(cancel=cancel, restore_tool=True, reason=reason)


def sync_active_tool() -> bool:
    """Synchronize the active draw session with Maya's current tool.

    This polling fallback covers hosts or third-party contexts that switch
    tools without invoking the dragger context's ``finalize`` callback.
    """

    session = _ACTIVE_SESSION
    if session is None:
        return False
    return session.sync_active_tool()


def is_drawing() -> bool:
    return bool(_ACTIVE_SESSION is not None and _ACTIVE_SESSION.started)


def active_kind() -> GuideKind | None:
    return _ACTIVE_SESSION.kind if _ACTIVE_SESSION is not None else None
