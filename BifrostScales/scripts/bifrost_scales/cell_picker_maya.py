from __future__ import annotations

import json
import math
from pathlib import Path
import weakref
import sys
from typing import Any, Callable, Mapping, Optional, Sequence

from .cell_picker_core import (
    CellPickRecord,
    SpatialCellIndex,
    find_metadata_list,
    find_scale_count,
    revision_from_payload,
    set_query_indices,
    approximate_voronoi_outline,
)

try:
    import maya.cmds as cmds
    import maya.mel as mel
    import maya.api.OpenMaya as om
    import maya.api.OpenMayaUI as omui
    MAYA_AVAILABLE = True
except Exception:
    cmds = mel = om = omui = None
    MAYA_AVAILABLE = False

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except Exception:
    try:
        from PySide2 import QtCore, QtGui, QtWidgets
    except Exception:
        QtCore = QtGui = QtWidgets = None

_CONTEXT_COMMAND = "bifrostScalesCellPickerContext"
_CONTEXT_PREFIX = "bifrostScalesCellPickerContext"
_PLUGIN_FILE = "bifrostScalesCellPicker.py"


def _json_load(text: Any) -> dict[str, Any]:
    if isinstance(text, dict):
        return dict(text)
    try:
        value = json.loads(str(text or "{}"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _attr_exists(node: str, attr: str) -> bool:
    try:
        return bool(cmds.attributeQuery(attr, node=node, exists=True))
    except Exception:
        return False


def _get_string(node: str, attr: str) -> str:
    try:
        return str(cmds.getAttr(f"{node}.{attr}") or "")
    except Exception:
        return ""


def _set_string(node: str, attr: str, value: str) -> None:
    cmds.setAttr(f"{node}.{attr}", value, type="string")


def _visible(node: str) -> bool:
    try:
        parent = cmds.listRelatives(node, parent=True, fullPath=True) or []
        target = parent[0] if parent else node
        return bool(cmds.getAttr(f"{target}.visibility"))
    except Exception:
        return True


def _candidate_graphs() -> list[str]:
    result: list[str] = []
    for node_type in ("bifrostGraphShape", "bifrostBoard"):
        try:
            result.extend(cmds.ls(type=node_type, long=True) or [])
        except Exception:
            pass
    if not result:
        for node in cmds.ls(long=True) or []:
            if _attr_exists(node, "payload_json") and _attr_exists(node, "profile_json"):
                result.append(node)
    selected = set(cmds.ls(selection=True, long=True) or [])
    scored = []
    seen = set()
    for node in result:
        if node in seen or not _attr_exists(node, "payload_json") or not _attr_exists(node, "profile_json"):
            continue
        seen.add(node)
        profile = _json_load(_get_string(node, "profile_json"))
        count = find_scale_count(profile)
        parent = (cmds.listRelatives(node, parent=True, fullPath=True) or [""])[0]
        selection_match = int(node in selected or parent in selected or any(item.startswith(parent + "|") for item in selected if parent))
        scored.append((selection_match, int(_visible(node)), count, node))
    scored.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3]))
    return [item[3] for item in scored]


def _source_mesh_from_graph(graph: str) -> Optional[str]:
    for attr in ("source_mesh", "sourceMesh"):
        if not _attr_exists(graph, attr):
            continue
        try:
            plugs = cmds.listConnections(f"{graph}.{attr}", source=True, destination=False, plugs=True) or []
        except Exception:
            plugs = []
        for plug in plugs:
            node = plug.split(".", 1)[0]
            try:
                if cmds.nodeType(node) == "mesh":
                    return node
            except Exception:
                pass
    return None


class MayaCellMetadataProvider:
    def __init__(self, graph: Optional[str] = None):
        if not MAYA_AVAILABLE:
            raise RuntimeError("Maya is not available")
        self.graph = graph or (next(iter(_candidate_graphs()), None))
        if not self.graph:
            raise RuntimeError("No active Bifrost Scales native graph was found.")
        self.target_mesh = _source_mesh_from_graph(self.graph)

    def read_profile(self) -> dict[str, Any]:
        try:
            cmds.dgdirty(self.graph)
        except Exception:
            pass
        return _json_load(_get_string(self.graph, "profile_json"))

    def read_payload(self) -> dict[str, Any]:
        payload = _json_load(_get_string(self.graph, "payload_json"))
        if not payload:
            raise RuntimeError(f"{self.graph}.payload_json is empty or invalid")
        return payload

    def query_all(self, *, batch_size: int = 4096, progress: Optional[Callable[[int, int], None]] = None) -> tuple[list[CellPickRecord], str]:
        original_text = _get_string(self.graph, "payload_json")
        original_payload = _json_load(original_text)
        if not original_payload:
            raise RuntimeError("Native payload is not available.")
        profile = self.read_profile()
        count = find_scale_count(profile)
        if count <= 0:
            count = find_scale_count(original_payload)
        if count <= 0:
            raise RuntimeError("Native profile did not report any generated cells.")
        revision = revision_from_payload(original_payload, profile)
        all_records: dict[str, CellPickRecord] = {}
        try:
            for start in range(0, count, max(1, min(int(batch_size), 4096))):
                stop = min(count, start + max(1, min(int(batch_size), 4096)))
                payload = json.loads(json.dumps(original_payload))
                set_query_indices(payload, range(start, stop))
                _set_string(self.graph, "payload_json", json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
                batch_profile = self.read_profile()
                mappings = find_metadata_list(batch_profile)
                for offset, mapping in enumerate(mappings):
                    record = CellPickRecord.from_mapping(mapping, fallback_index=start+offset, revision=revision)
                    all_records[record.cell_id] = record
                if progress:
                    progress(stop, count)
        finally:
            _set_string(self.graph, "payload_json", original_text)
            try:
                self.read_profile()
            except Exception:
                pass
        records = sorted(all_records.values(), key=lambda r: r.scale_index)
        if not records:
            raise RuntimeError("The native graph returned no cell metadata. Rebuild the 0.10.7+ Native Pack and evaluate Settled Preview once.")
        return records, revision

    def screen_ray(self, x: int, y: int):
        """Convert Maya port coordinates to a normalized world-space ray.

        Maya 2026's Python API 2.0 exposes ``M3dView.viewToWorld`` through
        output ``MPoint``/``MVector`` arguments.  Calling it with only ``x``
        and ``y`` raises ``TypeError`` inside the tool-context callback and
        prevents both hover and click selection.
        """
        view = omui.M3dView.active3dView()
        point = om.MPoint()
        vector = om.MVector()
        view.viewToWorld(int(x), int(y), point, vector)
        direction = om.MVector(vector)
        length = float(direction.length())
        if not math.isfinite(length) or length <= 1.0e-12:
            raise RuntimeError("Maya returned a zero-length viewport ray")
        direction.normalize()
        return (
            (float(point.x), float(point.y), float(point.z)),
            (float(direction.x), float(direction.y), float(direction.z)),
        )

    def raycast_target(self, origin: Sequence[float], direction: Sequence[float]) -> Optional[tuple[float, float, float]]:
        if not self.target_mesh or not cmds.objExists(self.target_mesh):
            return None
        try:
            selection = om.MSelectionList(); selection.add(self.target_mesh)
            dag = selection.getDagPath(0)
            fn = om.MFnMesh(dag)
            result = fn.closestIntersection(
                om.MFloatPoint(*origin), om.MFloatVector(*direction), om.MSpace.kWorld,
                1.0e12, False
            )
            if not result:
                return None
            point = result[0]
            return (float(point.x), float(point.y), float(point.z))
        except Exception:
            return None


class CellPickerManager:
    def __init__(self):
        self.enabled = False
        self.building = False
        self.provider: Optional[MayaCellMetadataProvider] = None
        self.index = SpatialCellIndex.build(())
        self.revision = ""
        self.hover: Optional[CellPickRecord] = None
        self.selected_ids: list[str] = []
        self.previous_context = "selectSuperContext"
        self.context_name: Optional[str] = None
        self.tool_job: Optional[int] = None
        self.listeners: list[weakref.ReferenceType] = []
        self.last_error = ""
        self.last_interaction_error = ""
        self.last_draw_error = ""
        self.pointer_event_count = 0
        self.press_event_count = 0
        self.ray_success_count = 0
        self.target_hit_count = 0
        self.pick_success_count = 0
        self.draw_feedback_count = 0
        self.draw_submit_count = 0
        self.draw_primitive_count = 0
        self._outline_cache: dict[str, list[tuple[float,float,float]]] = {}
        # Registration bridge is installed lazily after the production UI exists.

    def add_listener(self, callback: Callable[[], None]) -> None:
        try:
            self.listeners.append(weakref.WeakMethod(callback))
        except TypeError:
            self.listeners.append(weakref.ref(callback))

    def notify(self) -> None:
        alive = []
        for ref in self.listeners:
            callback = ref()
            if callback is not None:
                alive.append(ref)
                try: callback()
                except Exception: pass
        self.listeners = alive
        if MAYA_AVAILABLE:
            try: omui.M3dView.scheduleRefreshAllViews()
            except Exception: pass

    def status_text(self) -> str:
        if self.building:
            return "Building cell selection cache..."
        if self.last_error:
            return self.last_error
        base = f"Cells: {len(self.index.records):,}   Selected: {len(self.selected_ids):,}"
        errors = []
        if self.last_interaction_error:
            errors.append("Picker event error: " + self.last_interaction_error)
        if self.last_draw_error:
            errors.append("Picker draw error: " + self.last_draw_error)
        if self.enabled:
            hover_text = self.hover.cell_id if self.hover is not None else "None"
            result = (
                base
                + f"   Hover: {hover_text}"
                + f"\nEvents: {self.pointer_event_count:,}   Rays: {self.ray_success_count:,}"
                + f"   Target hits: {self.target_hit_count:,}   Picks: {self.pick_success_count:,}"
                + f"\nDraw feedback: {self.draw_feedback_count:,}   Draw submits: {self.draw_submit_count:,}"
                + f"   Primitives: {self.draw_primitive_count:,}"
            )
            if errors:
                result += "\n" + "\n".join(errors)
            return result
        if errors:
            return base + "\n" + "\n".join(errors)
        return base

    def report_interaction_error(self, stage: str, exc: BaseException) -> None:
        self.last_interaction_error = f"{stage}: {type(exc).__name__}: {exc}"
        self.hover = None
        self.notify()

    def clear_interaction_error(self) -> None:
        if self.last_interaction_error:
            self.last_interaction_error = ""

    def report_draw_error(self, stage: str, exc: BaseException) -> None:
        # A display failure must never destroy a valid hover or cell selection.
        self.last_draw_error = f"{stage}: {type(exc).__name__}: {exc}"
        self.notify()

    def clear_draw_error(self) -> None:
        if self.last_draw_error:
            self.last_draw_error = ""

    def note_draw_feedback(self) -> None:
        self.draw_feedback_count += 1

    def note_draw_submit(self, primitive_count: int) -> None:
        self.draw_submit_count += 1
        self.draw_primitive_count += max(0, int(primitive_count))

    def debug_snapshot(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "building": bool(self.building),
            "graph": self.provider.graph if self.provider is not None else "",
            "target_mesh": self.provider.target_mesh if self.provider is not None else "",
            "cell_count": len(self.index.records),
            "selected_count": len(self.selected_ids),
            "hover_cell_id": self.hover.cell_id if self.hover is not None else "",
            "pointer_event_count": int(self.pointer_event_count),
            "press_event_count": int(self.press_event_count),
            "ray_success_count": int(self.ray_success_count),
            "target_hit_count": int(self.target_hit_count),
            "pick_success_count": int(self.pick_success_count),
            "last_cache_error": self.last_error,
            "last_interaction_error": self.last_interaction_error,
            "last_draw_error": self.last_draw_error,
            "draw_feedback_count": int(self.draw_feedback_count),
            "draw_submit_count": int(self.draw_submit_count),
            "draw_primitive_count": int(self.draw_primitive_count),
            "context_name": self.context_name or "",
        }

    def current_records(self) -> list[CellPickRecord]:
        result = []
        for cell_id in self.selected_ids:
            rec = self.index.get(cell_id)
            if rec is not None: result.append(rec)
        return result

    def rebuild(self) -> None:
        if not MAYA_AVAILABLE or self.building:
            return
        self.building = True; self.last_error = ""; self.last_interaction_error = ""; self.last_draw_error = ""; self.notify()
        try:
            self.provider = MayaCellMetadataProvider()
            records, revision = self.provider.query_all(progress=lambda done, total: self._progress(done, total))
            old = list(self.selected_ids)
            self.index = SpatialCellIndex.build(records)
            self.revision = revision
            self.selected_ids = [cell_id for cell_id in old if self.index.get(cell_id) is not None]
            self.hover = None
            self._outline_cache.clear()
        except Exception as exc:
            self.last_error = f"Cell Picker: {exc}"
            self.index = SpatialCellIndex.build(())
            self.hover = None
        finally:
            self.building = False; self.notify()

    def _progress(self, done: int, total: int) -> None:
        self.last_error = f"Reading native cells {done:,}/{total:,}"
        self.notify()
        if QtWidgets is not None:
            try: QtWidgets.QApplication.processEvents()
            except Exception: pass
        if done >= total: self.last_error = ""

    def enable(self) -> bool:
        if not MAYA_AVAILABLE: return False
        if not self.index.records: self.rebuild()
        if not self.index.records: return False
        self._ensure_plugin_and_context()
        self.clear_interaction_error()
        self.clear_draw_error()
        try: self.previous_context = cmds.currentCtx() or "selectSuperContext"
        except Exception: self.previous_context = "selectSuperContext"
        cmds.setToolTo(self.context_name)
        self.enabled = True
        self._install_tool_job(); self.notify(); return True

    def disable(self, *, restore_tool: bool = True) -> None:
        self.enabled = False; self.hover = None
        if self.tool_job and MAYA_AVAILABLE:
            try: cmds.scriptJob(kill=self.tool_job, force=True)
            except Exception: pass
        self.tool_job = None
        if restore_tool and MAYA_AVAILABLE:
            try:
                if cmds.currentCtx() == self.context_name:
                    cmds.setToolTo(self.previous_context or "selectSuperContext")
            except Exception: pass
        self.notify()

    def _install_tool_job(self) -> None:
        if self.tool_job:
            try: cmds.scriptJob(kill=self.tool_job, force=True)
            except Exception: pass
        self.tool_job = cmds.scriptJob(event=["ToolChanged", self._tool_changed], protected=True)

    def _tool_changed(self) -> None:
        if not self.enabled: return
        try: current = cmds.currentCtx()
        except Exception: current = ""
        if current != self.context_name:
            self.disable(restore_tool=False)

    def _ensure_plugin_and_context(self) -> None:
        plugin_path = Path(__file__).resolve().parents[2] / "plug-ins" / _PLUGIN_FILE
        if not plugin_path.exists():
            raise RuntimeError(f"Missing picker plug-in: {plugin_path}")
        plugin_name = plugin_path.name
        try: loaded = cmds.pluginInfo(plugin_name, query=True, loaded=True)
        except Exception: loaded = False
        if not loaded: cmds.loadPlugin(str(plugin_path), quiet=True)
        if self.context_name and cmds.contextInfo(self.context_name, exists=True): return
        creator = getattr(cmds, _CONTEXT_COMMAND)
        self.context_name = creator()

    def hover_at(self, x: int, y: int) -> Optional[CellPickRecord]:
        if not self.enabled or self.building or not self.provider:
            return None
        self.pointer_event_count += 1
        try:
            origin, direction = self.provider.screen_ray(x, y)
            self.ray_success_count += 1
            surface = self.provider.raycast_target(origin, direction)
            if surface is not None:
                self.target_hit_count += 1
            else:
                # Fallback: use a point along the view ray near the cache centroid.
                if not self.index.records:
                    return None
                centroid = tuple(
                    sum(r.center[i] for r in self.index.records) / len(self.index.records)
                    for i in range(3)
                )
                t = max(
                    0.0,
                    sum((centroid[i] - origin[i]) * direction[i] for i in range(3)),
                )
                surface = tuple(origin[i] + direction[i] * t for i in range(3))
            new_hover = self.index.pick(surface, origin, direction)
            if new_hover is not None:
                self.pick_success_count += 1
            self.clear_interaction_error()
        except Exception as exc:
            self.report_interaction_error("hover", exc)
            return None
        if (new_hover.cell_id if new_hover else None) != (
            self.hover.cell_id if self.hover else None
        ):
            self.hover = new_hover
            self.notify()
        return self.hover

    def click_hover(self, *, shift: bool = False, control: bool = False) -> None:
        self.press_event_count += 1
        rec = self.hover
        if rec is None:
            if not shift and not control: self.selected_ids = []
        elif control:
            if rec.cell_id in self.selected_ids: self.selected_ids.remove(rec.cell_id)
        elif shift:
            if rec.cell_id not in self.selected_ids: self.selected_ids.append(rec.cell_id)
        else:
            self.selected_ids = [rec.cell_id]
        self.notify()

    def clear(self) -> None:
        self.selected_ids = []; self.hover = None; self.notify()

    def outline_for(self, record: CellPickRecord, segments: int = 24) -> list[tuple[float,float,float]]:
        if record.outline:
            return list(record.outline) + [record.outline[0]]
        cached = self._outline_cache.get(record.cell_id)
        if cached is not None: return cached
        neighbors = [self.index.records[i] for i in self.index.nearby_indices(record.center, 2)]
        outline = approximate_voronoi_outline(record, neighbors, max(self.index.cell_size*0.38, 1.0e-4))
        self._outline_cache[record.cell_id] = outline
        return outline



_MANAGER: Optional[CellPickerManager] = None

def get_manager() -> CellPickerManager:
    global _MANAGER
    if _MANAGER is None: _MANAGER = CellPickerManager()
    return _MANAGER

def current_selection_records() -> list[CellPickRecord]:
    return get_manager().current_records()

def enable_cell_picker() -> bool:
    return get_manager().enable()

def disable_cell_picker() -> None:
    get_manager().disable()

def rebuild_cell_picker_cache() -> None:
    get_manager().rebuild()


def cell_picker_debug_snapshot() -> dict[str, Any]:
    return get_manager().debug_snapshot()
