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
    assert 'VERSION = "0.10.6"' in version_source
    assert 'SCHEMA_VERSION = "bifrost-scales/5"' in version_source
    assert module_source.startswith("+ BifrostScales 0.10.6 ")
    assert 'MFnPlugin(plugin, "Bifrost Scales", "0.10.6", "Any")' in plugin_source


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
    assert contract["schema"] == "bifrost-scales/operator-contract/18"
    assert contract["published_graph"] == "Graphs::BifrostScales::native_scales_v4"
    assert policy["runtime_topology_mutation"] is False
    assert policy["python_vnn_commands"] is False
    assert policy["normal_updates"] == ["payload_json", "parent_visibility"]
    assert policy["target_binding"] == "maya-dg-worldMesh-once"

    native_backend = (PACKAGE / "native_backend.py").read_text(encoding="utf-8")
    assert "bifrost-scales/native-graph/4-dgmesh-1" in native_backend
    assert "maya-dg-worldMesh" in native_backend
    assert "def invalidate" in native_backend


def test_native_core_performance_and_stable_cell_contracts_remain_present():
    header = (ROOT / "native/include/bifrost_scales/core.hpp").read_text(encoding="utf-8")
    source = (ROOT / "native/src/core.cpp").read_text(encoding="utf-8")
    operator = (ROOT / "native/operator/src/bifrost_scales_nodedef.cpp").read_text(encoding="utf-8")
    gpu = (ROOT / "native/src/gpu_compute.cpp").read_text(encoding="utf-8")
    assert "struct GenerationProfile" in header
    assert "std::vector<std::uint64_t> cell_ids" in header
    assert "struct CellMetadata" in header
    assert "direction_grid" in source
    assert "class SurfaceProjector" in source
    assert "class ProcessStageCache" in source
    assert "process-shared-bounded" in header
    assert "BIFROST_SCALES_STAGE_CACHE_ENTRIES" in source
    assert "class DistributionGuideIndex" in source
    assert "maximum_neighbor_threshold" in source
    assert "hasher.key(distribution)" in source
    assert "cell_cache_reused_after_orientation_change" in source
    assert "bifrost-scales/cell-id/1" in source
    assert "bifrost-scales/cell-metadata/1" in operator
    assert "bifrost-scales/native-profile/9" in operator
    assert "cell_cache_basis" in operator
    assert "update_orientation_dirty_region" not in source
    assert "BIFROST_SCALES_GPU" in gpu
    assert "orientation_preview" in gpu
    assert "gpu_compute_requested" in operator
    assert "boundary_density_adapted" in source
    assert "std::vector<Vec2> ray_directions" in source
    assert "std::vector<Vec3> normals" in source
    assert "std::vector<std::uint32_t> components" in source
    assert "const bool has_mask_guides" in source
    assert "partition_sites" not in source
    assert "pair_influences" not in source


def test_guide_authoring_cell_picker_and_unique_override_authoring_remain_available():
    ui = (PACKAGE / "ui.py").read_text(encoding="utf-8")
    scene = (PACKAGE / "scene.py").read_text(encoding="utf-8")
    picker = (ROOT / "BifrostScales/plug-ins/bifrostScalesCellPicker.py").read_text(encoding="utf-8")
    settings = (PACKAGE / "settings.py").read_text(encoding="utf-8")
    assert "create_guide_point_button" in ui
    assert "draw_guide_curve_button" in ui
    assert "create_guide_group_button" in ui
    assert "Native Cell Picker" in ui
    assert "Unique Override Authoring" in ui
    assert 'GUIDE_DISPLAY_NAME = "bsGuideDisplayName"' in scene
    assert "drawFeedback" in picker
    assert "bifrost-scales/unique-overrides/1" in settings


def test_build_info_records_the_native_only_boundary():
    info = json.loads((ROOT / "BUILD_INFO.json").read_text(encoding="utf-8"))
    assert info["version"] == "0.10.6"
    assert info["runtime_engine"] == "native-bifrost-only"
    assert info["python_reference_runtime"] is False
    assert info["python_reference_preview"] is False
    assert info["python_reference_final"] is False
    assert info["python_reference_bake"] is False
    assert info["create_button_contract"] == (
        "selected-mesh-to-system-native-graph-and-first-settled-preview"
    )
    assert info["minimum_native_pack"] == "0.10.6"
    assert info["cell_cache_key_basis"] == "distribution-not-orientation"
    assert info["direction_edits_reuse_exact_cell_partition"] is True
    assert info["direction_edit_orientation_policy"] == (
        "0.10.2-full-rebuild-no-dirty-region"
    )
    assert info["gpu_generation_compute"] is True
    assert info["gpu_failure_policy"] == "automatic-cpu-multicore-fallback"
    assert info["open_boundary_density_adaptive"] is True
    assert info["native_stage_cache"] == (
        "process-shared-bounded-lru-exact-dual-hash"
    )
    assert info["distribution_candidate_guide_index"] == (
        "deterministic-authored-order-aabb-bvh"
    )
    assert info["cell_hot_path"] == (
        "single-site-precomputed-ray-table-normal-component-mask-gate"
    )
    assert info["direction_pair_partition_runtime"] is False
    assert info["native_pack_rebuild_required_for_release"] is True
    assert info["installer_native_preservation_scope"] == "installed-pack-only"
    assert info["installer_discards_transient_bifrost_out"] is True
    assert info["installer_revision"] == 2


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
