"""Audit the Maya 2026 Cell Picker Viewport 2.0 overlay contract."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "BifrostScales" / "plug-ins" / "bifrostScalesCellPicker.py"
MANAGER = ROOT / "BifrostScales" / "scripts" / "bifrost_scales" / "cell_picker_maya.py"


def _method_calls(source: str, method_name: str) -> tuple[str, ...]:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name:
            calls: list[str] = []
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                function = child.func
                if isinstance(function, ast.Attribute):
                    if isinstance(function.value, ast.Name):
                        calls.append("{}.{}".format(function.value.id, function.attr))
                    elif isinstance(function.value, ast.Attribute):
                        calls.append(function.attr)
                elif isinstance(function, ast.Name):
                    calls.append(function.id)
            return tuple(calls)
    return ()


def build_report() -> dict[str, object]:
    plugin = PLUGIN.read_text(encoding="utf-8")
    manager = MANAGER.read_text(encoding="utf-8")
    pointer_calls = _method_calls(plugin, "doPtrMoved")
    press_calls = _method_calls(plugin, "doPress")
    feedback_calls = _method_calls(plugin, "drawFeedback")
    checks = {
        "python_api_2_marker": "maya_useNewAPI = True" in plugin,
        "python_draw_feedback_dual_dispatch_signature": (
            "event_or_draw_manager" in plugin
            and "draw_manager_or_context=None" in plugin
            and "frame_context=None" in plugin
        ),
        "live_two_argument_dispatch_supported": (
            "if frame_context is None:" in plugin
            and "draw_manager = event_or_draw_manager" in plugin
        ),
        "documented_three_argument_dispatch_supported": (
            "draw_manager = draw_manager_or_context" in plugin
        ),
        "rigid_three_argument_signature_absent": (
            "def drawFeedback(self, event, draw_manager, frame_context)" not in plugin
        ),
        "pointer_move_does_not_submit_overlay": "self._draw" not in pointer_calls,
        "pointer_press_does_not_submit_overlay": "self._draw" not in press_calls,
        "draw_feedback_is_overlay_owner": feedback_calls.count("self._draw") == 1,
        "pointer_updates_request_refresh": (
            "manager.hover_at(x, y)" in plugin
            and "scheduleRefreshAllViews" in manager
        ),
        "open_maya_render_imported": "import maya.api.OpenMayaRender as omr" in plugin,
        "explicit_mpoint_array": "om.MPointArray()" in plugin,
        "line_mesh_overlay": "draw_manager.mesh(omr.MUIDrawManager.kLines" in plugin,
        "point_mesh_overlay": "draw_manager.mesh(omr.MUIDrawManager.kPoints" in plugin,
        "xray_begin_end": (
            "draw_manager.beginDrawInXray()" in plugin
            and "draw_manager.endDrawInXray()" in plugin
        ),
        "legacy_python_list_line_strip_absent": "draw_manager.lineStrip(" not in plugin,
        "draw_error_is_separate": (
            "def report_draw_error" in manager
            and "A display failure must never destroy a valid hover or cell selection" in manager
        ),
        "draw_diagnostics": all(
            token in manager
            for token in (
                "draw_feedback_count",
                "draw_submit_count",
                "draw_primitive_count",
                "last_draw_error",
            )
        ),
        "native_contract_declared": "0.10.7-surface-follow-contract" in (
            ROOT / "BUILD_INFO.json"
        ).read_text(encoding="utf-8"),
    }
    passed = sum(bool(value) for value in checks.values())
    return {
        "schema": "bifrost-scales/cell-picker-overlay-audit/2",
        "product_version": "0.10.7",
        "success": passed == len(checks),
        "passed": passed,
        "total": len(checks),
        "checks": checks,
        "pointer_calls": pointer_calls,
        "press_calls": press_calls,
        "feedback_calls": feedback_calls,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(ROOT / "CELL_PICKER_OVERLAY_AUDIT.json"))
    args = parser.parse_args()
    report = build_report()
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        "Cell Picker overlay audit: {} ({}/{})".format(
            "PASS" if report["success"] else "FAIL",
            report["passed"],
            report["total"],
        )
    )
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
