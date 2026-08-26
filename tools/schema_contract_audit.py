"""Audit the Native-only host and operator contracts without Maya."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PRODUCT_VERSION = "0.10.6"
EXPECTED_PAYLOAD_SCHEMA = "bifrost-scales/native-payload/10"
EXPECTED_OPERATOR_CONTRACT = "bifrost-scales/operator-contract/18"
EXPECTED_MINIMUM_PACK = "0.10.6"
EXPECTED_NATIVE_BEHAVIOR_CONTRACT = "bifrost-scales/native-core/0.10.6-cell-hot-path-1"
EXPECTED_NATIVE_PROFILE_SCHEMA = "bifrost-scales/native-profile/9"


def _extract(pattern: str, text: str, label: str) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        raise RuntimeError("Unable to read {}".format(label))
    return str(match.group(1))


def _graph_payload_schema(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    compounds = data.get("compounds", [])
    if len(compounds) != 1:
        raise RuntimeError("Published Graph must contain exactly one compound")
    port = next(
        item for item in compounds[0].get("ports", [])
        if item.get("portName") == "payload_json"
    )
    return str(json.loads(str(port.get("portDefault", "{}"))).get("schema", ""))


def audit(root: Path = ROOT) -> dict[str, Any]:
    package = root / "BifrostScales" / "scripts" / "bifrost_scales"
    graph = root / "BifrostScales" / "bifrost" / "compounds" / "BifrostScales_native_scales_v4_graph.json"
    manifest = graph.parent / "manifest.bifrost-scales.json"
    operator_contract = root / "native" / "bifrost" / "operator_contract.json"
    build_info = json.loads((root / "BUILD_INFO.json").read_text(encoding="utf-8"))
    release_builder_text = (root / "tools" / "build_release.py").read_text(
        encoding="utf-8"
    )

    graph_data = json.loads(graph.read_text(encoding="utf-8-sig"))
    graph_compound = graph_data["compounds"][0]
    graph_ports = {str(item.get("portName", "")) for item in graph_compound.get("ports", [])}
    graph_connections = {
        (str(item.get("source", "")), str(item.get("target", "")))
        for item in graph_compound.get("connections", [])
        if isinstance(item, dict)
    }
    manifest_data = json.loads(manifest.read_text(encoding="utf-8-sig"))
    operator_data = json.loads(operator_contract.read_text(encoding="utf-8-sig"))

    version_text = (package / "version.py").read_text(encoding="utf-8")
    payload_text = (package / "native_payload.py").read_text(encoding="utf-8")
    backend_text = (package / "native_backend.py").read_text(encoding="utf-8")
    host_backend_text = (package / "backend.py").read_text(encoding="utf-8")
    stable_id_text = (package / "stable_ids.py").read_text(encoding="utf-8")
    cpp_payload_text = (root / "native" / "src" / "payload.cpp").read_text(encoding="utf-8")
    core_header_text = (root / "native" / "include" / "bifrost_scales" / "core.hpp").read_text(encoding="utf-8")
    core_source_text = (root / "native" / "src" / "core.cpp").read_text(encoding="utf-8")
    gpu_source_text = (root / "native" / "src" / "gpu_compute.cpp").read_text(encoding="utf-8")
    operator_source_text = (root / "native" / "operator" / "src" / "bifrost_scales_nodedef.cpp").read_text(encoding="utf-8")
    cmake_text = (root / "native" / "CMakeLists.txt").read_text(encoding="utf-8")

    values = {
        "product_version": _extract(r'^VERSION\s*=\s*"([^"]+)"', version_text, "product version"),
        "python_payload_schema": _extract(r'^NATIVE_PAYLOAD_SCHEMA\s*=\s*"([^"]+)"', payload_text, "payload schema"),
        "module_graph_payload_schema": _graph_payload_schema(graph),
        "module_manifest_payload_schema": str(manifest_data.get("native_payload_schema", "")),
        "module_native_behavior_contract": str(manifest_data.get("native_behavior_contract", "")),
        "module_native_profile_schema": str(manifest_data.get("native_profile_schema", "")),
        "python_native_behavior_contract": _extract(r'^NATIVE_BEHAVIOR_CONTRACT\s*=\s*"([^"]+)"', backend_text, "behavior contract"),
        "python_native_profile_schema": _extract(r'^NATIVE_PROFILE_SCHEMA\s*=\s*"([^"]+)"', backend_text, "profile schema"),
        "operator_contract": str(operator_data.get("schema", "")),
        "operator_contract_payload_schema": str(operator_data.get("payload_schema", "")),
        "operator_profile_schema": str(operator_data.get("performance_contract", {}).get("profile_schema", "")),
        "operator_compute_backend": str(operator_data.get("performance_contract", {}).get("compute_backend", "")),
        "operator_gpu_generation_compute": bool(operator_data.get("performance_contract", {}).get("gpu_generation_compute", True)),
        "operator_cell_cache_key_basis": str(
            operator_data.get("performance_contract", {}).get(
                "cell_cache_key_basis", ""
            )
        ),
        "operator_stage_cache": str(
            operator_data.get("performance_contract", {}).get(
                "stage_cache", ""
            )
        ),
        "manifest_stage_cache": str(
            manifest_data.get("native_stage_cache_contract", "")
        ),
        "manifest_cell_cache_key_basis": str(
            manifest_data.get("native_cell_cache_key_basis", "")
        ),
        "cpp_payload_schema": _extract(r'schema\s*!=\s*"([^"]+)"', cpp_payload_text, "C++ payload schema"),
        "minimum_native_pack": _extract(r'^MINIMUM_NATIVE_PACK_VERSION_TEXT\s*=\s*"([^"]+)"', backend_text, "minimum Native Pack"),
        "native_cmake_version": _extract(r'project\(BifrostScalesCore VERSION ([0-9.]+)', cmake_text, "Native CMake version"),
    }

    checks = {
        "product_version": values["product_version"] == EXPECTED_PRODUCT_VERSION,
        "python_payload_schema": values["python_payload_schema"] == EXPECTED_PAYLOAD_SCHEMA,
        "module_graph_payload_schema": values["module_graph_payload_schema"] == EXPECTED_PAYLOAD_SCHEMA,
        "module_manifest_payload_schema": values["module_manifest_payload_schema"] == EXPECTED_PAYLOAD_SCHEMA,
        "module_native_behavior_contract": values["module_native_behavior_contract"] == EXPECTED_NATIVE_BEHAVIOR_CONTRACT,
        "python_native_behavior_contract": values["python_native_behavior_contract"] == EXPECTED_NATIVE_BEHAVIOR_CONTRACT,
        "operator_contract": values["operator_contract"] == EXPECTED_OPERATOR_CONTRACT,
        "operator_contract_payload_schema": values["operator_contract_payload_schema"] == EXPECTED_PAYLOAD_SCHEMA,
        "module_native_profile_schema": values["module_native_profile_schema"] == EXPECTED_NATIVE_PROFILE_SCHEMA,
        "operator_profile_schema": values["operator_profile_schema"] == EXPECTED_NATIVE_PROFILE_SCHEMA,
        "python_native_profile_schema": values["python_native_profile_schema"] == EXPECTED_NATIVE_PROFILE_SCHEMA,
        "operator_compute_backend": values["operator_compute_backend"] == "hybrid-opencl-gpu-interactive-cpu-exact-settled-final",
        "operator_gpu_generation_compute": values["operator_gpu_generation_compute"] is True,
        "operator_cell_cache_key_basis": values["operator_cell_cache_key_basis"] == "distribution-or-orientation-anisotropic",
        "manifest_cell_cache_key_basis": values["manifest_cell_cache_key_basis"] == "distribution-or-orientation-anisotropic",
        "operator_process_shared_stage_cache": values["operator_stage_cache"] == "process-shared-bounded-lru-exact-dual-hash",
        "manifest_process_shared_stage_cache": values["manifest_stage_cache"] == "process-shared-bounded-lru-exact-dual-hash",
        "core_process_shared_stage_cache": all(
            token in core_source_text
            for token in (
                "class ProcessStageCache",
                "BIFROST_SCALES_STAGE_CACHE_ENTRIES",
                "std::shared_ptr<const DistributionResult>",
            )
        ),
        "distribution_candidate_spatial_index": all(
            token in core_source_text
            for token in (
                "class DistributionGuideIndex",
                "maximum_neighbor_threshold",
                "largest_accepted_spacing",
            )
        ),
        "operator_profile_reports_stage_cache": all(
            token in operator_source_text
            for token in (
                "stage_cache_scope",
                "stage_cache_capacity",
                "stage_cache_evictions",
            )
        ),
        "core_cell_cache_uses_distribution_key": all(
            token in core_source_text
            for token in (
                "const CacheKey& distribution",
                "hasher.key(distribution)",
                "cell_cache_reused_after_orientation_change",
            )
        ),
        "operator_profile_reports_cell_cache_basis": all(
            token in operator_source_text
            for token in (
                "cell_cache_basis",
                "cell_cache_reused_after_orientation_change",
            )
        ),
        "operator_profile_reports_workers": all(
            token in operator_source_text
            for token in (
                "distribution_worker_threads",
                "orientation_worker_threads",
                "cell_worker_threads",
                "shape_worker_threads",
            )
        ),
        "core_parallel_runtime": all(
            token in core_source_text
            for token in (
                "BIFROST_SCALES_CPU_THREADS",
                "parallel_for_chunks",
                "std::thread",
            )
        ),
        "core_opencl_gpu_runtime": all(
            token in gpu_source_text
            for token in (
                "OpenCL.dll",
                "orientation_preview",
                "BIFROST_SCALES_GPU",
                "OpenCL runtime",
            )
        ),
        "operator_profile_reports_gpu": all(
            token in operator_source_text
            for token in (
                "gpu_compute_requested",
                "gpu_compute_available",
                "gpu_kernel_ms",
                "gpu_fallback_reason",
            )
        ),
        "boundary_density_adaptive_runtime": all(
            token in core_source_text
            for token in (
                "boundary_density_adapted",
                "density_sqrt",
                "weighted_distance",
            )
        ),
        "graph_profile_port": "profile_json" in graph_ports,
        "graph_profile_connection": ("generate_scale_mesh_payload_arrays.profile_json", ".profile_json") in graph_connections,
        "cpp_payload_schema": values["cpp_payload_schema"] == EXPECTED_PAYLOAD_SCHEMA,
        "minimum_native_pack": values["minimum_native_pack"] == EXPECTED_MINIMUM_PACK,
        "native_cmake_version": values["native_cmake_version"] == EXPECTED_MINIMUM_PACK,
        "runtime_probe_has_schema_gate": "payload_schema_contract_valid" in backend_text,
        "stable_id_python_contract": "bifrost-scales/cell-id/1" in stable_id_text and "FNV_OFFSET_BASIS_64" in stable_id_text,
        "stable_id_native_contract": "bifrost-scales/cell-id/1" in core_source_text and "std::uint64_t stable_id" in core_header_text,
        "cell_metadata_profile_contract": "bifrost-scales/cell-metadata/1" in operator_source_text and "selected_cells" in operator_source_text,
        "host_backend_is_native_only": "class NativeMayaBackend" in host_backend_text and 'PREVIEW_BACKENDS = ("native",)' in host_backend_text,
        "host_create_transaction_includes_graph_and_preview": "def create_system_with_preview" in host_backend_text and "self.native.create_graph(binding)" in host_backend_text,
        "world_mesh_binding_contract": "maya-dg-worldMesh" in backend_text,
        "normal_update_contract": operator_data.get("graph_policy", {}).get("normal_updates") == ["payload_json", "parent_visibility"],
        "installer_pack_only_preservation": (
            build_info.get("installer_revision") == 2
            and build_info.get("installer_native_preservation_scope")
            == "installed-pack-only"
            and build_info.get("installer_discards_transient_bifrost_out") is True
            and "def _preserve_native_pack(" in release_builder_text
            and 'relative = Path("bifrost") / "pack"' in release_builder_text
            and 'Path("bifrost") / "out"' not in release_builder_text
        ),
    }

    return {
        "schema": "bifrost-scales/native-schema-audit/2",
        "product": "Bifrost Scales",
        "version": EXPECTED_PRODUCT_VERSION,
        "expected": {
            "payload_schema": EXPECTED_PAYLOAD_SCHEMA,
            "operator_contract": EXPECTED_OPERATOR_CONTRACT,
            "minimum_native_pack": EXPECTED_MINIMUM_PACK,
            "native_behavior_contract": EXPECTED_NATIVE_BEHAVIOR_CONTRACT,
            "native_profile_schema": EXPECTED_NATIVE_PROFILE_SCHEMA,
        },
        "values": values,
        "checks": checks,
        "success": all(checks.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit(args.root.resolve())
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(
        "Native schema audit: {}; checks={}/{}".format(
            "PASS" if report["success"] else "FAIL",
            sum(bool(value) for value in report["checks"].values()),
            len(report["checks"]),
        )
    )
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
