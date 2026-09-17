"""Standalone environment diagnostics."""

from __future__ import annotations

import platform
import sys
from typing import Any

from .version import VERSION


def probe_environment(cmds_module: Any | None = None) -> dict[str, Any]:
    if cmds_module is None:
        import maya.cmds as cmds_module  # type: ignore
    systems = []
    try:
        from .scene import MayaSceneManager

        systems = MayaSceneManager(cmds_module).list_systems()
    except Exception:
        pass
    return {
        "product": "Bifrost Scales",
        "version": VERSION,
        "engine": "native_bifrost_only",
        "preview_architecture": "immutable_static_bifrost_graph",
        "mesh_update_policy": "payload_json_plus_worldMesh_dg_binding",
        "python_reference_runtime": False,
        "python": sys.version,
        "platform": platform.platform(),
        "maya_version": str(cmds_module.about(version=True)),
        "maya_api": str(cmds_module.about(apiVersion=True)),
        "systems": systems,
    }
