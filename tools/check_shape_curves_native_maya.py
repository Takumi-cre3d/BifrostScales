"""Validate shape curves through the installed Maya/Bifrost product path."""

from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import time

import maya.standalone

_INITIALIZED_HERE = os.environ.get("BIFROST_SCALES_MAYA_INITIALIZED") != "1"
if _INITIALIZED_HERE:
    maya.standalone.initialize(name="python")
from maya import cmds

cmds.loadPlugin("bifrostGraph", quiet=True)
module_root = Path(cmds.moduleInfo(path=True, moduleName="BifrostScales"))
sys.path.insert(0, str(module_root / "scripts"))

from bifrost_scales.backend import NativeMayaBackend
from bifrost_scales.scheduler import ChangeCategory, PreviewMode, PreviewRequest
from bifrost_scales.settings import ScaleSettings


def request(settings: ScaleSettings, revision: int) -> PreviewRequest:
    return PreviewRequest(
        revision=revision,
        mode=PreviewMode.SETTLED,
        categories=frozenset({ChangeCategory.SHAPE}),
        scope=ChangeCategory.SHAPE,
        snapshot=settings.to_mapping(),
        created_at=time.monotonic(),
    )


def main() -> int:
    cmds.file(new=True, force=True)
    target = cmds.polyPlane(width=4.0, height=4.0, subdivisionsX=4, subdivisionsY=4)[0]
    backend = NativeMayaBackend()
    neutral = ScaleSettings(
        target_count=24,
        interactive_budget=24,
        settled_budget=24,
        random_size=0.0,
        random_rotation_degrees=0.0,
        cell_mode="cards",
    )
    binding = None
    try:
        binding, first = backend.create_system_with_preview(target, neutral)
        edited = replace(
            neutral,
            width_curve=((0.0, 1.0), (1.0, 0.5)),
            profile_curve=((0.0, 1.0), (1.0, 2.0)),
        )
        second = backend.apply(request(edited, 2))
        assert first.scale_count == second.scale_count > 0
        assert first.vertex_count == second.vertex_count > 0
        assert first.face_count == second.face_count > 0
        assert second.native_execution_counter_after > first.native_execution_counter_after
        stored = backend.read_settings()
        assert stored.width_curve == edited.width_curve
        assert stored.profile_curve == edited.profile_curve
        payload = json.loads(cmds.getAttr(backend.native_graph() + ".payload_json"))
        assert payload["settings"]["width_curve"] == [[0.0, 1.0], [1.0, 0.5]]
        assert payload["settings"]["profile_curve"] == [[0.0, 1.0], [1.0, 2.0]]
        status = backend.native_status()
        assert status.ready and status.native_behavior_contract_valid
        from bifrost_scales.sculpt_surface import normalize_surface
        from bifrost_scales.settings import ScaleTypeSettings
        deltas = [(0.0, 0.0, 0.0)] * 81
        deltas[40] = (1.0, -0.25, 0.6)
        surface = normalize_surface(dict(schema="vector-surface/1", resolution=8, deltas=deltas))
        sculpt = replace(neutral, sculpt_surface=surface)
        third = backend.apply(request(sculpt, 3))
        assert third.scale_count == first.scale_count
        assert third.vertex_count > first.vertex_count
        assert backend.read_settings().sculpt_surface == surface
        dense = backend.apply(request(replace(sculpt, sculpt_settled_resolution=16), 4))
        assert dense.vertex_count > third.vertex_count
        typed = replace(neutral, scale_types=(ScaleTypeSettings(sculpt_surface=surface),))
        fifth = backend.apply(request(typed, 5))
        assert fifth.vertex_count == third.vertex_count
        assert backend.read_settings().scale_types[0].sculpt_surface == surface
        restored = backend.apply(request(neutral, 6))
        assert restored.vertex_count == first.vertex_count
        assert restored.face_count == first.face_count
        full_surface = normalize_surface(dict(surface, schema="vector-surface/2"))
        full = backend.apply(request(replace(neutral, sculpt_surface=full_surface), 7))
        assert full.vertex_count == full.scale_count*81
        assert full.face_count == full.scale_count*64
        no_growth = backend.apply(request(replace(neutral, sculpt_surface=full_surface, cell_growth=0., cell_shape_divisions=6), 8))
        assert no_growth.vertex_count == full.vertex_count and no_growth.face_count == full.face_count
        assert backend.read_settings().sculpt_surface == full_surface
        pinned_surface = normalize_surface(dict(surface, schema="vector-surface/3"))
        pinned = backend.apply(request(replace(neutral, sculpt_surface=pinned_surface, normal_offset=.001), 9))
        assert pinned.scale_count == full.scale_count
        assert pinned.vertex_count > full.vertex_count
        assert backend.read_settings().normal_offset == .001
        typed_pinned = replace(neutral, normal_offset=.001, scale_types=(ScaleTypeSettings(sculpt_surface=pinned_surface, offset=.002),))
        typed_result = backend.apply(request(typed_pinned, 10))
        assert typed_result.vertex_count == pinned.vertex_count
        assert backend.read_settings().scale_types[0].offset == .002
        print("Vector surface: legacy / v2 / pinned boundary / Global and Type thickness PASS", flush=True)
        print(
            json.dumps(
                {
                    "ready": status.ready,
                    "behavior": status.native_behavior_contract_expected,
                    "scales": second.scale_count,
                    "points": second.vertex_count,
                    "faces": second.face_count,
                    "execution": [
                        first.native_execution_counter_after,
                        second.native_execution_counter_after,
                    ],
                },
                sort_keys=True,
            )
        )
        return 0
    finally:
        if binding is not None:
            backend.delete_system()
        if cmds.objExists(target):
            cmds.delete(target)


if __name__ == "__main__":
    try:
        exit_code = main()
    finally:
        if _INITIALIZED_HERE:
            maya.standalone.uninitialize()
    if _INITIALIZED_HERE:
        raise SystemExit(exit_code)
    if exit_code:
        raise RuntimeError("Shape curve product-path check failed")
