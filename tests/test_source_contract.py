import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "BifrostScales/scripts/bifrost_scales"
REMOVED_REFERENCE_MODULES = {
    "adaptive",
    "cells",
    "generator",
    "maya_mesh",
    "maya_smoke",
    "mesh",
    "orientation",
    "relaxation",
    "sampling",
    "surface_features",
}


def test_product_runtime_has_no_python_reference_generator_modules_or_imports():
    for module in REMOVED_REFERENCE_MODULES:
        assert not (PACKAGE / (module + ".py")).exists(), module

    for path in PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level and node.module:
                assert node.module.split(".", 1)[0] not in REMOVED_REFERENCE_MODULES, (
                    path,
                    node.module,
                )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("bifrost_scales."):
                        imported = alias.name.split(".", 1)[1].split(".", 1)[0]
                        assert imported not in REMOVED_REFERENCE_MODULES, (path, imported)


def test_runtime_uses_no_dynamic_bifrost_graph_commands():
    forbidden = ("vnnCompound", "vnnNode", "vnnConnect", "vnnChangeBracket", "setExternalValue")
    for path in PACKAGE.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in source, (path, token)


def test_release_version_and_module_are_consistent():
    version_source = (PACKAGE / "version.py").read_text(encoding="utf-8")
    module_source = (ROOT / "BifrostScales.mod").read_text(encoding="utf-8")
    plugin_source = (ROOT / "BifrostScales/plug-ins/bifrostScalesCellPicker.py").read_text(encoding="utf-8")
    assert 'VERSION = "0.10.9"' in version_source
    assert 'SCHEMA_VERSION = "bifrost-scales/5"' in version_source
    assert module_source.startswith("+ BifrostScales 0.10.9 ")
    assert 'MFnPlugin(plugin, "Bifrost Scales", "0.10.9", "Any")' in plugin_source


def test_ui_is_native_only_and_new_create_finishes_first_preview():
    ui = (PACKAGE / "ui.py").read_text(encoding="utf-8")
    backend = (PACKAGE / "backend.py").read_text(encoding="utf-8")
    assert "class NativeMayaBackend" in backend
    assert 'PREVIEW_BACKENDS = ("native",)' in backend
    assert "def create_system_with_preview" in backend
    assert "self.native.create_graph(binding)" in backend
    assert "report = self.apply" in backend
    assert "選択メッシュから新規作成（Bifrost Previewまで）" in ui
    assert "create_system_with_preview" in ui
    assert "preview_backend_combo" not in ui
    assert "final_and_bake_button" not in ui
    assert "_final_and_bake" not in ui


def test_python_final_bake_and_public_python_smoke_are_removed():
    combined = "\n".join(
        (PACKAGE / name).read_text(encoding="utf-8")
        for name in ("__init__.py", "backend.py", "scene.py", "ui.py")
    )
    for token in (
        "def generate_final",
        "def bake_preview",
        "run_smoke_test",
        "maya_smoke",
    ):
        assert token not in combined
    assert "run_native_smoke_test" in (PACKAGE / "__init__.py").read_text(encoding="utf-8")


def test_native_operator_and_host_boundary_contracts_remain_immutable():
    contract = json.loads((ROOT / "native/bifrost/operator_contract.json").read_text(encoding="utf-8"))
    policy = contract["graph_policy"]
    performance = contract["performance_contract"]
    assert contract["schema"] == "bifrost-scales/operator-contract/20"
    assert contract["published_graph"] == "Graphs::BifrostScales::native_scales_v4"
    assert policy["runtime_topology_mutation"] is False
    assert policy["python_vnn_commands"] is False
    assert policy["normal_updates"] == ["payload_json", "parent_visibility"]
    assert policy["target_binding"] == "maya-dg-worldMesh-once"
    assert performance["direction_anisotropic_partition_runtime"] is True
    assert performance["direction_anisotropy_max_axis_ratio"] == 2.25
    assert performance["direction_only_edits_reuse_exact_cell_partition"] is False
    assert performance["direction_strength_edits_reuse_exact_cell_partition"] is True
    assert performance["gpu_buffer_schema"] == "bifrost-scales/compact-orientation-buffer/2"
    assert performance["settled_distribution_field"] == (
        "triangle-corner-cached-barycentric"
    )
    assert performance["settled_distribution_deterministic"] is True
    assert performance["distribution_density_acceptance_upper_bound"] == (
        "matches-evaluated-density-field-16"
    )
    assert performance["settled_distribution_candidate_sampling"] == (
        "triangle-area-times-corner-density-upper-bound"
    )
    assert performance["settled_distribution_density_acceptance"] == (
        "candidate-density-over-triangle-upper-bound"
    )
    assert performance["settled_distribution_stall_policy"] == (
        "next-spacing-after-max-1024-target-over-64-consecutive-conflicts"
    )
    assert performance["settled_distribution_grid_density_reference"] == (
        "minimum-density-with-settled-floor-0.08"
    )
    assert performance["settled_distribution_triangle_lookup"] == (
        "validated-cumulative-bin-index-65536"
    )
    assert performance["settled_distribution_conflict_diagnostics"] == (
        "bucket-queries-distance-tests-grid-density-reference"
    )
    assert performance["final_distribution_field"] == (
        "exact-per-candidate-surface-connected"
    )
    assert (
        performance["direction_only_edits_reuse_cell_partition_when_anisotropy_zero"]
        is True
    )

    native_backend = (PACKAGE / "native_backend.py").read_text(encoding="utf-8")
    assert "bifrost-scales/native-graph/4-dgmesh-1" in native_backend
    assert "maya-dg-worldMesh" in native_backend
    assert "def invalidate" in native_backend


def test_native_core_performance_and_stable_cell_contracts_remain_present():
    header = (ROOT / "native/include/bifrost_scales/core.hpp").read_text(encoding="utf-8")
    source = (ROOT / "native/src/core.cpp").read_text(encoding="utf-8")
    operator = (ROOT / "native/operator/src/bifrost_scales_nodedef.cpp").read_text(encoding="utf-8")
    gpu = (ROOT / "native/src/gpu_compute.cpp").read_text(encoding="utf-8")
    backend = (PACKAGE / "backend.py").read_text(encoding="utf-8")
    ui = (PACKAGE / "ui.py").read_text(encoding="utf-8")
    assert "struct GenerationProfile" in header
    assert "std::vector<std::uint64_t> cell_ids" in header
    assert "struct CellMetadata" in header
    assert "direction_grid" in source
    assert "class SurfaceProjector" in source
    assert "class ProcessStageCache" in source
    assert "process-shared-bounded" in header
    assert "BIFROST_SCALES_STAGE_CACHE_ENTRIES" in source
    assert "class DistributionGuideIndex" in source
    assert "class SettledDistributionFieldCache" in source
    assert "struct SurfaceGuideFieldCache" in source
    assert "guide_surface_cache_hits" in header
    assert "guide_surface_cache_misses" in operator
    assert "native_guide_surface_ms" in backend
    assert "guideSurface=" in ui
    assert "meshSample=" in ui
    assert "native_global_projection_cache_hit" in backend
    assert "projectorCache=" in ui
    assert "struct DirectionGuideContribution" in source
    assert "reuse_direction_neighbors" in source
    assert "struct DirectionNeighborGraph" in source
    assert "find_direction_neighbors" in source
    assert "maximum_average_cached_neighbors" in source
    assert "orientation_prepare_ms" in header
    assert "direction_neighbors_ms" in operator
    assert "direction_neighbors_cache_hit" in operator
    assert "native_direction_neighbors_ms" in backend
    assert "native_direction_neighbors_cache_hit" in backend
    assert "neighborCache=" in ui
    assert "orientParts=" in ui
    assert "gpuParts=" in ui
    assert "relaxParts=" in ui
    assert "direction_relax_pack_ms" in header
    assert "direction_relax_gpu_call_ms" in operator
    assert "native_direction_relax_unpack_ms" in backend
    assert "intentionally serial" in source
    assert "try_compute_direction_relax" in source
    assert "__kernel void direction_relax" in gpu
    assert "mode == PreviewMode::Settled" in source
    assert "maximum_neighbor_threshold" in source
    assert "settled_density_weighted_sampling" in source
    assert "settled_triangle_density_bounds" in source
    assert "settled_conflict_stall_limit" in source
    assert "grid_density_reference" in source
    assert "proposal_bin_offsets" in source
    assert "65536U" in source
    assert "exact_lower_bound" in source
    assert "hasher.key(distribution)" in source
    assert "cell_cache_reused_after_orientation_change" in source
    assert "bifrost-scales/cell-id/1" in source
    assert "bifrost-scales/cell-metadata/1" in operator
    assert "bifrost-scales/native-profile/11" in operator
    assert "distribution_density_rejected" in header
    assert "distribution_density_rejected" in operator
    assert "native_distribution_conflict_rejected" in backend
    assert "native_distribution_bucket_queries" in backend
    assert "native_distribution_distance_tests" in backend
    assert "native_distribution_grid_density_reference" in backend
    assert "--distribution-only" in (
        ROOT / "native/tools/parity_dump.cpp"
    ).read_text(encoding="utf-8")
    assert "cell_boundary_query_ms" in operator
    assert "cell_boundary_rays_ms" in operator
    assert "cell_mean_neighbors" in operator
    assert "class BoundaryIndex" in source
    assert "bounds_distance_squared(node.bounds, position)" in source
    assert "direction_metric_weight" in source
    assert "guide-anisotropic" in source
    assert "cell_direction_anisotropy" in header
    assert "cell_cache_basis" in operator
    assert "update_orientation_dirty_region" not in source
    assert "BIFROST_SCALES_GPU" in gpu
    assert "orientation_preview" in gpu
    assert "gpu_compute_requested" in operator
    assert "boundary_density_adapted" in source
    assert "std::vector<Vec2> ray_directions" in source
    assert "std::vector<Vec3> normals" in source
    assert "std::vector<std::uint32_t> components" in source
    assert "const bool has_mask_guides" not in source
    assert "mask_entry_radius" not in source
    assert "sample_visible_for_mask" in source
    assert "partition_sites" not in source
    assert "pair_influences" not in source


def test_guide_authoring_and_internal_cell_identity_foundation_remain_available():
    ui = (PACKAGE / "ui.py").read_text(encoding="utf-8")
    scene = (PACKAGE / "scene.py").read_text(encoding="utf-8")
    backend = (PACKAGE / "backend.py").read_text(encoding="utf-8")
    settings = (PACKAGE / "settings.py").read_text(encoding="utf-8")
    native_payload = (PACKAGE / "native_payload.py").read_text(encoding="utf-8")
    picker = (ROOT / "BifrostScales/plug-ins/bifrostScalesCellPicker.py").read_text(encoding="utf-8")
    assert "create_guide_point_button" in ui
    assert "draw_guide_curve_button" in ui
    assert "create_guide_group_button" in ui
    assert "Unique Scales" not in ui
    assert "UniqueScale" not in settings
    assert "register_selected_unique_scales" not in backend
    assert 'GUIDE_DISPLAY_NAME = "bsGuideDisplayName"' in scene
    assert 'GUIDE_CENTER_ALIGNMENT = "bsGuideCenterAlignment"' in scene
    assert 'GUIDE_CELL_ANISOTROPY = "bsGuideCellAnisotropy"' in scene
    assert "drawFeedback" in picker
    assert "cell_metadata_for_indices" in backend
    assert "resolve_cell_ids" in native_payload


def test_build_info_records_the_native_only_boundary():
    info = json.loads((ROOT / "BUILD_INFO.json").read_text(encoding="utf-8"))
    assert info["version"] == "0.10.9"
    assert info["runtime_engine"] == "native-bifrost-only"
    assert info["python_reference_runtime"] is False
    assert info["python_reference_preview"] is False
    assert info["python_reference_final"] is False
    assert info["python_reference_bake"] is False
    assert info["create_button_contract"] == (
        "selected-mesh-to-system-native-graph-and-first-settled-preview"
    )
    assert info["minimum_native_pack"] == "0.10.9"
    assert info["cell_cache_key_basis"] == "distribution-or-guide-anisotropic"
    assert info["direction_edits_reuse_exact_cell_partition"] is False
    assert info["direction_strength_affects_orientation_only"] is True
    assert info["direction_strength_edits_reuse_exact_cell_partition"] is True
    assert info["direction_curve_center_alignment_default"] == 0.35
    assert info["guide_cell_anisotropy_default"] == 1.0
    assert info["direction_edits_reuse_cell_partition_when_anisotropy_zero"] is True
    assert info["direction_edit_orientation_policy"] == (
        "0.10.2-full-rebuild-no-dirty-region"
    )
    assert info["gpu_generation_compute"] is True
    assert info["gpu_preview_benchmark_schema"] == (
        "bifrost-scales/gpu-preview-benchmark/3"
    )
    assert info["gpu_failure_policy"] == "automatic-cpu-multicore-fallback"
    assert info["interactive_candidate_batch_runtime_enabled"] is True
    assert info["interactive_conflict_reference_runtime_enabled"] is True
    assert info["interactive_conflict_gpu_runtime_enabled"] is True
    assert info["interactive_conflict_gpu_default_crossover_candidates"] == 65536
    assert info["interactive_distribution_candidate_multiplier"] == 4
    assert info["interactive_distribution_preserves_cpu_anchors"] is True
    assert info["global_projection_bvh_cache"] == (
        "process-shared-bounded/2-geometry-hash"
    )
    assert info["interactive_distribution_mask_stage"] == "post-cell-shape-only"
    assert info["settled_distribution_unchanged"] is False
    assert info["settled_distribution_field"] == (
        "triangle-corner-cached-barycentric"
    )
    assert info["orientation_guide_field"] == (
        "once-per-sample-reused-initial-final"
    )
    assert info["direction_relax_neighbor_query"] == (
        "distance-qualified-compact-csr-settled-multi-iteration"
    )
    assert info["direction_relax_neighbor_cache"] == (
        "distribution-keyed-process-shared-bounded"
    )
    assert info["orientation_profile_breakdown"] == (
        "prepare-neighbors-relax-finalize"
    )
    assert info["direction_relax_compute_backend"] == (
        "opencl-gpu-with-cpu-exact-guide-evaluation-and-fallback"
    )
    assert info["direction_relax_gpu_transfer_conversion"] == (
        "serial-compact-8k-15k-optimized"
    )
    assert info["direction_relax_profile_breakdown"] == (
        "pack-gpu-call-unpack"
    )
    assert info["direction_relax_gpu_runtime_enabled"] is True
    assert info["settled_distribution_deterministic"] is True
    assert info["final_distribution_field"] == (
        "exact-per-candidate-surface-connected"
    )
    assert info["open_boundary_density_adaptive"] is True
    assert info["native_stage_cache"] == (
        "process-shared-bounded-lru-exact-dual-hash"
    )
    assert info["distribution_candidate_guide_index"] == (
        "deterministic-authored-order-aabb-bvh"
    )
    assert info["distribution_density_acceptance_upper_bound"] == (
        "matches-evaluated-density-field-16"
    )
    assert info["settled_distribution_candidate_sampling"] == (
        "triangle-area-times-corner-density-upper-bound"
    )
    assert info["settled_distribution_density_acceptance"] == (
        "candidate-density-over-triangle-upper-bound"
    )
    assert info["settled_distribution_stall_policy"] == (
        "next-spacing-after-max-1024-target-over-64-consecutive-conflicts"
    )
    assert info["settled_distribution_grid_density_reference"] == (
        "minimum-density-with-settled-floor-0.08"
    )
    assert info["settled_distribution_triangle_lookup"] == (
        "validated-cumulative-bin-index-65536"
    )
    assert info["settled_distribution_conflict_diagnostics"] == (
        "bucket-queries-distance-tests-grid-density-reference"
    )
    assert info["cell_hot_path"] == (
        "single-site-precomputed-ray-table-normal-component"
    )
    assert info["direction_pair_partition_runtime"] is False
    assert info["direction_anisotropic_partition_runtime"] is True
    assert info["direction_anisotropy_max_axis_ratio"] == 2.25
    assert info["guide_mask_density_falloff"] is False
    assert info["guide_mask_post_cell_visibility"] is True
    assert info["guide_mask_preserves_distribution_and_cells"] is True
    assert info["guide_mask_visibility_random_basis"] == "stable-cell-id"
    assert info["guide_falloff_distance"] == "mesh-edge-shortest-path"
    assert info["guide_falloff_control"] == "normalized-width-within-range"
    assert info["guide_falloff_full_effect_radius"] == (
        "range-times-one-minus-falloff"
    )
    assert info["native_pack_rebuild_required_for_release"] is True
    assert info["installer_native_preservation_scope"] == "installed-pack-only"
    assert info["installer_discards_transient_bifrost_out"] is True
    assert info["installer_revision"] == 2
    assert info["one_click_installer_schema"] == (
        "bifrost-scales/one-click-build/1"
    )
    assert info["one_click_payload_schema"] == (
        "bifrost-scales/one-click-payload/1"
    )
    assert info["one_click_platform"] == "windows-x64-maya2026"
    assert info["one_click_integrity"] == (
        "sha256-all-payload-files-before-and-after-copy"
    )
    assert info["one_click_transaction"] == (
        "unique-backup-with-automatic-rollback"
    )
    assert info["release_input_contract"] == (
        "git-tracked-plus-current-generated-with-exported-tree-fallback"
    )
    assert info["release_text_normalization"] == (
        "utf8-line-endings-to-lf-binary-unchanged"
    )


def test_interactive_distribution_uses_candidate_gpu_runtime_only():
    core = (ROOT / "native/src/core.cpp").read_text(encoding="utf-8")
    preview = (
        ROOT / "native/include/bifrost_scales/preview_distribution.hpp"
    ).read_text(encoding="utf-8")

    assert '#include "bifrost_scales/preview_distribution.hpp"' in core
    assert "mode == PreviewMode::Interactive && samples.size() < count" in core
    assert "build_interactive_candidate_batch(mesh, settings, candidate_count)" in core
    assert "arbitrate_interactive_candidates_accelerated(" in core
    assert '"interactive-distribution"' in core
    assert "mode != PreviewMode::Interactive" in core
    assert "Settled output never uses this API" in preview
    assert "struct InteractiveSurfaceCache" in (
        ROOT / "native/src/preview_distribution.cpp"
    ).read_text(encoding="utf-8")
    assert "surface_cache_hit" in preview


def test_guide_falloff_is_a_normalized_width_inside_range():
    core = (ROOT / "native/src/core.cpp").read_text(encoding="utf-8")
    gpu = (ROOT / "native/src/gpu_compute.cpp").read_text(encoding="utf-8")
    guides = (
        ROOT / "BifrostScales/scripts/bifrost_scales/guides.py"
    ).read_text(encoding="utf-8")
    ui = (ROOT / "BifrostScales/scripts/bifrost_scales/ui.py").read_text(
        encoding="utf-8"
    )

    assert "clamp(guide.falloff, 0.0, 1.0)" in core
    assert "radius * (1.0 - falloff_width)" in core
    assert "radius * (1.0f - falloff_width)" in gpu
    assert "falloff=max(0.0, min(1.0" in guides
    assert "FloatParameterControl(0.0, 1.0, 1.0, decimals=3)" in ui


def test_installer_preserves_pack_without_copying_transient_build_tree():
    source = (ROOT / "tools/build_release.py").read_text(encoding="utf-8")
    assert "def _preserve_native_pack(" in source
    assert 'relative = Path("bifrost") / "pack"' in source
    assert 'Path("bifrost") / "out"' not in source


def test_native_schema_and_native_only_audits_pass():
    from tools.native_only_runtime_audit import audit as runtime_audit
    from tools.schema_contract_audit import audit as schema_audit

    assert runtime_audit()["success"] is True
    assert schema_audit()["success"] is True
