"""Standalone Maya scene ownership and settings persistence."""

from __future__ import annotations

import math
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any

from .guides import GuideData, GuideGroupData, GuideKind, GuideSet
from .settings import ScaleSettings
from .version import SCHEMA_VERSION, VERSION

SETTINGS_MARKER = "bsIsSettings"
TARGET_MESSAGE = "bsTargetMesh"
PREVIEW_MESSAGE = "bsPreviewTransform"
GUIDE_ROOT_MESSAGE = "bsGuideRoot"
SETTINGS_JSON = "bsSettingsJson"
SYSTEM_ID = "bsSystemId"
SCHEMA_ATTR = "bsSchemaVersion"
VERSION_ATTR = "bsToolVersion"
PREVIEW_MARKER = "bsOwnedPreview"
ROOT_MARKER = "bsIsRoot"
SCALE_COUNT = "bsScaleCount"
VERTEX_COUNT = "bsVertexCount"
FACE_COUNT = "bsFaceCount"
ACTIVE_SLOT = "bsActivePreviewSlot"
PREVIEW_SLOT = "bsPreviewSlot"
OWNED_PREVIEW_SHAPE = "bsOwnedPreviewShape"
ROOT_NAME = "BifrostScales_GRP"
GUIDE_ROOT_MARKER = "bsOwnedGuideRoot"
GUIDE_MARKER = "bsOwnedGuide"
GUIDE_ID = "bsGuideId"
GUIDE_KIND = "bsGuideKind"
GUIDE_DISPLAY_NAME = "bsGuideDisplayName"
GUIDE_ORDER = "bsGuideOrder"
GUIDE_ENABLED = "bsGuideEnabled"
GUIDE_RADIUS = "bsGuideRadius"
GUIDE_FALLOFF = "bsGuideFalloff"
GUIDE_DENSITY_MULTIPLIER = "bsGuideDensityMultiplier"
GUIDE_SIZE_MULTIPLIER = "bsGuideSizeMultiplier"
GUIDE_STRENGTH = "bsGuideStrength"
GUIDE_CENTER_ALIGNMENT = "bsGuideCenterAlignment"
GUIDE_CELL_ANISOTROPY = "bsGuideCellAnisotropy"
GUIDE_ANGLE = "bsGuideAngle"
GUIDE_CLOSED = "bsGuideClosed"
GUIDE_USE_DENSITY = "bsGuideUseDensity"
GUIDE_USE_SIZE = "bsGuideUseSize"
GUIDE_USE_DIRECTION = "bsGuideUseDirection"
GUIDE_USE_MASK = "bsGuideUseMask"
GUIDE_UI_ORDER = "bsGuideUiOrder"
GUIDE_GROUP_ID = "bsGuideGroupId"
GUIDE_SYMMETRY_ENABLED = "bsGuideSymmetryEnabled"
GUIDE_SYMMETRY_AXIS = "bsGuideSymmetryAxis"
GUIDE_SYMMETRY_SPACE = "bsGuideSymmetrySpace"
GUIDE_GROUP_MARKER = "bsOwnedGuideGroup"
GUIDE_GROUP_NAME = "bsGuideGroupName"
GUIDE_GROUP_ORDER = "bsGuideGroupOrder"
GUIDE_GROUP_COLLAPSED = "bsGuideGroupCollapsed"
GUIDE_GROUP_ENABLED = "bsGuideGroupEnabled"
GUIDE_GROUP_RADIUS_MULTIPLIER = "bsGuideGroupRadiusMultiplier"
GUIDE_GROUP_FALLOFF_MULTIPLIER = "bsGuideGroupFalloffMultiplier"
GUIDE_GROUP_DENSITY_STRENGTH = "bsGuideGroupDensityStrength"
GUIDE_GROUP_SIZE_STRENGTH = "bsGuideGroupSizeStrength"
GUIDE_GROUP_DIRECTION_STRENGTH = "bsGuideGroupDirectionStrength"
GUIDE_GROUP_ANGLE_OFFSET = "bsGuideGroupAngleOffset"
GUIDE_GROUP_SYMMETRY_ENABLED = "bsGuideGroupSymmetryEnabled"
GUIDE_GROUP_SYMMETRY_AXIS = "bsGuideGroupSymmetryAxis"
GUIDE_GROUP_SYMMETRY_SPACE = "bsGuideGroupSymmetrySpace"


@dataclass(frozen=True)
class SystemBinding:
    settings_node: str
    target_mesh: str
    preview_transform: str
    system_id: str
    guide_root: str = ""


class MayaSceneManager:
    def __init__(self, cmds_module: Any | None = None) -> None:
        if cmds_module is None:
            import maya.cmds as cmds_module  # type: ignore
        self.cmds = cmds_module
        self._undo_chunk_depth = 0

    def list_systems(self) -> list[str]:
        """Return only systems created for the current breaking schema."""

        result: list[str] = []
        for node in self.cmds.ls(type="network") or []:
            try:
                if not (
                    self.cmds.attributeQuery(SETTINGS_MARKER, node=node, exists=True)
                    and bool(self.cmds.getAttr(node + "." + SETTINGS_MARKER))
                ):
                    continue
                if not self.cmds.attributeQuery(SCHEMA_ATTR, node=node, exists=True):
                    continue
                schema = str(self.cmds.getAttr(node + "." + SCHEMA_ATTR) or "")
                if schema != SCHEMA_VERSION:
                    continue
                result.append(str(node))
            except Exception:
                continue
        return sorted(result)


    def selected_mesh(self) -> str:
        """Return the first selected non-intermediate polygon mesh shape."""

        selection = self.cmds.ls(selection=True, long=True) or []
        for item in selection:
            try:
                return self._resolve_mesh(str(item))
            except ValueError:
                continue
        raise ValueError("ポリゴンメッシュを1つ選択してください")

    def create_system(self, target_mesh: str, settings: ScaleSettings | None = None) -> SystemBinding:
        target = self._resolve_mesh(target_mesh)
        root = self._ensure_root()
        settings_node = self.cmds.createNode("network", name="bifrostScalesSettings#")
        preview_transform = self.cmds.createNode(
            "transform",
            name="bifrostScalesPreview#",
            parent=root,
        )
        system_id = str(uuid.uuid4())
        self._ensure_bool(settings_node, SETTINGS_MARKER, True)
        self._ensure_string(settings_node, SCHEMA_ATTR, SCHEMA_VERSION)
        self._ensure_string(settings_node, VERSION_ATTR, VERSION)
        self._ensure_string(settings_node, SYSTEM_ID, system_id)
        self._ensure_string(settings_node, SETTINGS_JSON, (settings or ScaleSettings()).to_json())
        self._ensure_message(settings_node, TARGET_MESSAGE)
        self._ensure_message(settings_node, PREVIEW_MESSAGE)
        self._ensure_message(settings_node, GUIDE_ROOT_MESSAGE)
        self._ensure_bool(preview_transform, PREVIEW_MARKER, True)
        self._ensure_string(preview_transform, SYSTEM_ID, system_id)
        self._ensure_int(preview_transform, SCALE_COUNT, 0)
        self._ensure_int(preview_transform, VERTEX_COUNT, 0)
        self._ensure_int(preview_transform, FACE_COUNT, 0)
        self._ensure_string(preview_transform, ACTIVE_SLOT, "settled")
        self.cmds.connectAttr(target + ".message", settings_node + "." + TARGET_MESSAGE, force=True)
        self.cmds.connectAttr(
            preview_transform + ".message",
            settings_node + "." + PREVIEW_MESSAGE,
            force=True,
        )
        guide_root = self._create_guide_root(root, system_id)
        self.cmds.connectAttr(
            guide_root + ".message",
            settings_node + "." + GUIDE_ROOT_MESSAGE,
            force=True,
        )
        return self.bind(settings_node)

    def bind(self, settings_node: str) -> SystemBinding:
        if not settings_node or not self.cmds.objExists(settings_node):
            raise ValueError("Settings node does not exist")
        if not self.cmds.attributeQuery(SETTINGS_MARKER, node=settings_node, exists=True):
            raise ValueError("Node is not a Bifrost Scales settings node")
        schema = ""
        if self.cmds.attributeQuery(SCHEMA_ATTR, node=settings_node, exists=True):
            schema = str(self.cmds.getAttr(settings_node + "." + SCHEMA_ATTR) or "")
        if schema != SCHEMA_VERSION:
            raise ValueError(
                "Incompatible Bifrost Scales system schema: {} (expected {})".format(
                    schema or "missing",
                    SCHEMA_VERSION,
                )
            )
        target_nodes = self.cmds.listConnections(
            settings_node + "." + TARGET_MESSAGE,
            source=True,
            destination=False,
        ) or []
        preview_nodes = self.cmds.listConnections(
            settings_node + "." + PREVIEW_MESSAGE,
            source=True,
            destination=False,
        ) or []
        if not target_nodes:
            raise ValueError("Settings node has no target mesh")
        if not preview_nodes:
            raise ValueError("Settings node has no preview transform")
        target = self._resolve_mesh(str(target_nodes[0]))
        preview = str(preview_nodes[0])
        if self.cmds.nodeType(preview) != "transform":
            parents = self.cmds.listRelatives(preview, parent=True, fullPath=True) or []
            if not parents:
                raise ValueError("Preview connection is invalid")
            preview = str(parents[0])
        self._ensure_string(preview, ACTIVE_SLOT, self._active_slot(preview))
        system_id = ""
        if self.cmds.attributeQuery(SYSTEM_ID, node=settings_node, exists=True):
            system_id = str(self.cmds.getAttr(settings_node + "." + SYSTEM_ID) or "")
        guide_root = self._guide_root_for_settings(str(settings_node), preview, system_id)
        return SystemBinding(
            settings_node=str(settings_node),
            target_mesh=target,
            preview_transform=preview,
            system_id=system_id,
            guide_root=guide_root,
        )

    def set_target(self, settings_node: str, target_mesh: str) -> SystemBinding:
        target = self._resolve_mesh(target_mesh)
        plug = settings_node + "." + TARGET_MESSAGE
        current = self.cmds.listConnections(plug, source=True, destination=False, plugs=True) or []
        for source in current:
            try:
                self.cmds.disconnectAttr(source, plug)
            except Exception:
                pass
        self.cmds.connectAttr(target + ".message", plug, force=True)
        return self.bind(settings_node)

    def read_settings(self, settings_node: str) -> ScaleSettings:
        if not self.cmds.attributeQuery(SETTINGS_JSON, node=settings_node, exists=True):
            return ScaleSettings()
        return ScaleSettings.from_json(self.cmds.getAttr(settings_node + "." + SETTINGS_JSON))

    def write_settings(self, settings_node: str, settings: ScaleSettings) -> None:
        with self._automatic_update_guard():
            self._ensure_string(settings_node, SETTINGS_JSON, settings.to_json())
            self._ensure_string(settings_node, VERSION_ATTR, VERSION)
            self._ensure_string(settings_node, SCHEMA_ATTR, SCHEMA_VERSION)

    def set_stats(self, preview_transform: str, scales: int, vertices: int, faces: int) -> None:
        with self._automatic_update_guard():
            self._ensure_int(preview_transform, SCALE_COUNT, int(scales))
            self._ensure_int(preview_transform, VERTEX_COUNT, int(vertices))
            self._ensure_int(preview_transform, FACE_COUNT, int(faces))

    def get_stats(self, preview_transform: str) -> tuple[int, int, int]:
        values = []
        for name in (SCALE_COUNT, VERTEX_COUNT, FACE_COUNT):
            try:
                values.append(int(self.cmds.getAttr(preview_transform + "." + name)))
            except Exception:
                values.append(0)
        return (values[0], values[1], values[2])

    def delete_system(self, settings_node: str) -> None:
        binding = self.bind(settings_node)
        parents = self.cmds.listRelatives(
            binding.preview_transform, parent=True, fullPath=True
        ) or []
        parent = str(parents[0]) if parents else ""
        for owned_node in (binding.preview_transform, binding.guide_root):
            if owned_node and self.cmds.objExists(owned_node):
                self.cmds.delete(owned_node)
        if self.cmds.objExists(settings_node):
            self.cmds.delete(settings_node)
        if parent and self.cmds.objExists(parent):
            owned = bool(
                self.cmds.attributeQuery(ROOT_MARKER, node=parent, exists=True)
                and self.cmds.getAttr(parent + "." + ROOT_MARKER)
            )
            children = self.cmds.listRelatives(parent, children=True, fullPath=True) or []
            if owned and not children:
                self.cmds.delete(parent)

    def create_point_guide(
        self,
        settings_node: str,
        kind: GuideKind | str,
    ) -> str:
        binding = self.bind(settings_node)
        guide_kind = GuideKind(kind)
        if guide_kind.is_curve:
            raise ValueError("Point guide creation requires a point guide kind")
        with self.user_undo_chunk("Bifrost Scales Create Guide Point"):
            name = "bifrostScalesGuidePoint#"
            if hasattr(self.cmds, "spaceLocator"):
                transform = str(self.cmds.spaceLocator(name=name)[0])
                parented = self.cmds.parent(transform, binding.guide_root) or [transform]
                transform = self._long_node_name(str(parented[0]))
            else:
                transform = str(
                    self.cmds.createNode(
                        "transform",
                        name=name,
                        parent=binding.guide_root,
                    )
                )
                self.cmds.createNode("locator", name=transform + "Shape", parent=transform)
            center = self._target_center(binding.target_mesh)
            try:
                self.cmds.xform(transform, worldSpace=True, translation=center)
            except Exception:
                for attribute, value in zip(("translateX", "translateY", "translateZ"), center):
                    try:
                        self.cmds.setAttr(transform + "." + attribute, float(value))
                    except Exception:
                        pass
            self._initialize_guide(transform, binding, guide_kind)
            self.cmds.select(transform, replace=True)
        return transform

    def create_curve_guide_from_points(
        self,
        settings_node: str,
        kind: GuideKind | str,
        points: list[tuple[float, float, float]] | tuple[tuple[float, float, float], ...],
    ) -> str:
        guide_kind = GuideKind(kind)
        if not guide_kind.is_curve:
            raise ValueError("Curve guide creation requires a curve guide kind")
        clean_points = [
            (float(point[0]), float(point[1]), float(point[2]))
            for point in points
        ]
        if len(clean_points) < 2:
            raise ValueError("Guide Curveには2点以上必要です")
        with self.user_undo_chunk("Bifrost Scales Create Guide Curve"):
            transform = str(
                self.cmds.curve(
                    degree=1,
                    point=clean_points,
                    worldSpace=True,
                    name="bifrostScalesGuideCurve#",
                )
            )
            try:
                return self.adopt_curve_guide(settings_node, guide_kind, transform)
            except Exception:
                if self.cmds.objExists(transform):
                    self.cmds.delete(transform)
                raise

    def adopt_curve_guide(
        self,
        settings_node: str,
        kind: GuideKind | str,
        curve_transform: str,
    ) -> str:
        binding = self.bind(settings_node)
        guide_kind = GuideKind(kind)
        if not guide_kind.is_curve:
            raise ValueError("Curve guide adoption requires a curve guide kind")
        transform = self._curve_transform(curve_transform)
        if self.cmds.attributeQuery(GUIDE_MARKER, node=transform, exists=True):
            raise ValueError("Curve is already an owned Bifrost Scales guide")
        with self.user_undo_chunk("Bifrost Scales Adopt Guide Curve"):
            parented = self.cmds.parent(transform, binding.guide_root) or [transform]
            transform = self._long_node_name(str(parented[0]))
            self._initialize_guide(transform, binding, guide_kind)
            self.cmds.select(transform, replace=True)
        return transform

    def create_curve_guide_from_selection(
        self,
        settings_node: str,
        kind: GuideKind | str,
    ) -> str:
        """Backward-compatible scripting API for adopting a curve copy."""

        guide_kind = GuideKind(kind)
        if not guide_kind.is_curve:
            raise ValueError("Curve guide creation requires a curve guide kind")
        source = self._selected_curve_transform()
        with self.user_undo_chunk("Bifrost Scales Duplicate Guide Curve"):
            duplicate = str(
                self.cmds.duplicate(
                    source,
                    name="bifrostScalesGuideCurve#",
                    returnRootsOnly=True,
                )[0]
            )
            try:
                return self.adopt_curve_guide(settings_node, guide_kind, duplicate)
            except Exception:
                if self.cmds.objExists(duplicate):
                    self.cmds.delete(duplicate)
                raise

    def _initialize_guide_group(
        self,
        group: str,
        binding: SystemBinding,
        name: str,
        order: int,
    ) -> str:
        group_id = "group_" + uuid.uuid4().hex
        display_name = (
            " ".join(str(name).strip().split())[:64]
            or self._next_group_display_name(binding)
        )
        self._ensure_bool(group, GUIDE_GROUP_MARKER, True)
        self._ensure_string(group, SYSTEM_ID, binding.system_id)
        self._ensure_string(group, GUIDE_GROUP_ID, group_id)
        self._ensure_string(group, GUIDE_GROUP_NAME, display_name)
        self._ensure_int(group, GUIDE_GROUP_ORDER, order)
        self._ensure_bool(group, GUIDE_GROUP_COLLAPSED, False)
        self._ensure_bool(group, GUIDE_GROUP_ENABLED, True)
        self._ensure_double(group, GUIDE_GROUP_RADIUS_MULTIPLIER, 1.0)
        self._ensure_double(group, GUIDE_GROUP_FALLOFF_MULTIPLIER, 1.0)
        self._ensure_double(group, GUIDE_GROUP_DENSITY_STRENGTH, 1.0)
        self._ensure_double(group, GUIDE_GROUP_SIZE_STRENGTH, 1.0)
        self._ensure_double(group, GUIDE_GROUP_DIRECTION_STRENGTH, 1.0)
        self._ensure_double(group, GUIDE_GROUP_ANGLE_OFFSET, 0.0)
        self._ensure_bool(group, GUIDE_GROUP_SYMMETRY_ENABLED, False)
        self._ensure_string(group, GUIDE_GROUP_SYMMETRY_AXIS, "x")
        self._ensure_string(group, GUIDE_GROUP_SYMMETRY_SPACE, "world")
        return group_id

    def create_guide_group(
        self,
        settings_node: str,
        name: str = "",
        guide_nodes: list[str] | tuple[str, ...] = (),
    ) -> str:
        binding = self.bind(settings_node)
        self._ensure_guide_management_metadata(binding)
        owned_guides = self._owned_guide_nodes(binding)
        guides: list[str] = []
        for node in guide_nodes:
            guide = self._canonical_owned_node(node, owned_guides)
            if not guide:
                raise ValueError("Guide is not owned by the current system")
            if guide not in guides:
                guides.append(guide)
        order = max(
            (
                self._int_attr(node, GUIDE_GROUP_ORDER, -1)
                for node in self._owned_group_nodes(binding)
            ),
            default=-1,
        ) + 1
        with self.user_undo_chunk("Bifrost Scales Create Guide Group"):
            group = self._long_node_name(
                str(
                    self.cmds.createNode(
                        "transform",
                        name="bifrostScalesGuideGroup#",
                        parent=binding.guide_root,
                    )
                )
            )
            group_id = self._initialize_guide_group(group, binding, name, order)
            for index, guide in enumerate(guides):
                parented = self.cmds.parent(guide, group) or [guide]
                moved = self._long_node_name(str(parented[0]))
                self._ensure_string(moved, GUIDE_GROUP_ID, group_id)
                self._ensure_int(moved, GUIDE_UI_ORDER, index)
            self.cmds.select(group, replace=True)
        return group

    def list_guide_groups(self, settings_node: str) -> list[str]:
        binding = self.bind(settings_node)
        self._ensure_guide_management_metadata(binding)
        groups = self._owned_group_nodes(binding)
        children: dict[str, list[str]] = {"": []}
        for node in groups:
            parent = self._group_parent_node(binding, node, groups)
            children.setdefault(parent, []).append(node)

        def key(node: str) -> tuple[object, ...]:
            return (
                self._int_attr(node, GUIDE_GROUP_ORDER, 0),
                self._string_attr(node, GUIDE_GROUP_ID, ""),
                str(node),
            )

        ordered: list[str] = []
        seen: set[str] = set()

        def append_children(parent: str) -> None:
            for node in sorted(children.get(parent, ()), key=key):
                if node in seen:
                    continue
                seen.add(node)
                ordered.append(node)
                append_children(node)

        append_children("")
        for node in sorted(groups, key=key):
            if node not in seen:
                seen.add(node)
                ordered.append(node)
                append_children(node)
        return ordered
    def list_guides(self, settings_node: str) -> list[str]:
        """Return guides in management order without changing evaluation order."""

        binding = self.bind(settings_node)
        self._ensure_guide_management_metadata(binding)
        groups = {
            self._string_attr(node, GUIDE_GROUP_ID, ""): self._int_attr(
                node, GUIDE_GROUP_ORDER, 0
            )
            for node in self._owned_group_nodes(binding)
        }

        def key(node: str) -> tuple[object, ...]:
            group_id = self._string_attr(node, GUIDE_GROUP_ID, "")
            if group_id:
                return (
                    1,
                    groups.get(group_id, 1_000_000),
                    self._int_attr(node, GUIDE_UI_ORDER, 0),
                    self._guide_id(node),
                    str(node),
                )
            return (
                0,
                -1,
                self._int_attr(node, GUIDE_UI_ORDER, 0),
                self._guide_id(node),
                str(node),
            )

        return sorted(self._owned_guide_nodes(binding), key=key)

    def guide_management_fingerprint(self, settings_node: str) -> tuple[object, ...]:
        """Return UI-management state, including empty groups and display order."""

        binding = self.bind(settings_node)
        self._ensure_guide_management_metadata(binding)
        group_rows: list[tuple[object, ...]] = []
        group_nodes = self.list_guide_groups(settings_node)
        for node in group_nodes:
            group = self.read_guide_group(node)
            group_rows.append(
                (
                    group.group_id,
                    self._string_attr(
                        self._group_parent_node(binding, node, group_nodes),
                        GUIDE_GROUP_ID,
                        "",
                    ),
                    self._bool_attr(node, GUIDE_GROUP_COLLAPSED, False),
                    self._bool_attr(node, "visibility", True),
                    self._node_locked(node),
                    group.name,
                    group.enabled,
                    group.order,
                    group.radius_multiplier,
                    group.falloff_multiplier,
                    group.density_strength,
                    group.size_strength,
                    group.direction_strength,
                    group.angle_offset_degrees,
                    group.symmetry_enabled,
                    group.symmetry_axis,
                    group.symmetry_space,
                )
            )
        guide_rows: list[tuple[object, ...]] = []
        for node in self.list_guides(settings_node):
            guide_rows.append(
                (
                    self._guide_id(node),
                    self._guide_display_name(node),
                    self._string_attr(node, GUIDE_GROUP_ID, ""),
                    self._int_attr(node, GUIDE_UI_ORDER, 0),
                    self._bool_attr(node, "visibility", True),
                    self._node_locked(node),
                    self._bool_attr(node, GUIDE_SYMMETRY_ENABLED, False),
                    self._string_attr(node, GUIDE_SYMMETRY_AXIS, "x"),
                    self._string_attr(node, GUIDE_SYMMETRY_SPACE, "world"),
                )
            )
        return (tuple(group_rows), tuple(guide_rows))

    def read_guide_group(self, node: str) -> GuideGroupData:
        if not node or not self.cmds.objExists(node):
            raise ValueError("Guide group does not exist")
        if not (
            self.cmds.attributeQuery(GUIDE_GROUP_MARKER, node=node, exists=True)
            and bool(self.cmds.getAttr(node + "." + GUIDE_GROUP_MARKER))
        ):
            raise ValueError("Node is not an owned Bifrost Scales guide group")
        return GuideGroupData(
            group_id=self._string_attr(node, GUIDE_GROUP_ID, "group"),
            name=self._string_attr(
                node,
                GUIDE_GROUP_NAME,
                str(node).split("|")[-1],
            ),
            enabled=self._bool_attr(node, GUIDE_GROUP_ENABLED, True),
            order=self._int_attr(node, GUIDE_GROUP_ORDER, 0),
            radius_multiplier=self._double_attr(
                node, GUIDE_GROUP_RADIUS_MULTIPLIER, 1.0
            ),
            falloff_multiplier=self._double_attr(
                node, GUIDE_GROUP_FALLOFF_MULTIPLIER, 1.0
            ),
            density_strength=self._double_attr(
                node, GUIDE_GROUP_DENSITY_STRENGTH, 1.0
            ),
            size_strength=self._double_attr(
                node, GUIDE_GROUP_SIZE_STRENGTH, 1.0
            ),
            direction_strength=self._double_attr(
                node, GUIDE_GROUP_DIRECTION_STRENGTH, 1.0
            ),
            angle_offset_degrees=self._double_attr(
                node, GUIDE_GROUP_ANGLE_OFFSET, 0.0
            ),
            symmetry_enabled=self._bool_attr(
                node, GUIDE_GROUP_SYMMETRY_ENABLED, False
            ),
            symmetry_axis=self._string_attr(
                node, GUIDE_GROUP_SYMMETRY_AXIS, "x"
            ),
            symmetry_space=self._string_attr(
                node, GUIDE_GROUP_SYMMETRY_SPACE, "world"
            ),
        ).normalized()

    def guide_group_layout_state(
        self,
        settings_node: str,
    ) -> dict[str, tuple[str, bool]]:
        binding = self.bind(settings_node)
        groups = self.list_guide_groups(settings_node)
        return {
            node: (
                self._group_parent_node(binding, node, groups),
                self._bool_attr(node, GUIDE_GROUP_COLLAPSED, False),
            )
            for node in groups
        }

    def guide_group_parent(self, settings_node: str, node: str) -> str:
        binding = self.bind(settings_node)
        groups = self._owned_group_nodes(binding)
        node = self._canonical_owned_node(node, groups)
        if not node:
            raise ValueError("Guide group is not owned by the current system")
        return self._group_parent_node(binding, node, groups)

    def guide_group_collapsed(self, node: str) -> bool:
        self.read_guide_group(node)
        return self._bool_attr(node, GUIDE_GROUP_COLLAPSED, False)

    def guide_item_presentation_state(
        self,
        settings_node: str,
    ) -> dict[str, tuple[bool, bool]]:
        binding = self.bind(settings_node)
        nodes = self._owned_guide_nodes(binding) + self._owned_group_nodes(binding)
        return {
            node: (
                self._bool_attr(node, "visibility", True),
                self._node_locked(node),
            )
            for node in nodes
        }

    def set_guide_item_visible(
        self,
        settings_node: str,
        node: str,
        visible: bool,
    ) -> None:
        binding = self.bind(settings_node)
        owned = self._owned_guide_nodes(binding) + self._owned_group_nodes(binding)
        node = self._canonical_owned_node(node, owned)
        if not node:
            raise ValueError("Guide item is not owned by the current system")
        # Even an unchanged Maya write discards the user's redo history.
        if bool(self.cmds.getAttr(node + ".visibility")) == bool(visible):
            return
        with self.user_undo_chunk("Bifrost Scales Set Guide Visibility"):
            self.cmds.setAttr(node + ".visibility", bool(visible))

    def set_guide_item_locked(
        self,
        settings_node: str,
        node: str,
        locked: bool,
    ) -> None:
        binding = self.bind(settings_node)
        owned = self._owned_guide_nodes(binding) + self._owned_group_nodes(binding)
        node = self._canonical_owned_node(node, owned)
        if not node:
            raise ValueError("Guide item is not owned by the current system")
        if bool(self.cmds.lockNode(node, query=True, lock=True)[0]) == bool(locked):
            return
        with self.user_undo_chunk("Bifrost Scales Set Guide Lock"):
            self.cmds.lockNode(node, lock=bool(locked))

    def set_guide_group_collapsed(self, node: str, collapsed: bool) -> None:
        self.read_guide_group(node)
        with self._automatic_update_guard():
            self._ensure_bool(node, GUIDE_GROUP_COLLAPSED, bool(collapsed))

    def read_guide(self, node: str, effective: bool = False) -> GuideData:
        if not node or not self.cmds.objExists(node):
            raise ValueError("Guide does not exist")
        if not (
            self.cmds.attributeQuery(GUIDE_MARKER, node=node, exists=True)
            and bool(self.cmds.getAttr(node + "." + GUIDE_MARKER))
        ):
            raise ValueError("Node is not an owned Bifrost Scales guide")
        raw_kind = str(self.cmds.getAttr(node + "." + GUIDE_KIND) or "")
        kind = GuideKind(raw_kind)
        guide = GuideData(
            guide_id=self._guide_id(node),
            name=self._guide_display_name(node),
            kind=kind,
            points=self._guide_points(node, kind),
            order=self._guide_order(node),
            group_id=self._string_attr(node, GUIDE_GROUP_ID, ""),
            symmetry_enabled=self._bool_attr(
                node, GUIDE_SYMMETRY_ENABLED, False
            ),
            symmetry_axis=self._string_attr(node, GUIDE_SYMMETRY_AXIS, "x"),
            symmetry_space=self._string_attr(
                node, GUIDE_SYMMETRY_SPACE, "world"
            ),
            direction=self._guide_direction(node),
            enabled=bool(self.cmds.getAttr(node + "." + GUIDE_ENABLED)),
            radius=float(self.cmds.getAttr(node + "." + GUIDE_RADIUS)),
            falloff=float(self.cmds.getAttr(node + "." + GUIDE_FALLOFF)),
            density_multiplier=float(
                self.cmds.getAttr(node + "." + GUIDE_DENSITY_MULTIPLIER)
            ),
            size_multiplier=float(
                self.cmds.getAttr(node + "." + GUIDE_SIZE_MULTIPLIER)
            ),
            strength=float(self.cmds.getAttr(node + "." + GUIDE_STRENGTH)),
            center_alignment=self._double_attr(
                node, GUIDE_CENTER_ALIGNMENT, 0.35
            ),
            cell_anisotropy=self._double_attr(
                node, GUIDE_CELL_ANISOTROPY, 1.0
            ),
            angle_degrees=float(self.cmds.getAttr(node + "." + GUIDE_ANGLE)),
            closed=bool(self.cmds.getAttr(node + "." + GUIDE_CLOSED)),
            use_density=self._guide_role_value(
                node, GUIDE_USE_DENSITY, kind.default_use_density
            ),
            use_size=self._guide_role_value(
                node, GUIDE_USE_SIZE, kind.default_use_size
            ),
            use_direction=self._guide_role_value(
                node, GUIDE_USE_DIRECTION, kind.default_use_direction
            ),
            use_mask=self._guide_role_value(node, GUIDE_USE_MASK, False),
        ).normalized()
        if not effective or not guide.group_id:
            return guide
        group_node = self._group_node_for_id(node, guide.group_id)
        if not group_node:
            return guide
        return self.read_guide_group(group_node).apply(guide)

    def read_guides(self, settings_node: str) -> GuideSet:
        binding = self.bind(settings_node)
        self._ensure_guide_management_metadata(binding)
        nodes = sorted(
            self._owned_guide_nodes(binding),
            key=lambda node: (
                self._guide_order(node),
                self._guide_id(node),
                str(node),
            ),
        )
        guides: list[GuideData] = []
        for node in nodes:
            try:
                guide = self.read_guide(node, effective=False)
                if guide.group_id:
                    group_node = self._group_node_for_id(node, guide.group_id)
                    if group_node:
                        guide = self.read_guide_group(group_node).apply(guide)
                guides.append(
                    self._resolve_guide_symmetry_frame(
                        guide,
                        binding.target_mesh,
                    )
                )
            except Exception:
                continue
        return GuideSet.from_iterable(guides)

    def update_guide(self, node: str, **values: object) -> None:
        if not node or not self.cmds.objExists(node):
            raise ValueError("Guide does not exist")
        if not self.cmds.attributeQuery(GUIDE_MARKER, node=node, exists=True):
            raise ValueError("Node is not an owned Bifrost Scales guide")
        mapping = {
            "enabled": (GUIDE_ENABLED, "bool"),
            "radius": (GUIDE_RADIUS, "double"),
            "falloff": (GUIDE_FALLOFF, "double"),
            "density_multiplier": (GUIDE_DENSITY_MULTIPLIER, "double"),
            "size_multiplier": (GUIDE_SIZE_MULTIPLIER, "double"),
            "strength": (GUIDE_STRENGTH, "double"),
            "center_alignment": (GUIDE_CENTER_ALIGNMENT, "double"),
            "cell_anisotropy": (GUIDE_CELL_ANISOTROPY, "double"),
            "angle_degrees": (GUIDE_ANGLE, "double"),
            "closed": (GUIDE_CLOSED, "bool"),
            "use_density": (GUIDE_USE_DENSITY, "bool"),
            "use_size": (GUIDE_USE_SIZE, "bool"),
            "use_direction": (GUIDE_USE_DIRECTION, "bool"),
            "use_mask": (GUIDE_USE_MASK, "bool"),
            "symmetry_enabled": (GUIDE_SYMMETRY_ENABLED, "bool"),
            "symmetry_axis": (GUIDE_SYMMETRY_AXIS, "string"),
            "symmetry_space": (GUIDE_SYMMETRY_SPACE, "string"),
        }
        with self.user_undo_chunk("Bifrost Scales Edit Guide"):
            for key, value in values.items():
                if key not in mapping:
                    continue
                attribute, kind = mapping[key]
                if kind == "bool":
                    self._ensure_bool(node, attribute, bool(value))
                elif kind == "string":
                    self._ensure_string(node, attribute, str(value))
                else:
                    self._ensure_double(node, attribute, float(value))
            if "use_mask" in values:
                try:
                    kind = GuideKind(self._string_attr(node, GUIDE_KIND, GuideKind.DENSITY_POINT.value))
                except Exception:
                    kind = GuideKind.DENSITY_POINT
                self._style_guide_node(node, kind, bool(values.get("use_mask")))

    def rename_guide(self, node: str, display_name: str) -> str:
        if not node or not self.cmds.objExists(node):
            raise ValueError("Guide does not exist")
        if not self.cmds.attributeQuery(GUIDE_MARKER, node=node, exists=True):
            raise ValueError("Node is not an owned Bifrost Scales guide")
        normalized = " ".join(str(display_name).strip().split())
        if not normalized:
            raise ValueError("Guide名を入力してください")
        normalized = normalized[:64]
        with self.user_undo_chunk("Bifrost Scales Rename Guide"):
            self._ensure_string(node, GUIDE_DISPLAY_NAME, normalized)
        return normalized

    def update_guide_group(self, node: str, **values: object) -> GuideGroupData:
        current = self.read_guide_group(node)
        accepted = {
            key: value
            for key, value in values.items()
            if key in {
                "name",
                "enabled",
                "radius_multiplier",
                "falloff_multiplier",
                "density_strength",
                "size_strength",
                "direction_strength",
                "angle_offset_degrees",
                "symmetry_enabled",
                "symmetry_axis",
                "symmetry_space",
            }
        }
        if "name" in accepted:
            accepted["name"] = " ".join(str(accepted["name"]).strip().split())[:64]
        normalized = replace(current, **accepted).normalized()
        with self.user_undo_chunk("Bifrost Scales Edit Guide Group"):
            self._ensure_string(node, GUIDE_GROUP_NAME, normalized.name)
            self._ensure_bool(node, GUIDE_GROUP_ENABLED, normalized.enabled)
            self._ensure_double(
                node, GUIDE_GROUP_RADIUS_MULTIPLIER, normalized.radius_multiplier
            )
            self._ensure_double(
                node, GUIDE_GROUP_FALLOFF_MULTIPLIER, normalized.falloff_multiplier
            )
            self._ensure_double(
                node, GUIDE_GROUP_DENSITY_STRENGTH, normalized.density_strength
            )
            self._ensure_double(
                node, GUIDE_GROUP_SIZE_STRENGTH, normalized.size_strength
            )
            self._ensure_double(
                node, GUIDE_GROUP_DIRECTION_STRENGTH, normalized.direction_strength
            )
            self._ensure_double(
                node, GUIDE_GROUP_ANGLE_OFFSET, normalized.angle_offset_degrees
            )
            self._ensure_bool(
                node, GUIDE_GROUP_SYMMETRY_ENABLED, normalized.symmetry_enabled
            )
            self._ensure_string(
                node, GUIDE_GROUP_SYMMETRY_AXIS, normalized.symmetry_axis
            )
            self._ensure_string(
                node, GUIDE_GROUP_SYMMETRY_SPACE, normalized.symmetry_space
            )
        return self.read_guide_group(node)

    def move_guide_to_group(
        self,
        settings_node: str,
        guide_node: str,
        group_node: str = "",
    ) -> str:
        binding = self.bind(settings_node)
        self._ensure_guide_management_metadata(binding)
        guide_node = self._canonical_owned_node(
            guide_node,
            self._owned_guide_nodes(binding),
        )
        if not guide_node:
            raise ValueError("Guide is not owned by the current system")
        destination = binding.guide_root
        group_id = ""
        if group_node:
            group_node = self._canonical_owned_node(
                group_node,
                self._owned_group_nodes(binding),
            )
            if not group_node:
                raise ValueError("Guide group is not owned by the current system")
            destination = group_node
            group_id = self._string_attr(group_node, GUIDE_GROUP_ID, "")
        with self.user_undo_chunk("Bifrost Scales Move Guide To Group"):
            parented = self.cmds.parent(guide_node, destination) or [guide_node]
            moved = self._long_node_name(str(parented[0]))
            self._ensure_string(moved, GUIDE_GROUP_ID, group_id)
            self._ensure_int(
                moved,
                GUIDE_UI_ORDER,
                self._next_guide_ui_order(binding, group_id, exclude=moved),
            )
            self.cmds.select(moved, replace=True)
        return moved

    def reorder_guide(self, settings_node: str, node: str, delta: int) -> int:
        binding = self.bind(settings_node)
        self._ensure_guide_management_metadata(binding)
        node = self._canonical_owned_node(node, self._owned_guide_nodes(binding))
        if not node:
            raise ValueError("Guide is not owned by the current system")
        group_id = self._string_attr(node, GUIDE_GROUP_ID, "")
        siblings = [
            item
            for item in self._owned_guide_nodes(binding)
            if self._string_attr(item, GUIDE_GROUP_ID, "") == group_id
        ]
        siblings.sort(
            key=lambda item: (
                self._int_attr(item, GUIDE_UI_ORDER, 0),
                self._guide_id(item),
            )
        )
        old_index = siblings.index(node)
        new_index = max(0, min(len(siblings) - 1, old_index + int(delta)))
        if new_index == old_index:
            return old_index
        siblings.pop(old_index)
        siblings.insert(new_index, node)
        with self.user_undo_chunk("Bifrost Scales Reorder Guides"):
            for index, item in enumerate(siblings):
                self._ensure_int(item, GUIDE_UI_ORDER, index)
        return new_index

    def reorder_guide_group(self, settings_node: str, node: str, delta: int) -> int:
        binding = self.bind(settings_node)
        groups = self.list_guide_groups(settings_node)
        node = self._canonical_owned_node(node, groups)
        if not node:
            raise ValueError("Guide group is not owned by the current system")
        parent = self._group_parent_node(binding, node, groups)
        siblings = [
            group
            for group in groups
            if self._group_parent_node(binding, group, groups) == parent
        ]
        old_index = siblings.index(node)
        new_index = max(0, min(len(siblings) - 1, old_index + int(delta)))
        if new_index == old_index:
            return old_index
        siblings.pop(old_index)
        siblings.insert(new_index, node)
        with self.user_undo_chunk("Bifrost Scales Reorder Guide Groups"):
            for index, item in enumerate(siblings):
                self._ensure_int(item, GUIDE_GROUP_ORDER, index)
        return new_index
    def apply_guide_tree_layout(
        self,
        settings_node: str,
        ordered_groups: list[str],
        guides_by_group: dict[str, list[str]],
        group_parents: dict[str, str] | None = None,
    ) -> None:
        """Apply one validated drag/drop layout without touching evaluation order."""

        binding = self.bind(settings_node)
        self._ensure_guide_management_metadata(binding)
        current_groups = self.list_guide_groups(settings_node)
        canonical_groups = [
            self._canonical_owned_node(node, current_groups) for node in ordered_groups
        ]
        if (
            any(not node for node in canonical_groups)
            or len(canonical_groups) != len(current_groups)
            or set(canonical_groups) != set(current_groups)
        ):
            raise ValueError("Guide group layout must contain every group exactly once")
        group_ids = {
            node: self._string_attr(node, GUIDE_GROUP_ID, "")
            for node in canonical_groups
        }
        if not all(group_ids.values()) or len(set(group_ids.values())) != len(group_ids):
            raise ValueError("Guide groups must have unique stable IDs")
        ordered_group_ids = [group_ids[node] for node in canonical_groups]

        parent_by_id: dict[str, str] = {}
        if group_parents is None:
            parent_by_id = {group_id: "" for group_id in ordered_group_ids}
        else:
            for raw_group, raw_parent in group_parents.items():
                group = self._canonical_owned_node(raw_group, current_groups)
                if not group or group_ids[group] in parent_by_id:
                    raise ValueError("Guide group parent layout is invalid")
                parent = ""
                if raw_parent:
                    parent = self._canonical_owned_node(raw_parent, current_groups)
                    if not parent or parent == group:
                        raise ValueError("Guide group cannot parent itself")
                parent_by_id[group_ids[group]] = group_ids[parent] if parent else ""
            if set(parent_by_id) != set(ordered_group_ids):
                raise ValueError("Guide group parent layout must contain every group")

        def depth(group_id: str) -> int:
            seen: set[str] = set()
            current = group_id
            value = 0
            while parent_by_id.get(current, ""):
                if current in seen:
                    raise ValueError("Guide group layout contains a cycle")
                seen.add(current)
                current = parent_by_id[current]
                if current not in parent_by_id:
                    raise ValueError("Guide group layout contains an unknown parent")
                value += 1
            return value

        depths = {group_id: depth(group_id) for group_id in ordered_group_ids}
        current_guides = self._owned_guide_nodes(binding)
        guide_ids = {node: self._guide_id(node) for node in current_guides}
        canonical_layout: dict[str, list[str]] = {}
        flattened: list[str] = []
        for raw_group, raw_guides in guides_by_group.items():
            if raw_group:
                group = self._canonical_owned_node(raw_group, current_groups)
                if not group:
                    raise ValueError("Guide layout contains an unknown group")
                group_id = group_ids[group]
            else:
                group_id = ""
            if group_id in canonical_layout:
                raise ValueError("Guide layout contains a duplicate container")
            canonical_guides = [
                self._canonical_owned_node(node, current_guides) for node in raw_guides
            ]
            if any(not node for node in canonical_guides):
                raise ValueError("Guide layout contains an unknown guide")
            stable_ids = [guide_ids[node] for node in canonical_guides]
            canonical_layout[group_id] = stable_ids
            flattened.extend(stable_ids)
        if len(flattened) != len(current_guides) or set(flattened) != set(
            guide_ids.values()
        ):
            raise ValueError("Guide layout must contain every guide exactly once")
        canonical_layout.setdefault("", [])
        for group_id in ordered_group_ids:
            canonical_layout.setdefault(group_id, [])

        order_index = {group_id: index for index, group_id in enumerate(ordered_group_ids)}
        with self.user_undo_chunk("Bifrost Scales Arrange Guide Tree"):
            for group_id in sorted(
                ordered_group_ids,
                key=lambda item: (depths[item], order_index[item]),
            ):
                group = self._group_node_for_stable_id(binding, group_id)
                parent_id = parent_by_id[group_id]
                destination = (
                    self._group_node_for_stable_id(binding, parent_id)
                    if parent_id
                    else binding.guide_root
                )
                if not group or not destination:
                    raise ValueError("Guide group layout could not be resolved")
                current_parent = self._group_parent_node(binding, group)
                current_parent_id = (
                    self._string_attr(current_parent, GUIDE_GROUP_ID, "")
                    if current_parent
                    else ""
                )
                if current_parent_id != parent_id:
                    self.cmds.parent(group, destination)

            sibling_orders: dict[str, int] = {}
            for group_id in ordered_group_ids:
                parent_id = parent_by_id[group_id]
                group = self._group_node_for_stable_id(binding, group_id)
                index = sibling_orders.get(parent_id, 0)
                self._ensure_int(group, GUIDE_GROUP_ORDER, index)
                sibling_orders[parent_id] = index + 1

            for group_id in [""] + ordered_group_ids:
                destination = (
                    self._group_node_for_stable_id(binding, group_id)
                    if group_id
                    else binding.guide_root
                )
                for index, guide_id in enumerate(canonical_layout[group_id]):
                    guide = self._guide_node_for_stable_id(binding, guide_id)
                    if not guide or not destination:
                        raise ValueError("Guide layout could not be resolved")
                    parents = self.cmds.listRelatives(
                        guide, parent=True, fullPath=True
                    ) or []
                    parent = str(parents[0]) if parents else ""
                    moved = guide
                    if self._canonical_node_name(parent) != self._canonical_node_name(
                        destination
                    ):
                        parented = self.cmds.parent(guide, destination) or [guide]
                        moved = self._long_node_name(str(parented[0]))
                    self._ensure_string(moved, GUIDE_GROUP_ID, group_id)
                    self._ensure_int(moved, GUIDE_UI_ORDER, index)
    def reorder_guides(self, settings_node: str, ordered_nodes: list[str]) -> list[str]:
        """Compatibility API: reorder guides within their current containers."""

        binding = self.bind(settings_node)
        current = self.list_guides(settings_node)
        requested = [self._canonical_owned_node(node, current) for node in ordered_nodes]
        if any(not node for node in requested) or len(requested) != len(current) or set(requested) != set(current):
            raise ValueError("Guide order must contain every guide exactly once")
        groups = self.list_guide_groups(settings_node)
        by_group: dict[str, list[str]] = {"": []}
        for group in groups:
            by_group[group] = []
        group_by_id = {
            self._string_attr(group, GUIDE_GROUP_ID, ""): group for group in groups
        }
        for guide in requested:
            group_id = self._string_attr(guide, GUIDE_GROUP_ID, "")
            by_group[group_by_id.get(group_id, "")].append(guide)
        self.apply_guide_tree_layout(settings_node, groups, by_group)
        return self.list_guides(settings_node)

    def delete_guide(self, node: str) -> None:
        if not node or not self.cmds.objExists(node):
            return
        if not self.cmds.attributeQuery(GUIDE_MARKER, node=node, exists=True):
            raise ValueError("Node is not an owned Bifrost Scales guide")
        with self.user_undo_chunk("Bifrost Scales Delete Guide"):
            self.cmds.delete(node)

    def delete_guide_group(self, settings_node: str, node: str) -> list[str]:
        binding = self.bind(settings_node)
        groups = self._owned_group_nodes(binding)
        node = self._canonical_owned_node(node, groups)
        if not node:
            raise ValueError("Guide group is not owned by the current system")
        group_id = self._string_attr(node, GUIDE_GROUP_ID, "")
        parent_group = self._group_parent_node(binding, node, groups)
        parent_group_id = (
            self._string_attr(parent_group, GUIDE_GROUP_ID, "")
            if parent_group
            else ""
        )
        members = [
            item
            for item in self._owned_guide_nodes(binding)
            if self._string_attr(item, GUIDE_GROUP_ID, "") == group_id
        ]
        members.sort(
            key=lambda item: (
                self._int_attr(item, GUIDE_UI_ORDER, 0),
                self._guide_id(item),
            )
        )
        child_groups = [
            group
            for group in groups
            if self._group_parent_node(binding, group, groups) == node
        ]
        child_groups.sort(
            key=lambda item: (
                self._int_attr(item, GUIDE_GROUP_ORDER, 0),
                self._string_attr(item, GUIDE_GROUP_ID, ""),
            )
        )
        guide_start = self._next_guide_ui_order(binding, parent_group_id)
        sibling_orders = [
            self._int_attr(group, GUIDE_GROUP_ORDER, -1)
            for group in groups
            if group != node
            and self._group_parent_node(binding, group, groups) == parent_group
        ]
        group_start = max(sibling_orders, default=-1) + 1
        destination = parent_group or binding.guide_root
        moved_members: list[str] = []
        with self.user_undo_chunk("Bifrost Scales Delete Guide Group"):
            for offset, child in enumerate(child_groups):
                child_id = self._string_attr(child, GUIDE_GROUP_ID, "")
                current = self._group_node_for_stable_id(binding, child_id)
                parented = self.cmds.parent(current, destination) or [current]
                moved = self._long_node_name(str(parented[0]))
                self._ensure_int(moved, GUIDE_GROUP_ORDER, group_start + offset)
            for offset, guide in enumerate(members):
                guide_id = self._guide_id(guide)
                current = self._guide_node_for_stable_id(binding, guide_id)
                parented = self.cmds.parent(current, destination) or [current]
                moved = self._long_node_name(str(parented[0]))
                self._ensure_string(moved, GUIDE_GROUP_ID, parent_group_id)
                self._ensure_int(moved, GUIDE_UI_ORDER, guide_start + offset)
                moved_members.append(moved)
            current_group = self._group_node_for_stable_id(binding, group_id)
            self.cmds.delete(current_group)
        return moved_members
    def select_guide(self, node: str) -> None:
        self.select_guide_item(node)

    def select_guide_item(self, node: str) -> None:
        self.select_guide_items([node])

    def select_guide_items(self, nodes: list[str] | tuple[str, ...]) -> None:
        selected: list[str] = []
        for node in nodes:
            node = str(node)
            if not node or not self.cmds.objExists(node):
                raise ValueError("Guide item does not exist")
            is_guide = bool(
                self.cmds.attributeQuery(GUIDE_MARKER, node=node, exists=True)
                and self.cmds.getAttr(node + "." + GUIDE_MARKER)
            )
            is_group = bool(
                self.cmds.attributeQuery(GUIDE_GROUP_MARKER, node=node, exists=True)
                and self.cmds.getAttr(node + "." + GUIDE_GROUP_MARKER)
            )
            if not (is_guide or is_group):
                raise ValueError("Node is not a Bifrost Scales guide item")
            if node not in selected:
                selected.append(node)
        if selected:
            self.cmds.select(selected, replace=True)
        else:
            self.cmds.select(clear=True)

    def selected_guide_item(self, settings_node: str) -> str:
        selected = self.selected_guide_items(settings_node)
        return selected[0] if selected else ""

    def _maya_selected_objects(self) -> list[str]:
        try:
            return list(
                self.cmds.ls(
                    selection=True,
                    long=True,
                    objectsOnly=True,
                )
                or []
            )
        except Exception:
            return list(self.cmds.ls(selection=True, long=True) or [])

    def _resolve_selected_guide_items(
        self,
        binding: SystemBinding,
        selection: list[str] | tuple[str, ...],
    ) -> tuple[list[str], bool]:
        owned_nodes = self._owned_guide_nodes(binding) + self._owned_group_nodes(binding)
        owned = {
            self._canonical_node_name(node): node for node in owned_nodes
        }
        result: list[str] = []
        seen: set[str] = set()
        unmatched = False
        for selected in selection:
            candidate = str(selected).split(".", 1)[0]
            visited: set[str] = set()
            resolved = ""
            while candidate and candidate not in visited and self.cmds.objExists(candidate):
                visited.add(candidate)
                resolved = owned.get(self._canonical_node_name(candidate), "")
                if resolved:
                    break
                try:
                    parents = self.cmds.listRelatives(
                        candidate,
                        parent=True,
                        fullPath=True,
                    ) or []
                except Exception:
                    parents = []
                candidate = str(parents[0]) if parents else ""
            if not resolved:
                unmatched = True
                continue
            canonical = self._canonical_node_name(resolved)
            if canonical not in seen:
                result.append(resolved)
                seen.add(canonical)
        return result, unmatched

    def selected_guide_items(self, settings_node: str) -> list[str]:
        binding = self.bind(settings_node)
        selection = self._maya_selected_objects()
        self._adopt_selected_maya_guide_groups(binding, selection)
        return self._resolve_selected_guide_items(binding, selection)[0]

    def guide_grouping_selection(
        self,
        settings_node: str,
    ) -> tuple[list[str], bool, bool]:
        binding = self.bind(settings_node)
        selected, unmatched = self._resolve_selected_guide_items(
            binding,
            self._maya_selected_objects(),
        )
        owned_guides = {
            self._canonical_node_name(node): node
            for node in self._owned_guide_nodes(binding)
        }
        guides = [
            owned_guides[self._canonical_node_name(node)]
            for node in selected
            if self._canonical_node_name(node) in owned_guides
        ]
        has_guide_items = bool(selected)
        mixed = unmatched or len(guides) != len(selected)
        return guides, has_guide_items, mixed

    def selected_guides(
        self,
        settings_node: str,
        guide_nodes: list[str] | tuple[str, ...] | None = None,
    ) -> list[str]:
        allowed = (
            [str(node) for node in guide_nodes]
            if guide_nodes is not None
            else self.list_guides(settings_node)
        )
        canonical = {
            self._canonical_node_name(node): node for node in allowed
        }
        result: list[str] = []
        for selected in self.selected_guide_items(settings_node):
            node = canonical.get(self._canonical_node_name(selected))
            if node is not None:
                result.append(node)
        return result

    def guide_stage(self, node: str) -> str:
        try:
            guide = self.read_guide(node, effective=True)
            if guide.affects_direction and (guide.affects_density or guide.affects_size):
                return "combined"
            if guide.affects_direction:
                return "direction"
            return "density"
        except Exception:
            return "density"

    def _create_guide_root(self, root: str, system_id: str) -> str:
        guide_root = str(
            self.cmds.createNode(
                "transform",
                name="bifrostScalesGuides#",
                parent=root,
            )
        )
        self._ensure_bool(guide_root, GUIDE_ROOT_MARKER, True)
        self._ensure_string(guide_root, SYSTEM_ID, system_id)
        return guide_root

    def _guide_root_for_settings(
        self,
        settings_node: str,
        preview_transform: str,
        system_id: str,
    ) -> str:
        self._ensure_message(settings_node, GUIDE_ROOT_MESSAGE)
        connected = self.cmds.listConnections(
            settings_node + "." + GUIDE_ROOT_MESSAGE,
            source=True,
            destination=False,
        ) or []
        for node in connected:
            if self.cmds.objExists(node) and self.cmds.nodeType(node) == "transform":
                return str(node)
        parents = self.cmds.listRelatives(preview_transform, parent=True, fullPath=True) or []
        root = str(parents[0]) if parents else self._ensure_root()
        guide_root = self._create_guide_root(root, system_id)
        self.cmds.connectAttr(
            guide_root + ".message",
            settings_node + "." + GUIDE_ROOT_MESSAGE,
            force=True,
        )
        return guide_root

    @staticmethod
    def _guide_display_color(kind: GuideKind, use_mask: bool) -> tuple[float, float, float]:
        if use_mask:
            return (1.0, 0.08, 0.72)
        if kind == GuideKind.FLOW_CURVE:
            return (0.15, 0.85, 0.85)
        if kind.stage == "density":
            return (0.2, 0.85, 0.35)
        return (0.2, 0.55, 1.0)

    def _style_guide_node(
        self,
        node: str,
        kind: GuideKind,
        use_mask: bool,
    ) -> None:
        """Keep mask guides visibly magenta in the Maya viewport."""

        if not node or not self.cmds.objExists(node):
            return
        shapes = self.cmds.listRelatives(
            node,
            shapes=True,
            noIntermediate=True,
            fullPath=True,
        ) or []
        color = self._guide_display_color(kind, bool(use_mask))
        for shape in shapes:
            for plug, value, kwargs in (
                (str(shape) + ".overrideEnabled", True, {}),
                (str(shape) + ".overrideRGBColors", True, {}),
                (str(shape) + ".overrideColorRGB", color, {"type": "double3"}),
                (str(shape) + ".alwaysDrawOnTop", True, {}),
                (str(shape) + ".lineWidth", 4.0, {}),
            ):
                matches = False
                try:
                    current = self.cmds.getAttr(plug)
                    if isinstance(value, tuple):
                        if (
                            isinstance(current, (list, tuple))
                            and len(current) == 1
                            and isinstance(current[0], (list, tuple))
                        ):
                            current = current[0]
                        current_values = tuple(current)
                        matches = len(current_values) == len(value) and all(
                            abs(float(actual) - float(expected)) <= 1.0e-6
                            for actual, expected in zip(current_values, value)
                        )
                    else:
                        matches = current == value
                except Exception:
                    pass
                if matches:
                    continue
                try:
                    if isinstance(value, tuple):
                        self.cmds.setAttr(plug, *value, **kwargs)
                    else:
                        self.cmds.setAttr(plug, value, **kwargs)
                except Exception:
                    pass

    def _initialize_guide(
        self,
        node: str,
        binding: SystemBinding,
        kind: GuideKind,
    ) -> None:
        self._ensure_guide_management_metadata(binding)
        guide_id = "guide_" + uuid.uuid4().hex
        self._ensure_bool(node, GUIDE_MARKER, True)
        self._ensure_string(node, SYSTEM_ID, binding.system_id)
        self._ensure_string(node, GUIDE_ID, guide_id)
        self._ensure_string(node, GUIDE_KIND, kind.value)
        self._ensure_string(
            node,
            GUIDE_DISPLAY_NAME,
            self._next_guide_display_name(binding),
        )
        self._ensure_int(
            node,
            GUIDE_ORDER,
            self._next_guide_evaluation_order(binding, exclude=node),
        )
        self._ensure_string(node, GUIDE_GROUP_ID, "")
        self._ensure_bool(node, GUIDE_SYMMETRY_ENABLED, False)
        self._ensure_string(node, GUIDE_SYMMETRY_AXIS, "x")
        self._ensure_string(node, GUIDE_SYMMETRY_SPACE, "world")
        self._ensure_int(
            node,
            GUIDE_UI_ORDER,
            self._next_guide_ui_order(binding, "", exclude=node),
        )
        self._ensure_bool(node, GUIDE_ENABLED, True)
        self._ensure_double(node, GUIDE_RADIUS, 1.0)
        self._ensure_double(node, GUIDE_FALLOFF, 1.0)
        self._ensure_double(node, GUIDE_DENSITY_MULTIPLIER, 1.75)
        self._ensure_double(node, GUIDE_SIZE_MULTIPLIER, 1.0)
        self._ensure_double(node, GUIDE_STRENGTH, 1.0)
        self._ensure_double(node, GUIDE_CENTER_ALIGNMENT, 0.35)
        self._ensure_double(node, GUIDE_CELL_ANISOTROPY, 1.0)
        self._ensure_double(node, GUIDE_ANGLE, 0.0)
        self._ensure_bool(node, GUIDE_CLOSED, False)
        self._ensure_bool(node, GUIDE_USE_DENSITY, kind.default_use_density)
        self._ensure_bool(node, GUIDE_USE_SIZE, kind.default_use_size)
        self._ensure_bool(node, GUIDE_USE_DIRECTION, kind.default_use_direction)
        self._ensure_bool(node, GUIDE_USE_MASK, False)
        self._style_guide_node(node, kind, False)

    def _owned_guide_nodes(self, binding: SystemBinding) -> list[str]:
        descendants = self.cmds.listRelatives(
            binding.guide_root,
            allDescendents=True,
            fullPath=True,
            type="transform",
        ) or []
        result: list[str] = []
        for node in descendants:
            try:
                if not (
                    self.cmds.attributeQuery(GUIDE_MARKER, node=node, exists=True)
                    and bool(self.cmds.getAttr(node + "." + GUIDE_MARKER))
                    and self.cmds.attributeQuery(SYSTEM_ID, node=node, exists=True)
                    and self._string_attr(node, SYSTEM_ID, "") == binding.system_id
                ):
                    continue
                result.append(str(node))
            except Exception:
                continue
        return result

    def _owned_group_nodes(self, binding: SystemBinding) -> list[str]:
        descendants = self.cmds.listRelatives(
            binding.guide_root,
            allDescendents=True,
            fullPath=True,
            type="transform",
        ) or []
        result: list[str] = []
        for node in descendants:
            try:
                if not (
                    self.cmds.attributeQuery(GUIDE_GROUP_MARKER, node=node, exists=True)
                    and bool(self.cmds.getAttr(node + "." + GUIDE_GROUP_MARKER))
                    and self.cmds.attributeQuery(SYSTEM_ID, node=node, exists=True)
                    and self._string_attr(node, SYSTEM_ID, "") == binding.system_id
                ):
                    continue
                result.append(str(node))
            except Exception:
                continue
        return result

    def _group_parent_node(
        self,
        binding: SystemBinding,
        node: str,
        groups: list[str] | None = None,
    ) -> str:
        groups = self._owned_group_nodes(binding) if groups is None else groups
        parents = self.cmds.listRelatives(node, parent=True, fullPath=True) or []
        if not parents:
            return ""
        return self._canonical_owned_node(str(parents[0]), groups)

    def _group_node_for_stable_id(self, binding: SystemBinding, group_id: str) -> str:
        if not group_id:
            return ""
        matches = [
            node
            for node in self._owned_group_nodes(binding)
            if self._string_attr(node, GUIDE_GROUP_ID, "") == group_id
        ]
        return matches[0] if len(matches) == 1 else ""

    def _guide_node_for_stable_id(self, binding: SystemBinding, guide_id: str) -> str:
        matches = [
            node for node in self._owned_guide_nodes(binding) if self._guide_id(node) == guide_id
        ]
        return matches[0] if len(matches) == 1 else ""
    def _adopt_selected_maya_guide_groups(
        self,
        binding: SystemBinding,
        selection: list[str] | tuple[str, ...],
    ) -> None:
        root = self._canonical_node_name(binding.guide_root)
        order = max(
            (
                self._int_attr(node, GUIDE_GROUP_ORDER, -1)
                for node in self._owned_group_nodes(binding)
            ),
            default=-1,
        ) + 1
        for selected in selection:
            group = str(selected).split(".", 1)[0]
            if not group or not self.cmds.objExists(group):
                continue
            try:
                if self.cmds.nodeType(group) != "transform":
                    continue
                parents = self.cmds.listRelatives(
                    group,
                    parent=True,
                    fullPath=True,
                ) or []
                if (
                    not parents
                    or self._canonical_node_name(str(parents[0])) != root
                    or self.cmds.attributeQuery(
                        GUIDE_MARKER,
                        node=group,
                        exists=True,
                    )
                    or self.cmds.attributeQuery(
                        GUIDE_GROUP_MARKER,
                        node=group,
                        exists=True,
                    )
                ):
                    continue
                children = self.cmds.listRelatives(
                    group,
                    children=True,
                    fullPath=True,
                    type="transform",
                ) or []
                guides = [
                    str(node)
                    for node in children
                    if self.cmds.attributeQuery(
                        GUIDE_MARKER,
                        node=node,
                        exists=True,
                    )
                    and bool(self.cmds.getAttr(str(node) + "." + GUIDE_MARKER))
                    and self._string_attr(str(node), SYSTEM_ID, "")
                    == binding.system_id
                ]
                if not guides or len(guides) != len(children):
                    continue
            except Exception:
                continue
            with self._automatic_update_guard():
                group_id = self._initialize_guide_group(
                    group,
                    binding,
                    str(group).split("|")[-1],
                    order,
                )
                for index, guide in enumerate(guides):
                    self._ensure_string(guide, GUIDE_GROUP_ID, group_id)
                    self._ensure_int(guide, GUIDE_UI_ORDER, index)
            order += 1

    def _ensure_guide_management_metadata(self, binding: SystemBinding) -> None:
        """Lazily migrate older guides/groups without changing evaluation order."""

        groups = sorted(self._owned_group_nodes(binding))
        guides = sorted(self._owned_guide_nodes(binding))
        with self._automatic_update_guard():
            existing_group_orders = [
                self._int_attr(node, GUIDE_GROUP_ORDER, -1)
                for node in groups
                if self.cmds.attributeQuery(GUIDE_GROUP_ORDER, node=node, exists=True)
            ]
            next_group_order = max(existing_group_orders, default=-1) + 1
            used_group_names = {
                self._string_attr(node, GUIDE_GROUP_NAME, "").strip()
                for node in groups
                if self._string_attr(node, GUIDE_GROUP_NAME, "").strip()
            }
            for node in groups:
                if not self.cmds.attributeQuery(GUIDE_GROUP_ID, node=node, exists=True):
                    self._ensure_string(node, GUIDE_GROUP_ID, "group_" + uuid.uuid4().hex)
                if not self.cmds.attributeQuery(GUIDE_GROUP_ORDER, node=node, exists=True):
                    self._ensure_int(node, GUIDE_GROUP_ORDER, next_group_order)
                    next_group_order += 1
                if not self.cmds.attributeQuery(GUIDE_GROUP_NAME, node=node, exists=True):
                    suffix = max(1, self._int_attr(node, GUIDE_GROUP_ORDER, 0) + 1)
                    candidate = "Group {}".format(suffix)
                    while candidate in used_group_names:
                        suffix += 1
                        candidate = "Group {}".format(suffix)
                    self._ensure_string(node, GUIDE_GROUP_NAME, candidate)
                    used_group_names.add(candidate)
                defaults = (
                    (GUIDE_GROUP_COLLAPSED, "bool", False),
                    (GUIDE_GROUP_ENABLED, "bool", True),
                    (GUIDE_GROUP_RADIUS_MULTIPLIER, "double", 1.0),
                    (GUIDE_GROUP_FALLOFF_MULTIPLIER, "double", 1.0),
                    (GUIDE_GROUP_DENSITY_STRENGTH, "double", 1.0),
                    (GUIDE_GROUP_SIZE_STRENGTH, "double", 1.0),
                    (GUIDE_GROUP_DIRECTION_STRENGTH, "double", 1.0),
                    (GUIDE_GROUP_ANGLE_OFFSET, "double", 0.0),
                    (GUIDE_GROUP_SYMMETRY_ENABLED, "bool", False),
                    (GUIDE_GROUP_SYMMETRY_AXIS, "string", "x"),
                    (GUIDE_GROUP_SYMMETRY_SPACE, "string", "world"),
                )
                for attribute, kind, value in defaults:
                    if self.cmds.attributeQuery(attribute, node=node, exists=True):
                        continue
                    if kind == "bool":
                        self._ensure_bool(node, attribute, bool(value))
                    elif kind == "string":
                        self._ensure_string(node, attribute, str(value))
                    else:
                        self._ensure_double(node, attribute, float(value))

            group_ids = {
                node: self._string_attr(node, GUIDE_GROUP_ID, "") for node in groups
            }

            existing_evaluation = [
                self._int_attr(node, GUIDE_ORDER, -1)
                for node in guides
                if self.cmds.attributeQuery(GUIDE_ORDER, node=node, exists=True)
            ]
            next_evaluation = max(existing_evaluation, default=-1) + 1
            for node in guides:
                if not self.cmds.attributeQuery(GUIDE_ORDER, node=node, exists=True):
                    self._ensure_int(node, GUIDE_ORDER, next_evaluation)
                    next_evaluation += 1

            used_names = {
                self._string_attr(node, GUIDE_DISPLAY_NAME, "").strip()
                for node in guides
                if self._string_attr(node, GUIDE_DISPLAY_NAME, "").strip()
            }
            for node in guides:
                current_name = self._string_attr(node, GUIDE_DISPLAY_NAME, "").strip()
                if not current_name:
                    suffix = max(1, self._guide_order(node) + 1)
                    candidate = "Guide {}".format(suffix)
                    while candidate in used_names:
                        suffix += 1
                        candidate = "Guide {}".format(suffix)
                    self._ensure_string(node, GUIDE_DISPLAY_NAME, candidate)
                    used_names.add(candidate)

                if not self.cmds.attributeQuery(
                    GUIDE_SYMMETRY_ENABLED,
                    node=node,
                    exists=True,
                ):
                    self._ensure_bool(node, GUIDE_SYMMETRY_ENABLED, False)
                if not self.cmds.attributeQuery(
                    GUIDE_SYMMETRY_AXIS,
                    node=node,
                    exists=True,
                ):
                    self._ensure_string(node, GUIDE_SYMMETRY_AXIS, "x")
                if not self.cmds.attributeQuery(
                    GUIDE_SYMMETRY_SPACE,
                    node=node,
                    exists=True,
                ):
                    self._ensure_string(node, GUIDE_SYMMETRY_SPACE, "world")
                if not self.cmds.attributeQuery(GUIDE_USE_MASK, node=node, exists=True):
                    self._ensure_bool(node, GUIDE_USE_MASK, False)
                if not self.cmds.attributeQuery(
                    GUIDE_CENTER_ALIGNMENT, node=node, exists=True
                ):
                    self._ensure_double(node, GUIDE_CENTER_ALIGNMENT, 0.35)
                if not self.cmds.attributeQuery(
                    GUIDE_CELL_ANISOTROPY, node=node, exists=True
                ):
                    self._ensure_double(node, GUIDE_CELL_ANISOTROPY, 1.0)
                try:
                    kind = GuideKind(self._string_attr(node, GUIDE_KIND, GuideKind.DENSITY_POINT.value))
                except Exception:
                    kind = GuideKind.DENSITY_POINT
                self._style_guide_node(
                    node,
                    kind,
                    self._bool_attr(node, GUIDE_USE_MASK, False),
                )

                parents = self.cmds.listRelatives(
                    node, parent=True, fullPath=True
                ) or []
                parent = str(parents[0]) if parents else ""
                desired_group_id = group_ids.get(parent, "")
                self._ensure_string(node, GUIDE_GROUP_ID, desired_group_id)

            by_group: dict[str, list[str]] = {}
            for node in guides:
                group_id = self._string_attr(node, GUIDE_GROUP_ID, "")
                by_group.setdefault(group_id, []).append(node)
            for group_id, members in by_group.items():
                used_ui_orders = {
                    self._int_attr(node, GUIDE_UI_ORDER, 0)
                    for node in members
                    if self.cmds.attributeQuery(GUIDE_UI_ORDER, node=node, exists=True)
                }
                next_ui_order = max(used_ui_orders, default=-1) + 1
                for node in sorted(
                    members,
                    key=lambda item: (self._guide_order(item), self._guide_id(item), item),
                ):
                    if self.cmds.attributeQuery(GUIDE_UI_ORDER, node=node, exists=True):
                        continue
                    preferred = self._guide_order(node)
                    value = preferred if preferred not in used_ui_orders else next_ui_order
                    while value in used_ui_orders:
                        value += 1
                    self._ensure_int(node, GUIDE_UI_ORDER, value)
                    used_ui_orders.add(value)
                    next_ui_order = max(next_ui_order, value + 1)

    def _next_guide_display_name(self, binding: SystemBinding) -> str:
        existing = {
            self._string_attr(node, GUIDE_DISPLAY_NAME, "")
            for node in self._owned_guide_nodes(binding)
        }
        index = 1
        while "Guide {}".format(index) in existing:
            index += 1
        return "Guide {}".format(index)

    def _next_group_display_name(self, binding: SystemBinding) -> str:
        existing = {
            self._string_attr(node, GUIDE_GROUP_NAME, "")
            for node in self._owned_group_nodes(binding)
        }
        index = 1
        while "Group {}".format(index) in existing:
            index += 1
        return "Group {}".format(index)

    def _next_guide_ui_order(
        self,
        binding: SystemBinding,
        group_id: str,
        exclude: str = "",
    ) -> int:
        values = [
            self._int_attr(node, GUIDE_UI_ORDER, -1)
            for node in self._owned_guide_nodes(binding)
            if node != exclude
            and self._string_attr(node, GUIDE_GROUP_ID, "") == group_id
        ]
        return max(values, default=-1) + 1

    def _next_guide_evaluation_order(
        self,
        binding: SystemBinding,
        exclude: str = "",
    ) -> int:
        values = [
            self._int_attr(node, GUIDE_ORDER, -1)
            for node in self._owned_guide_nodes(binding)
            if node != exclude
        ]
        return max(values, default=-1) + 1

    def _group_node_for_id(self, guide_node: str, group_id: str) -> str:
        if not group_id:
            return ""
        parents = self.cmds.listRelatives(
            guide_node,
            parent=True,
            fullPath=True,
        ) or []
        parent = str(parents[0]) if parents else ""
        if not parent or not self.cmds.objExists(parent):
            return ""
        if not self.cmds.attributeQuery(GUIDE_GROUP_MARKER, node=parent, exists=True):
            return ""
        return parent if self._string_attr(parent, GUIDE_GROUP_ID, "") == group_id else ""

    def _long_node_name(self, node: str) -> str:
        text = str(node)
        try:
            matches = [str(item) for item in (self.cmds.ls(text, long=True) or [])]
        except Exception:
            return text
        if text in matches:
            return text
        if len(matches) == 1:
            return matches[0]
        short_name = text.rsplit("|", 1)[-1]
        suffix_matches = [
            item for item in matches if item.rsplit("|", 1)[-1] == short_name
        ]
        return suffix_matches[0] if len(suffix_matches) == 1 else text

    def _canonical_owned_node(self, node: str, candidates: list[str]) -> str:
        text = str(node)
        if text in candidates:
            return text
        resolved = self._long_node_name(text)
        if resolved in candidates:
            return resolved
        canonical = self._canonical_node_name(text)
        matches = [
            candidate
            for candidate in candidates
            if self._canonical_node_name(candidate) == canonical
        ]
        return matches[0] if len(matches) == 1 else ""

    def _string_attr(self, node: str, attribute: str, default: str) -> str:
        try:
            if self.cmds.attributeQuery(attribute, node=node, exists=True):
                return str(self.cmds.getAttr(node + "." + attribute) or "")
        except Exception:
            pass
        return str(default)

    def _node_locked(self, node: str) -> bool:
        try:
            values = self.cmds.lockNode(node, query=True, lock=True) or []
            return bool(values[0]) if values else False
        except Exception:
            return False

    def _bool_attr(self, node: str, attribute: str, default: bool) -> bool:
        try:
            if self.cmds.attributeQuery(attribute, node=node, exists=True):
                return bool(self.cmds.getAttr(node + "." + attribute))
        except Exception:
            pass
        return bool(default)

    def _int_attr(self, node: str, attribute: str, default: int) -> int:
        try:
            if self.cmds.attributeQuery(attribute, node=node, exists=True):
                return int(self.cmds.getAttr(node + "." + attribute))
        except Exception:
            pass
        return int(default)

    def _double_attr(self, node: str, attribute: str, default: float) -> float:
        try:
            if self.cmds.attributeQuery(attribute, node=node, exists=True):
                return float(self.cmds.getAttr(node + "." + attribute))
        except Exception:
            pass
        return float(default)

    def _guide_display_name(self, node: str) -> str:
        value = self._string_attr(node, GUIDE_DISPLAY_NAME, "").strip()
        return value[:64] if value else str(node).split("|")[-1]

    def _guide_order(self, node: str) -> int:
        return self._int_attr(node, GUIDE_ORDER, 2147483647)

    def _guide_id(self, node: str) -> str:
        value = self._string_attr(node, GUIDE_ID, "")
        return value if value else str(node)

    def _canonical_node_name(self, node: str) -> str:
        try:
            matches = self.cmds.ls(str(node), long=True) or []
            if matches:
                return str(matches[0])
        except Exception:
            pass
        return str(node)

    def _guide_role_value(self, node: str, attribute: str, default: bool) -> bool:
        try:
            if self.cmds.attributeQuery(attribute, node=node, exists=True):
                return bool(self.cmds.getAttr(node + "." + attribute))
        except Exception:
            pass
        return bool(default)

    def _target_center(self, target_mesh: str) -> tuple[float, float, float]:
        try:
            bounds = self.cmds.exactWorldBoundingBox(target_mesh)
            return (
                0.5 * (float(bounds[0]) + float(bounds[3])),
                0.5 * (float(bounds[1]) + float(bounds[4])),
                0.5 * (float(bounds[2]) + float(bounds[5])),
            )
        except Exception:
            return (0.0, 0.0, 0.0)

    @staticmethod
    def _symmetry_axis_vector(axis: str) -> tuple[float, float, float]:
        normalized = str(axis).strip().lower()
        if normalized == "y":
            return (0.0, 1.0, 0.0)
        if normalized == "z":
            return (0.0, 0.0, 1.0)
        return (1.0, 0.0, 0.0)

    def _resolve_guide_symmetry_frame(
        self,
        guide: GuideData,
        target_mesh: str,
    ) -> GuideData:
        """Resolve World or Target Local symmetry to one world-space plane."""

        normalized = guide.normalized()
        fallback = self._symmetry_axis_vector(normalized.symmetry_axis)
        if normalized.symmetry_space != "target_local":
            return normalized.with_symmetry_frame((0.0, 0.0, 0.0), fallback)

        target_transform = str(target_mesh)
        try:
            if self.cmds.nodeType(target_transform) != "transform":
                parents = self.cmds.listRelatives(
                    target_transform,
                    parent=True,
                    fullPath=True,
                ) or []
                if parents:
                    target_transform = str(parents[0])
            matrix = self.cmds.xform(
                target_transform,
                query=True,
                worldSpace=True,
                matrix=True,
            )
            origin = (
                float(matrix[12]),
                float(matrix[13]),
                float(matrix[14]),
            )
            start = {"x": 0, "y": 4, "z": 8}.get(
                normalized.symmetry_axis,
                0,
            )
            raw_normal = (
                float(matrix[start]),
                float(matrix[start + 1]),
                float(matrix[start + 2]),
            )
            magnitude = math.sqrt(sum(value * value for value in raw_normal))
            normal = (
                tuple(value / magnitude for value in raw_normal)
                if magnitude > 1.0e-12
                else fallback
            )
            return normalized.with_symmetry_frame(origin, normal)  # type: ignore[arg-type]
        except Exception:
            return normalized.with_symmetry_frame((0.0, 0.0, 0.0), fallback)

    def _curve_transform(self, node: str) -> str:
        if not node or not self.cmds.objExists(node):
            raise ValueError("NURBS curve does not exist")
        if self.cmds.nodeType(node) == "nurbsCurve":
            parents = self.cmds.listRelatives(node, parent=True, fullPath=True) or []
            if not parents:
                raise ValueError("NURBS curve has no transform")
            return str(parents[0])
        if self.cmds.nodeType(node) == "transform":
            curves = self.cmds.listRelatives(
                node,
                shapes=True,
                noIntermediate=True,
                fullPath=True,
                type="nurbsCurve",
            ) or []
            if curves:
                return str(node)
        raise ValueError("Node is not a NURBS curve")

    def _selected_curve_transform(self) -> str:
        selection = self.cmds.ls(selection=True, long=True) or []
        for node in selection:
            try:
                return self._curve_transform(str(node))
            except ValueError:
                continue
        raise ValueError("NURBS curveを1つ選択してください")

    def _guide_points(self, node: str, kind: GuideKind) -> tuple[tuple[float, float, float], ...]:
        if not kind.is_curve:
            try:
                value = self.cmds.xform(node, query=True, worldSpace=True, translation=True)
                return ((float(value[0]), float(value[1]), float(value[2])),)
            except Exception:
                return ((0.0, 0.0, 0.0),)
        shapes = self.cmds.listRelatives(
            node,
            shapes=True,
            noIntermediate=True,
            fullPath=True,
            type="nurbsCurve",
        ) or []
        if not shapes:
            return ((0.0, 0.0, 0.0),)
        components = self.cmds.ls(str(shapes[0]) + ".cv[*]", flatten=True) or []
        points = []
        for component in components:
            value = self.cmds.pointPosition(component, world=True)
            points.append((float(value[0]), float(value[1]), float(value[2])))
        return tuple(points) or ((0.0, 0.0, 0.0),)

    def _guide_direction(self, node: str) -> tuple[float, float, float]:
        try:
            matrix = self.cmds.xform(node, query=True, worldSpace=True, matrix=True)
            return (float(matrix[0]), float(matrix[1]), float(matrix[2]))
        except Exception:
            return (1.0, 0.0, 0.0)

    def _active_slot(self, preview_transform: str) -> str:
        try:
            if self.cmds.attributeQuery(ACTIVE_SLOT, node=preview_transform, exists=True):
                value = str(self.cmds.getAttr(preview_transform + "." + ACTIVE_SLOT) or "")
                if value in {"interactive", "settled"}:
                    return value
        except Exception:
            pass
        return "settled"

    def _ensure_root(self) -> str:
        if self.cmds.objExists(ROOT_NAME):
            owned = bool(
                self.cmds.attributeQuery(ROOT_MARKER, node=ROOT_NAME, exists=True)
                and self.cmds.getAttr(ROOT_NAME + "." + ROOT_MARKER)
            )
            root = ROOT_NAME if owned else self.cmds.createNode(
                "transform", name=ROOT_NAME + "#"
            )
        else:
            root = self.cmds.createNode("transform", name=ROOT_NAME)
        self._ensure_bool(root, ROOT_MARKER, True)
        return str(root)

    def _resolve_mesh(self, node: str) -> str:
        if not self.cmds.objExists(node):
            raise ValueError("Target mesh does not exist: {}".format(node))
        if self.cmds.nodeType(node) == "mesh":
            return str(node)
        if self.cmds.nodeType(node) == "transform":
            shapes = self.cmds.listRelatives(
                node,
                shapes=True,
                noIntermediate=True,
                fullPath=True,
                type="mesh",
            ) or []
            if shapes:
                return str(shapes[0])
        raise ValueError("Target is not a polygon mesh: {}".format(node))

    def _ensure_bool(self, node: str, name: str, value: bool) -> None:
        if not self.cmds.attributeQuery(name, node=node, exists=True):
            self.cmds.addAttr(node, longName=name, attributeType="bool")
        desired = bool(value)
        try:
            if bool(self.cmds.getAttr(node + "." + name)) == desired:
                return
        except Exception:
            pass
        self.cmds.setAttr(node + "." + name, desired)

    def _ensure_int(self, node: str, name: str, value: int) -> None:
        if not self.cmds.attributeQuery(name, node=node, exists=True):
            self.cmds.addAttr(node, longName=name, attributeType="long")
        desired = int(value)
        try:
            if int(self.cmds.getAttr(node + "." + name)) == desired:
                return
        except Exception:
            pass
        self.cmds.setAttr(node + "." + name, desired)

    def _ensure_double(self, node: str, name: str, value: float) -> None:
        if not self.cmds.attributeQuery(name, node=node, exists=True):
            self.cmds.addAttr(node, longName=name, attributeType="double")
        desired = float(value)
        try:
            if abs(float(self.cmds.getAttr(node + "." + name)) - desired) <= 1.0e-12:
                return
        except Exception:
            pass
        self.cmds.setAttr(node + "." + name, desired)

    def _ensure_string(self, node: str, name: str, value: str) -> None:
        if not self.cmds.attributeQuery(name, node=node, exists=True):
            self.cmds.addAttr(node, longName=name, dataType="string")
        desired = str(value)
        try:
            if str(self.cmds.getAttr(node + "." + name) or "") == desired:
                return
        except Exception:
            pass
        self.cmds.setAttr(node + "." + name, desired, type="string")

    def _ensure_message(self, node: str, name: str) -> None:
        if not self.cmds.attributeQuery(name, node=node, exists=True):
            self.cmds.addAttr(node, longName=name, attributeType="message")

    def begin_undo_chunk(self, name: str = "Bifrost Scales") -> None:
        """Open one nestable Maya undo chunk for a user-authored operation."""

        if self._undo_chunk_depth == 0:
            try:
                self.cmds.undoInfo(openChunk=True, chunkName=str(name))
            except TypeError:
                try:
                    self.cmds.undoInfo(openChunk=True)
                except Exception:
                    pass
            except Exception:
                pass
        self._undo_chunk_depth += 1

    def end_undo_chunk(self) -> None:
        if self._undo_chunk_depth <= 0:
            self._undo_chunk_depth = 0
            return
        self._undo_chunk_depth -= 1
        if self._undo_chunk_depth == 0:
            try:
                self.cmds.undoInfo(closeChunk=True)
            except Exception:
                pass

    @contextmanager
    def user_undo_chunk(self, name: str = "Bifrost Scales"):
        self.begin_undo_chunk(name)
        try:
            yield
        finally:
            self.end_undo_chunk()

    @contextmanager
    def _automatic_update_guard(self):
        """Keep automatic JSON/stat persistence out of Maya's undo queue."""

        if self._undo_chunk_depth > 0:
            yield
            return

        undo_enabled = False
        try:
            undo_enabled = bool(self.cmds.undoInfo(query=True, state=True))
        except Exception:
            undo_enabled = False
        if undo_enabled:
            try:
                self.cmds.undoInfo(stateWithoutFlush=False)
            except Exception:
                undo_enabled = False
        try:
            yield
        finally:
            if undo_enabled:
                try:
                    self.cmds.undoInfo(stateWithoutFlush=True)
                except Exception:
                    pass
