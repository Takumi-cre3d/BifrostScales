"""Compare the installed product before/after with identical isolated fixtures."""
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--source", action="store_true", help="Test workspace Python against the installed native pack")
    args = parser.parse_args()
    import maya.standalone
    maya.standalone.initialize(name="python")
    try:
        from maya import cmds
        cmds.loadPlugin("bifrostGraph", quiet=True)
        root = Path(cmds.moduleInfo(path=True, moduleName="BifrostScales"))
        python_root = Path(__file__).resolve().parents[1] / "BifrostScales/scripts" if args.source else root / "scripts"
        sys.path.insert(0, str(python_root))
        from bifrost_scales.backend import NativeMayaBackend
        from bifrost_scales.scheduler import ChangeCategory, PreviewMode, PreviewRequest
        from bifrost_scales.settings import ScaleSettings
        if args.source:
            from bifrost_scales import native_backend
            # Python-only test: probe the DLL actually loaded by this Maya process,
            # not the development checkout's protected, machine-local .mod file.
            native_backend._module_root = lambda: root
        backend = NativeMayaBackend()
        target = cmds.polyPlane(width=4, height=4, subdivisionsX=4, subdivisionsY=4)[0]
        neutral = ScaleSettings(target_count=24, settled_budget=24, random_size=0,
                                random_rotation_degrees=0, cell_mode="cards")
        binding, report = backend.create_system_with_preview(target, neutral)

        def capture(report):
            payload = json.loads(cmds.getAttr(backend.native_graph()+".payload_json"))
            return dict(scales=report.scale_count, vertices=report.vertex_count,
                        faces=report.face_count, settings=payload["settings"],
                        payload_sha256=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest())

        result = {"neutral": capture(report), "installed": str(root)}
        for revision, (name, settings) in enumerate((
            ("old_manual_cap", replace(neutral, settled_budget=8)),
            ("extended", ScaleSettings.from_mapping(dict(neutral.to_mapping(),
                curvature=8, normal_offset=6, forward_offset=-5))),
            ("restored", neutral)), 2):
            request = PreviewRequest(revision=revision, mode=PreviewMode.SETTLED,
                categories=frozenset({ChangeCategory.SHAPE, ChangeCategory.DISTRIBUTION}),
                scope=ChangeCategory.DISTRIBUTION, snapshot=settings.to_mapping(),
                created_at=time.monotonic())
            result[name] = capture(backend.apply(request))
        assert result["neutral"] == result["restored"]
        assert backend.native_status().ready
        if args.baseline:
            before = json.loads(args.baseline.read_text(encoding="utf-8"))
            assert before["neutral"] == result["neutral"]
            assert result["old_manual_cap"]["scales"] == result["neutral"]["scales"]
            assert before["old_manual_cap"]["scales"] < result["old_manual_cap"]["scales"]
            for key, value in (("curvature", 8), ("normal_offset", 6), ("forward_offset", -5)):
                assert result["extended"]["settings"][key] == value
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print("Native settings comparison PASS: " + str(python_root), flush=True)
    finally:
        maya.standalone.uninitialize()


if __name__ == "__main__":
    main()
