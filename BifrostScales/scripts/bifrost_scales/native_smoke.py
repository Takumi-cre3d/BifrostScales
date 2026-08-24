"""Maya-host smoke test for the native Bifrost preview boundary.

The test is self-contained by default.  When no current-schema Bifrost Scales
System exists, it creates a small temporary polygon plane and System before
importing and evaluating the immutable Published Graph.  This keeps the probe
useful in a clean Maya scene and matches the production Native-only creation path.
"""

from __future__ import annotations

import time
from typing import Any

from .backend import NativeMayaBackend
from .scheduler import ChangeCategory, PreviewMode, PreviewRequest
from .settings import ScaleSettings


def _smoke_settings() -> ScaleSettings:
    """Return a deliberately small deterministic Native smoke-test payload."""

    return ScaleSettings(
        target_count=32,
        settled_budget=32,
        interactive_budget=16,
        relax_iterations=1,
        direction_relax_iterations=1,
        cell_settled_resolution=8,
        cell_shape_divisions=2,
    )


def _create_temporary_system(
    backend: NativeMayaBackend,
    cmds_module: Any,
) -> tuple[str, str]:
    """Create a low-cost target and System, rolling back partial creation."""

    target = ""
    try:
        created = cmds_module.polyPlane(
            name="bifrostScalesNativeSmokeTarget#",
            width=4.0,
            height=4.0,
            subdivisionsX=4,
            subdivisionsY=4,
        )
        if not created:
            raise RuntimeError("Native smoke target could not be created")
        target = str(created[0])
        binding = backend.create_system(target, _smoke_settings())
        return target, binding.settings_node
    except Exception:
        if target:
            try:
                if cmds_module.objExists(target):
                    cmds_module.delete(target)
            except Exception:
                pass
        raise


def run(
    settings_node: str | None = None,
    evaluate: bool = False,
    cleanup_graph: bool = False,
    auto_create_system: bool = True,
    cleanup_test_system: bool | None = None,
    cmds_module: Any | None = None,
    om_module: Any | None = None,
) -> dict[str, Any]:
    """Probe or evaluate the Native Published Graph in Maya.

    Args:
        settings_node: Existing current-schema System to evaluate.  When
            omitted, the first existing System is used.
        evaluate: When false, perform a read-only Native environment probe.
        cleanup_graph: Delete the graph created by this test after evaluation.
        auto_create_system: If no System exists, create a deterministic test
            plane and System automatically.
        cleanup_test_system: Controls cleanup only for an automatically created
            System.  ``None`` follows ``cleanup_graph``: a retained graph keeps
            its temporary System, while a cleaned graph removes all test data.
        cmds_module: Test seam for ``maya.cmds``.
        om_module: Test seam for ``maya.api.OpenMaya``.
    """

    if cmds_module is None:
        import maya.cmds as cmds_module  # type: ignore

    backend = NativeMayaBackend(cmds_module=cmds_module, om_module=om_module)
    status = backend.native_status()
    result: dict[str, Any] = {
        "success": bool(status.ready) if not evaluate else False,
        "phase": "probe",
        "native": status.to_mapping(),
        "graph_definition": "Graphs::BifrostScales::native_scales_v4",
        "operator_definition": "BifrostScales::generate_scale_mesh_payload_arrays",
        "auto_created_system": False,
    }
    if not evaluate:
        return result

    # Do not modify the Maya scene when the Native Pack is unavailable.
    if not status.ready:
        result["error"] = "; ".join(status.reasons)
        return result

    systems = backend.list_systems()
    selected = str(settings_node or (systems[0] if systems else ""))
    created_target = ""
    created_settings = ""
    graph = ""
    cleanup_created = bool(cleanup_graph) if cleanup_test_system is None else bool(
        cleanup_test_system
    )

    try:
        result["phase"] = "setup"
        if not selected:
            if not auto_create_system:
                result["error"] = (
                    "Bifrost Scales Systemがありません。Target MeshからSystemを作成するか、"
                    "auto_create_system=Trueで実行してください。"
                )
                return result
            created_target, created_settings = _create_temporary_system(
                backend,
                cmds_module,
            )
            selected = created_settings
            result.update(
                {
                    "auto_created_system": True,
                    "temporary_target": created_target,
                    "temporary_settings_node": created_settings,
                }
            )

        backend.bind(selected)
        graph = backend.create_native_graph()
        settings = backend.read_settings()
        request = PreviewRequest(
            revision=1,
            mode=PreviewMode.SETTLED,
            categories=frozenset({ChangeCategory.DISTRIBUTION}),
            scope=ChangeCategory.DISTRIBUTION,
            snapshot=settings.to_mapping(),
            created_at=time.monotonic(),
        )
        report = backend.apply(request)
        result.update(
            {
                "success": True,
                "phase": "evaluate",
                "settings_node": selected,
                "graph_shape": graph,
                "scale_count": report.scale_count,
                "point_count": report.vertex_count,
                "face_count": report.face_count,
                "mesh_update": report.mesh_update,
                "total_ms": report.total_ms,
                "native_execution_wait_ms": report.native_execution_wait_ms,
                "native_execution_counter_before": report.native_execution_counter_before,
                "native_execution_counter_after": report.native_execution_counter_after,
                "native_evaluation_policy": report.native_evaluation_policy,
            }
        )
    except Exception as exc:
        result["error"] = "{}: {}".format(type(exc).__name__, exc)
    finally:
        if created_settings and cleanup_created:
            try:
                if (
                    backend.binding is None
                    or backend.binding.settings_node != created_settings
                ):
                    backend.bind(created_settings)
                backend.delete_system()
                result["test_system_cleaned"] = True
                if graph:
                    result["graph_cleaned"] = True
            except Exception as exc:
                result["system_cleanup_error"] = "{}: {}".format(
                    type(exc).__name__, exc
                )
            try:
                if created_target and cmds_module.objExists(created_target):
                    cmds_module.delete(created_target)
                result["test_target_cleaned"] = True
            except Exception as exc:
                result["target_cleanup_error"] = "{}: {}".format(
                    type(exc).__name__, exc
                )
        elif cleanup_graph and graph:
            try:
                backend.delete_native_graph()
                result["graph_cleaned"] = True
            except Exception as exc:
                result["cleanup_error"] = "{}: {}".format(type(exc).__name__, exc)
        elif created_settings:
            result["temporary_system_retained"] = True

    return result
