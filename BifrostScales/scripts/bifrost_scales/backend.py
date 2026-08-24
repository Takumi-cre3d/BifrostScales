"""Native-only Maya authoring backend for Bifrost Scales.

The Python reference generator was removed in 0.10.0.  Maya Python now owns
scene authoring, guide management, scheduling, and the immutable Bifrost host
boundary only.  All preview geometry is produced by the native Bifrost graph.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Any, Mapping

from .cell_identity import CellMetadata
from .guides import GuideKind, GuideSet
from .native_backend import NativeGraphController
from .scene import MayaSceneManager, SystemBinding
from .scheduler import ChangeCategory, PreviewMode, PreviewRequest
from .settings import ScaleSettings, UniqueScaleOverride, UniqueScaleRegistration
from .stable_ids import cell_id_hex, parse_cell_id

@dataclass(frozen=True)
class BackendApplyReport:
    revision: int
    mode: str
    binding: SystemBinding
    scale_count: int
    vertex_count: int
    face_count: int
    cache_hit: bool
    target_cache_hit: bool
    generated: bool
    sampling_attempts: int
    mesh_update: str
    effective_budget: int
    next_interactive_budget: int
    generation_ms: float
    viewport_ms: float
    total_ms: float
    orientation_cache_hit: bool = False
    cell_cache_hit: bool = False
    geometry_kind: str = "card"
    cell_count: int = 0
    cell_resolution: int = 0
    cell_clipped_rays: int = 0
    cell_mean_neighbors: float = 0.0
    paired_sample_count: int = 0
    partition_seed_count: int = 0
    cell_shape_divisions: int = 0
    density_guide_count: int = 0
    direction_guide_count: int = 0
    density_relax_iterations: int = 0
    direction_relax_iterations: int = 0
    type_counts: tuple[tuple[str, int], ...] = ()
    native_execution_wait_ms: float = 0.0
    native_execution_counter_before: int = -1
    native_execution_counter_after: int = -1
    native_evaluation_policy: str = ""
    native_profile_available: bool = False
    native_payload_decode_ms: float = 0.0
    native_source_decode_ms: float = 0.0
    native_distribution_ms: float = 0.0
    native_orientation_ms: float = 0.0
    native_cells_ms: float = 0.0
    native_shape_ms: float = 0.0
    native_core_total_ms: float = 0.0
    native_encode_ms: float = 0.0
    native_operator_total_ms: float = 0.0
    native_graph_publish_ms: float = 0.0
    native_compute_backend: str = ""
    native_gpu_compute: bool = False
    native_gpu_compute_requested: bool = False
    native_gpu_compute_available: bool = False
    native_gpu_stage: str = ""
    native_gpu_device: str = ""
    native_gpu_fallback_reason: str = ""
    native_gpu_upload_ms: float = 0.0
    native_gpu_kernel_ms: float = 0.0
    native_gpu_readback_ms: float = 0.0
    native_gpu_sample_count: int = 0
    native_boundary_anchor_count: int = 0
    native_boundary_density_adapted: bool = False
    native_distribution_worker_threads: int = 0
    native_orientation_worker_threads: int = 0
    native_cell_worker_threads: int = 0
    native_shape_worker_threads: int = 0
    native_cell_cache_basis: str = ""
    native_cell_cache_reused_after_orientation_change: bool = False
    native_stage_cache_scope: str = ""
    native_stage_cache_capacity: int = 0
    native_stage_cache_evictions: int = 0


class NativeMayaBackend:
    """Own Maya authoring state and evaluate only the native Bifrost graph."""

    PREVIEW_BACKENDS = ("native",)

    def __init__(
        self,
        cmds_module: Any | None = None,
        om_module: Any | None = None,
    ) -> None:
        del om_module  # Kept as a compatibility argument for host scripts.
        self.scene = MayaSceneManager(cmds_module=cmds_module)
        self.native = NativeGraphController(cmds_module=self.scene.cmds)
        self._binding: SystemBinding | None = None
        self._guide_cache: GuideSet | None = None
        self._guide_management_cache: tuple[object, ...] | None = None

    @property
    def binding(self) -> SystemBinding | None:
        return self._binding

    def list_systems(self) -> list[str]:
        return self.scene.list_systems()

    def list_guides(self) -> list[str]:
        return self.scene.list_guides(self._require_binding().settings_node)

    def list_guide_groups(self) -> list[str]:
        return self.scene.list_guide_groups(self._require_binding().settings_node)

    def read_guide(self, node: str):
        return self.scene.read_guide(node)

    def read_guide_group(self, node: str):
        return self.scene.read_guide_group(node)

    def selected_guide_item(self) -> str:
        return self.scene.selected_guide_item(
            self._require_binding().settings_node
        )

    def read_guides(self, force: bool = False) -> GuideSet:
        binding = self._require_binding()
        if force or self._guide_cache is None:
            self._guide_cache = self.scene.read_guides(binding.settings_node)
            self._guide_management_cache = self.scene.guide_management_fingerprint(
                binding.settings_node
            )
        return self._guide_cache

    def refresh_guide_cache(self) -> GuideSet:
        self._guide_cache = None
        self._guide_management_cache = None
        return self.read_guides(force=True)

    @staticmethod
    def _guide_change_category(
        previous: GuideSet,
        current: GuideSet,
    ) -> ChangeCategory:
        if previous.fingerprint("distribution") != current.fingerprint(
            "distribution"
        ):
            return ChangeCategory.DISTRIBUTION
        if previous.fingerprint("direction") != current.fingerprint("direction"):
            return ChangeCategory.ORIENTATION
        if previous.fingerprint("links") != current.fingerprint("links"):
            return ChangeCategory.SHAPE
        return ChangeCategory.DISPLAY

    def poll_guide_changes(self) -> ChangeCategory | None:
        return self.poll_guide_state()[0]

    def poll_guide_state(self) -> tuple[ChangeCategory | None, bool]:
        """Return generation invalidation and presentation-change state."""

        binding = self._require_binding()
        previous = self._guide_cache or GuideSet()
        previous_management = self._guide_management_cache
        current = self.scene.read_guides(binding.settings_node)
        current_management = self.scene.guide_management_fingerprint(
            binding.settings_node
        )
        self._guide_cache = current
        self._guide_management_cache = current_management
        presentation_changed = (
            previous.fingerprint() != current.fingerprint()
            or previous_management != current_management
        )
        category = self._guide_change_category(previous, current)
        return (
            None if category is ChangeCategory.DISPLAY else category,
            presentation_changed,
        )

    def create_point_guide(self, kind: GuideKind | str) -> str:
        node = self.scene.create_point_guide(self._require_binding().settings_node, kind)
        self.refresh_guide_cache()
        return node

    def create_curve_guide_from_points(
        self,
        kind: GuideKind | str,
        points: list[tuple[float, float, float]] | tuple[tuple[float, float, float], ...],
    ) -> str:
        node = self.scene.create_curve_guide_from_points(
            self._require_binding().settings_node,
            kind,
            points,
        )
        self.refresh_guide_cache()
        return node

    def adopt_curve_guide(
        self,
        kind: GuideKind | str,
        curve_transform: str,
    ) -> str:
        node = self.scene.adopt_curve_guide(
            self._require_binding().settings_node,
            kind,
            curve_transform,
        )
        self.refresh_guide_cache()
        return node

    def create_curve_guide_from_selection(self, kind: GuideKind | str) -> str:
        node = self.scene.create_curve_guide_from_selection(
            self._require_binding().settings_node,
            kind,
        )
        self.refresh_guide_cache()
        return node

    def create_guide_group(self, name: str = "") -> str:
        node = self.scene.create_guide_group(
            self._require_binding().settings_node,
            name=name,
        )
        self.refresh_guide_cache()
        return node

    def update_guide(self, node: str, **values: object) -> ChangeCategory:
        previous = self.read_guides(force=True)
        self.scene.update_guide(node, **values)
        current = self.refresh_guide_cache()
        return self._guide_change_category(previous, current)

    def rename_guide(self, node: str, display_name: str) -> str:
        result = self.scene.rename_guide(node, display_name)
        self.refresh_guide_cache()
        return result

    def update_guide_group(self, node: str, **values: object) -> ChangeCategory:
        previous = self.read_guides(force=True)
        self.scene.update_guide_group(node, **values)
        current = self.refresh_guide_cache()
        return self._guide_change_category(previous, current)

    def move_guide_to_group(self, node: str, group_node: str = "") -> ChangeCategory:
        previous = self.read_guides(force=True)
        self.scene.move_guide_to_group(
            self._require_binding().settings_node,
            node,
            group_node,
        )
        current = self.refresh_guide_cache()
        return self._guide_change_category(previous, current)

    def apply_guide_tree_layout(
        self,
        ordered_groups: list[str],
        guides_by_group: dict[str, list[str]],
    ) -> ChangeCategory:
        previous = self.read_guides(force=True)
        self.scene.apply_guide_tree_layout(
            self._require_binding().settings_node,
            ordered_groups,
            guides_by_group,
        )
        current = self.refresh_guide_cache()
        return self._guide_change_category(previous, current)

    def reorder_guides(self, ordered_nodes: list[str]) -> ChangeCategory:
        previous = self.read_guides(force=True)
        self.scene.reorder_guides(
            self._require_binding().settings_node,
            ordered_nodes,
        )
        current = self.refresh_guide_cache()
        return self._guide_change_category(previous, current)

    def reorder_guide(self, node: str, delta: int) -> int:
        result = self.scene.reorder_guide(
            self._require_binding().settings_node,
            node,
            delta,
        )
        self.refresh_guide_cache()
        return result

    def reorder_guide_group(self, node: str, delta: int) -> int:
        result = self.scene.reorder_guide_group(
            self._require_binding().settings_node,
            node,
            delta,
        )
        self.refresh_guide_cache()
        return result

    def delete_guide(self, node: str) -> ChangeCategory:
        previous = self.read_guides(force=True)
        self.scene.delete_guide(node)
        current = self.refresh_guide_cache()
        return self._guide_change_category(previous, current)

    def delete_guide_group(self, node: str) -> ChangeCategory:
        previous = self.read_guides(force=True)
        self.scene.delete_guide_group(
            self._require_binding().settings_node,
            node,
        )
        current = self.refresh_guide_cache()
        return self._guide_change_category(previous, current)

    def select_guide(self, node: str) -> None:
        self.scene.select_guide(node)

    def select_guide_item(self, node: str) -> None:
        self.scene.select_guide_item(node)

    def selected_guides(
        self,
        guide_nodes: list[str] | tuple[str, ...] | None = None,
    ) -> list[str]:
        return self.scene.selected_guides(
            self._require_binding().settings_node,
            guide_nodes=guide_nodes,
        )

    def begin_undo_chunk(self, name: str = "Bifrost Scales") -> None:
        self.scene.begin_undo_chunk(name)

    def end_undo_chunk(self) -> None:
        self.scene.end_undo_chunk()

    @property
    def preview_backend(self) -> str:
        return "native"

    @property
    def final_output_available(self) -> bool:
        """Native final/Bake is intentionally not exposed yet."""

        return False

    def selected_mesh(self) -> str:
        return self.scene.selected_mesh()

    def native_status(self):
        return self.native.probe()

    def native_graph(self) -> str:
        return self.native.graph_for_system(self._require_binding())

    def set_preview_backend(self, mode: str) -> str:
        normalized = str(mode).strip().lower()
        if normalized != "native":
            raise ValueError(
                "Python Reference preview was removed in Bifrost Scales 0.10.0; "
                "only Native Bifrost is supported."
            )
        binding = self._binding
        if binding is not None:
            self.native.set_active(
                binding,
                active=True,
                visible=self.read_settings().visible,
            )
        return "native"

    def _require_native_ready(self) -> None:
        status = self.native.probe()
        if not status.ready:
            raise RuntimeError(
                "Native Bifrost backend is not ready: {}".format(
                    "; ".join(status.reasons)
                )
            )

    def create_system(
        self,
        target_mesh: str,
        settings: ScaleSettings | None = None,
    ) -> SystemBinding:
        """Create the System and immutable Native Graph as one transaction."""

        self._require_native_ready()
        normalized = settings or ScaleSettings()
        binding: SystemBinding | None = None
        try:
            binding = self.scene.create_system(target_mesh, settings=normalized)
            self._binding = binding
            self._reset_authoring_caches()
            self.native.create_graph(binding)
            self.native.set_active(binding, active=True, visible=normalized.visible)
            return binding
        except Exception:
            if binding is not None:
                try:
                    self.native.delete_graph(binding)
                except Exception:
                    pass
                try:
                    self.scene.delete_system(binding.settings_node)
                except Exception:
                    pass
            self._binding = None
            self._reset_authoring_caches()
            raise

    def create_system_with_preview(
        self,
        target_mesh: str,
        settings: ScaleSettings | None = None,
        *,
        mode: str = "settled",
    ) -> tuple[SystemBinding, BackendApplyReport]:
        """Create System + Graph and finish the first Bifrost evaluation."""

        normalized = settings or ScaleSettings()
        binding = self.create_system(target_mesh, normalized)
        try:
            report = self.apply(
                self._request_for_settings(normalized, mode=mode, revision=1)
            )
            return binding, report
        except Exception:
            try:
                self.delete_system()
            except Exception:
                pass
            raise

    def bind(self, settings_node: str) -> SystemBinding:
        changed = self._binding is None or self._binding.settings_node != settings_node
        self._binding = self.scene.bind(settings_node)
        if changed:
            self._reset_authoring_caches()
        self.native.set_active(
            self._binding,
            active=True,
            visible=self.read_settings().visible,
        )
        return self._binding

    def set_target(self, target_mesh: str) -> SystemBinding:
        """Replace the target and rebuild the explicit worldMesh binding."""

        binding, _report = self.set_target_with_preview(target_mesh)
        return binding

    def set_target_with_preview(
        self,
        target_mesh: str,
        *,
        settings: ScaleSettings | None = None,
    ) -> tuple[SystemBinding, BackendApplyReport]:
        self._require_native_ready()
        current = self._require_binding()
        old_target = current.target_mesh
        normalized = settings or self.read_settings()
        self.native.delete_graph(current)
        try:
            binding = self.scene.set_target(current.settings_node, target_mesh)
            self._binding = binding
            self._reset_authoring_caches()
            self.native.create_graph(binding)
            self.native.set_active(binding, active=True, visible=normalized.visible)
            report = self.apply(
                self._request_for_settings(normalized, mode="settled", revision=1)
            )
            return binding, report
        except Exception:
            # Best-effort rollback to the previously valid target contract.
            try:
                failed = self.scene.bind(current.settings_node)
                self.native.delete_graph(failed)
            except Exception:
                pass
            try:
                restored = self.scene.set_target(current.settings_node, old_target)
                self._binding = restored
                self.native.create_graph(restored)
                self.native.set_active(
                    restored,
                    active=True,
                    visible=normalized.visible,
                )
            except Exception:
                self._binding = None
            self._reset_authoring_caches()
            raise

    def create_native_graph(self) -> str:
        binding = self._require_binding()
        graph = self.native.create_graph(binding)
        self.native.set_active(
            binding,
            active=True,
            visible=self.read_settings().visible,
        )
        return graph

    def rebuild_native_graph(self) -> str:
        binding = self._require_binding()
        self.native.delete_graph(binding)
        return self.create_native_graph()

    def delete_native_graph(self) -> bool:
        binding = self._require_binding()
        deleted = self.native.delete_graph(binding)
        # There is no Python preview to reveal after graph deletion.
        if binding.preview_transform and self.scene.cmds.objExists(binding.preview_transform):
            try:
                self.scene.cmds.setAttr(binding.preview_transform + ".visibility", False)
            except Exception:
                pass
        return deleted

    def refresh_target_cache(self) -> None:
        """Force one fresh native execution without reconnecting the target."""

        self.native.invalidate(self._require_binding())

    def read_settings(self) -> ScaleSettings:
        return self.scene.read_settings(self._require_binding().settings_node)

    def persist_settings(
        self,
        settings: ScaleSettings | Mapping[str, object],
    ) -> ScaleSettings:
        source = settings.to_mapping() if isinstance(settings, ScaleSettings) else settings
        normalized = ScaleSettings.from_mapping(source)
        self.scene.write_settings(self._require_binding().settings_node, normalized)
        return normalized

    @staticmethod
    def _request_for_settings(
        settings: ScaleSettings,
        *,
        mode: str,
        revision: int,
    ) -> PreviewRequest:
        normalized_mode = str(mode).strip().lower()
        preview_mode = (
            PreviewMode.INTERACTIVE
            if normalized_mode == "interactive"
            else PreviewMode.SETTLED
        )
        return PreviewRequest(
            revision=int(revision),
            mode=preview_mode,
            categories=frozenset({ChangeCategory.DISTRIBUTION}),
            scope=ChangeCategory.DISTRIBUTION,
            snapshot=settings.to_mapping(),
            created_at=time.monotonic(),
        )

    @staticmethod
    def _native_cell_metadata(profile: Mapping[str, object]) -> tuple[CellMetadata, ...]:
        raw_items = profile.get("selected_cells", ())
        if not isinstance(raw_items, (list, tuple)):
            return ()
        result: list[CellMetadata] = []
        for raw in raw_items:
            if not isinstance(raw, Mapping):
                continue
            try:
                result.append(
                    CellMetadata(
                        cell_id=parse_cell_id(raw.get("cell_id", "")),
                        scale_index=max(0, int(raw.get("index", 0))),
                        position=tuple(float(value) for value in raw.get("position", (0, 0, 0))),
                        normal=tuple(float(value) for value in raw.get("normal", (0, 1, 0))),
                        triangle_index=max(0, int(raw.get("triangle_index", 0))),
                        barycentric=tuple(
                            float(value) for value in raw.get("barycentric", (1, 0, 0))
                        ),
                        boundary_signature=int(
                            str(raw.get("boundary_signature", "0") or "0"),
                            16,
                        ) & ((1 << 64) - 1),
                    )
                )
            except (TypeError, ValueError):
                continue
        return tuple(sorted(result, key=lambda item: item.scale_index))

    def cell_metadata_for_indices(
        self,
        indices: tuple[int, ...],
        *,
        settings: ScaleSettings | None = None,
        mode: str = "settled",
    ) -> tuple[CellMetadata, ...]:
        normalized_indices = tuple(sorted({max(0, int(value)) for value in indices}))
        if not normalized_indices:
            return ()
        normalized = settings or self.read_settings()
        evaluation = self.native.evaluate(
            self._require_binding(),
            normalized,
            self.read_guides(force=True),
            mode=mode,
            cell_metadata_indices=normalized_indices,
        )
        metadata = self._native_cell_metadata(evaluation.profile)
        by_index = {item.scale_index: item for item in metadata}
        result = tuple(by_index[index] for index in normalized_indices if index in by_index)
        if len(result) != len(normalized_indices):
            missing = sorted(set(normalized_indices) - set(by_index))
            raise ValueError(
                "選択セルを現在のNativeウロコへ解決できませんでした: {}".format(missing)
            )
        return result

    @staticmethod
    def _picker_scale_indices() -> tuple[int, ...]:
        from .cell_picker_maya import current_selection_records

        records = current_selection_records()
        if not records:
            raise ValueError(
                "Unique Scalesの『Select Cells』モードでセルを1つ以上選択してください"
            )
        return tuple(sorted({max(0, int(record.scale_index)) for record in records}))

    def _target_identity(self) -> str:
        binding = self._require_binding()
        try:
            values = self.scene.cmds.ls(binding.target_mesh, uuid=True) or []
            if values:
                return "maya-uuid:" + str(values[0])
        except Exception:
            pass
        return "maya-node:" + str(binding.target_mesh)

    def register_selected_unique_scales(
        self,
        mode: str = "settled",
    ) -> tuple[ScaleSettings, tuple[UniqueScaleRegistration, ...]]:
        settings = self.read_settings()
        indices = self._picker_scale_indices()
        metadata = self.cell_metadata_for_indices(indices, settings=settings, mode=mode)
        topology_identity = self._target_identity()
        existing_ids = {item.cell_id for item in settings.unique_scales}
        existing_names = {item.name for item in settings.unique_scales}
        additions: list[UniqueScaleRegistration] = []
        next_number = len(settings.unique_scales) + 1
        for item in metadata:
            normalized_id = item.cell_id_hex
            if normalized_id in existing_ids:
                continue
            name = "Unique Scale {}".format(next_number)
            while name in existing_names:
                next_number += 1
                name = "Unique Scale {}".format(next_number)
            additions.append(
                UniqueScaleRegistration(
                    cell_id=normalized_id,
                    name=name,
                    position=tuple(float(value) for value in item.position),
                    normal=tuple(float(value) for value in item.normal),
                    triangle_index=int(item.triangle_index),
                    barycentric=tuple(float(value) for value in item.barycentric),
                    boundary_signature=cell_id_hex(item.boundary_signature),
                    topology_hash=topology_identity,
                    seed=int(settings.seed),
                )
            )
            existing_ids.add(normalized_id)
            existing_names.add(name)
            next_number += 1
        if not additions:
            return settings, ()
        updated = replace(settings, unique_scales=settings.unique_scales + tuple(additions))
        with self.scene.user_undo_chunk("Bifrost Scales Register Unique Scales"):
            self.scene.write_settings(self._require_binding().settings_node, updated)
        return updated, tuple(additions)

    def unregister_unique_scales(
        self,
        cell_ids: tuple[str, ...] | list[str],
    ) -> ScaleSettings:
        normalized_ids: set[str] = set()
        for value in cell_ids:
            try:
                normalized_ids.add(cell_id_hex(parse_cell_id(value)))
            except ValueError:
                continue
        settings = self.read_settings()
        retained = tuple(
            item for item in settings.unique_scales if item.cell_id not in normalized_ids
        )
        if retained == settings.unique_scales:
            return settings
        updated = replace(settings, unique_scales=retained)
        with self.scene.user_undo_chunk("Bifrost Scales Unregister Unique Scales"):
            self.scene.write_settings(self._require_binding().settings_node, updated)
        return updated

    def set_unique_scale_overrides(
        self,
        cell_ids: tuple[str, ...] | list[str],
        override: UniqueScaleOverride | Mapping[str, Any],
    ) -> ScaleSettings:
        normalized_ids: set[str] = set()
        for value in cell_ids:
            try:
                normalized_ids.add(cell_id_hex(parse_cell_id(value)))
            except ValueError:
                continue
        if not normalized_ids:
            raise ValueError("Unique Scaleを1つ以上選択してください")
        canonical = (
            override
            if isinstance(override, UniqueScaleOverride)
            else UniqueScaleOverride.from_mapping(override)
        )
        settings = self.read_settings()
        found = False
        updated_items: list[UniqueScaleRegistration] = []
        for item in settings.unique_scales:
            if item.cell_id in normalized_ids:
                found = True
                updated_items.append(replace(item, override=canonical))
            else:
                updated_items.append(item)
        if not found:
            raise ValueError("選択したStable Cell IDは登録済みUnique Scaleにありません")
        updated = replace(settings, unique_scales=tuple(updated_items))
        with self.scene.user_undo_chunk("Bifrost Scales Edit Unique Overrides"):
            self.scene.write_settings(self._require_binding().settings_node, updated)
        return updated

    def reset_unique_scale_overrides(
        self,
        cell_ids: tuple[str, ...] | list[str],
    ) -> ScaleSettings:
        return self.set_unique_scale_overrides(cell_ids, UniqueScaleOverride())

    def unique_scale_status(self, mode: str = "settled") -> dict[str, str]:
        settings = self.read_settings()
        ids = tuple(item.cell_id for item in settings.unique_scales)
        if not ids:
            return {}
        evaluation = self.native.evaluate(
            self._require_binding(),
            settings,
            self.read_guides(force=True),
            mode=mode,
            resolve_cell_ids=ids,
        )
        resolved = {
            str(value).lower()
            for value in evaluation.profile.get("resolved_cell_ids", ())
        }
        orphaned = {
            str(value).lower()
            for value in evaluation.profile.get("orphaned_cell_ids", ())
        }
        return {
            cell_id: (
                "resolved"
                if cell_id in resolved
                else "orphaned"
                if cell_id in orphaned
                else "unchecked"
            )
            for cell_id in ids
        }

    def rebind_unique_scale(
        self,
        old_cell_id: str,
        mode: str = "settled",
    ) -> UniqueScaleRegistration:
        normalized_old = cell_id_hex(parse_cell_id(old_cell_id))
        settings = self.read_settings()
        matches = [item for item in settings.unique_scales if item.cell_id == normalized_old]
        if len(matches) != 1:
            raise ValueError("再バインド対象のUnique Scaleが見つかりません")
        indices = self._picker_scale_indices()
        if len(indices) != 1:
            raise ValueError("再バインド先のセルを1つだけ選択してください")
        metadata = self.cell_metadata_for_indices(
            indices,
            settings=settings,
            mode=mode,
        )[0]
        new_id = metadata.cell_id_hex
        if any(
            item.cell_id == new_id and item.cell_id != normalized_old
            for item in settings.unique_scales
        ):
            raise ValueError("選択したセルはすでにUnique Scaleとして登録されています")
        rebound = replace(
            matches[0],
            cell_id=new_id,
            position=tuple(float(value) for value in metadata.position),
            normal=tuple(float(value) for value in metadata.normal),
            triangle_index=int(metadata.triangle_index),
            barycentric=tuple(float(value) for value in metadata.barycentric),
            boundary_signature=cell_id_hex(metadata.boundary_signature),
            topology_hash=self._target_identity(),
            seed=int(settings.seed),
        )
        updated_items = tuple(
            rebound if item.cell_id == normalized_old else item
            for item in settings.unique_scales
        )
        updated = replace(settings, unique_scales=updated_items)
        with self.scene.user_undo_chunk("Bifrost Scales Rebind Unique Scale"):
            self.scene.write_settings(self._require_binding().settings_node, updated)
        return rebound

    def delete_system(self) -> None:
        binding = self._require_binding()
        try:
            self.native.delete_graph(binding)
        finally:
            self.scene.delete_system(binding.settings_node)
            self._binding = None
            self._reset_authoring_caches()

    def apply(self, request: PreviewRequest) -> BackendApplyReport:
        binding = self._require_binding()
        settings = ScaleSettings.from_mapping(request.snapshot)
        self.scene.write_settings(binding.settings_node, settings)
        guides = self.read_guides(force=True)
        display_only = request.scope is ChangeCategory.DISPLAY
        evaluation = self.native.evaluate(
            binding,
            settings,
            guides,
            mode=request.mode.value,
            display_only=display_only,
        )
        self.scene.set_stats(
            binding.preview_transform,
            evaluation.scale_count,
            evaluation.point_count,
            evaluation.face_count,
        )
        density_count = sum(
            1 for guide in guides.evaluated_guides
            if guide.enabled and guide.affects_density
        )
        direction_count = sum(
            1 for guide in guides.evaluated_guides
            if guide.enabled and guide.affects_direction
        )
        effective_budget = settings.effective_count(request.mode.value)
        profile = evaluation.profile

        def profile_ms(name: str) -> float:
            try:
                return max(0.0, float(profile.get(name, 0.0)))
            except (TypeError, ValueError):
                return 0.0

        operator_total_ms = profile_ms("operator_total_ms")
        return BackendApplyReport(
            revision=request.revision,
            mode=request.mode.value,
            binding=binding,
            scale_count=evaluation.scale_count,
            vertex_count=evaluation.point_count,
            face_count=evaluation.face_count,
            cache_hit=bool(profile.get("distribution_cache_hit", False)),
            target_cache_hit=True,
            generated=evaluation.payload_changed,
            sampling_attempts=0,
            mesh_update=(
                "native-display"
                if display_only
                else "native-payload"
                if evaluation.payload_changed
                else "native-cache"
            ),
            effective_budget=effective_budget,
            next_interactive_budget=effective_budget,
            generation_ms=evaluation.generation_ms,
            viewport_ms=evaluation.viewport_ms,
            total_ms=evaluation.total_ms,
            orientation_cache_hit=bool(
                profile.get("orientation_cache_hit", False)
            ),
            cell_cache_hit=bool(profile.get("cell_cache_hit", False)),
            geometry_kind=settings.geometry_kind(request.mode.value),
            cell_count=(
                evaluation.scale_count
                if settings.geometry_kind(request.mode.value) == "cell"
                else 0
            ),
            cell_resolution=settings.effective_cell_resolution(request.mode.value),
            cell_shape_divisions=settings.cell_shape_divisions,
            density_guide_count=density_count,
            direction_guide_count=direction_count,
            density_relax_iterations=settings.effective_relax_iterations(request.mode.value),
            direction_relax_iterations=settings.effective_direction_relax_iterations(
                request.mode.value
            ),
            native_execution_wait_ms=evaluation.execution_wait_ms,
            native_execution_counter_before=evaluation.execution_counter_before,
            native_execution_counter_after=evaluation.execution_counter_after,
            native_evaluation_policy=evaluation.evaluation_policy,
            native_profile_available=bool(profile),
            native_payload_decode_ms=profile_ms("payload_decode_ms"),
            native_source_decode_ms=profile_ms("source_decode_ms"),
            native_distribution_ms=profile_ms("distribution_ms"),
            native_orientation_ms=profile_ms("orientation_ms"),
            native_cells_ms=profile_ms("cells_ms"),
            native_shape_ms=profile_ms("shape_ms"),
            native_core_total_ms=profile_ms("core_total_ms"),
            native_encode_ms=profile_ms("encode_ms"),
            native_operator_total_ms=operator_total_ms,
            native_graph_publish_ms=max(
                0.0, evaluation.generation_ms - operator_total_ms
            ),
            native_compute_backend=str(profile.get("compute_backend", "")),
            native_gpu_compute=bool(profile.get("gpu_compute", False)),
            native_gpu_compute_requested=bool(
                profile.get("gpu_compute_requested", False)
            ),
            native_gpu_compute_available=bool(
                profile.get("gpu_compute_available", False)
            ),
            native_gpu_stage=str(profile.get("gpu_stage", "")),
            native_gpu_device=str(profile.get("gpu_device", "")),
            native_gpu_fallback_reason=str(
                profile.get("gpu_fallback_reason", "")
            ),
            native_gpu_upload_ms=profile_ms("gpu_upload_ms"),
            native_gpu_kernel_ms=profile_ms("gpu_kernel_ms"),
            native_gpu_readback_ms=profile_ms("gpu_readback_ms"),
            native_gpu_sample_count=int(profile.get("gpu_sample_count", 0) or 0),
            native_boundary_anchor_count=int(
                profile.get("boundary_anchor_count", 0) or 0
            ),
            native_boundary_density_adapted=bool(
                profile.get("boundary_density_adapted", False)
            ),
            native_distribution_worker_threads=int(
                profile.get("distribution_worker_threads", 0) or 0
            ),
            native_orientation_worker_threads=int(
                profile.get("orientation_worker_threads", 0) or 0
            ),
            native_cell_worker_threads=int(
                profile.get("cell_worker_threads", 0) or 0
            ),
            native_shape_worker_threads=int(
                profile.get("shape_worker_threads", 0) or 0
            ),
            native_cell_cache_basis=str(profile.get("cell_cache_basis", "")),
            native_cell_cache_reused_after_orientation_change=bool(
                profile.get(
                    "cell_cache_reused_after_orientation_change",
                    False,
                )
            ),
            native_stage_cache_scope=str(profile.get("stage_cache_scope", "")),
            native_stage_cache_capacity=int(
                profile.get("stage_cache_capacity", 0) or 0
            ),
            native_stage_cache_evictions=int(
                profile.get("stage_cache_evictions", 0) or 0
            ),
        )

    def _reset_authoring_caches(self) -> None:
        self._guide_cache = None
        self._guide_management_cache = None

    def _require_binding(self) -> SystemBinding:
        if self._binding is None:
            raise ValueError("Bifrost Scales system is not selected")
        self._binding = self.scene.bind(self._binding.settings_node)
        return self._binding
