"""Audit the product runtime after removal of the Python reference generator."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "BifrostScales" / "scripts" / "bifrost_scales"
SCHEMA = "bifrost-scales/native-only-runtime-audit/1"
REMOVED_MODULES = (
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
)


def _relative_import_targets(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level and node.module:
            result.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("bifrost_scales."):
                    result.add(alias.name.split(".", 1)[1].split(".", 1)[0])
    return result


def audit(root: Path = ROOT) -> dict[str, object]:
    package = root / "BifrostScales" / "scripts" / "bifrost_scales"
    backend = (package / "backend.py").read_text(encoding="utf-8")
    ui = (package / "ui.py").read_text(encoding="utf-8")
    init = (package / "__init__.py").read_text(encoding="utf-8")
    scene = (package / "scene.py").read_text(encoding="utf-8")
    diagnostics = (package / "diagnostics.py").read_text(encoding="utf-8")

    imported_removed: dict[str, list[str]] = {}
    for path in package.glob("*.py"):
        hits = sorted(_relative_import_targets(path).intersection(REMOVED_MODULES))
        if hits:
            imported_removed[path.name] = hits

    checks = {
        "removed_modules_absent": all(
            not (package / (name + ".py")).exists() for name in REMOVED_MODULES
        ),
        "removed_modules_not_imported": not imported_removed,
        "native_backend_only": (
            "class NativeMayaBackend" in backend
            and 'PREVIEW_BACKENDS = ("native",)' in backend
            and 'return "native"' in backend
        ),
        "python_backend_rejected": "Python Reference preview was removed" in backend,
        "create_is_transactional_native_preview": (
            "def create_system_with_preview" in backend
            and "binding = self.create_system" in backend
            and "report = self.apply" in backend
            and "self.delete_system()" in backend
        ),
        "create_button_calls_native_transaction": (
            "選択メッシュから新規作成（Bifrost Previewまで）" in ui
            and "create_system_with_preview" in ui
        ),
        "backend_selector_removed": all(
            token not in ui
            for token in (
                "preview_backend_combo",
                "_preview_backend_changed",
                "Python Reference Backend",
            )
        ),
        "python_final_and_bake_removed": all(
            token not in backend + ui + scene
            for token in (
                "def generate_final",
                "def bake_preview",
                "_final_and_bake",
                "final_and_bake_button",
            )
        ),
        "public_python_smoke_removed": (
            "run_smoke_test" not in init and "maya_smoke" not in init
        ),
        "native_smoke_retained": "run_native_smoke_test" in init,
        "native_only_diagnostics": (
            '"engine": "native_bifrost_only"' in diagnostics
            and '"python_reference_runtime": False' in diagnostics
        ),
        "world_mesh_host_boundary_retained": (
            "maya-dg-worldMesh" in (package / "native_backend.py").read_text(encoding="utf-8")
        ),
    }
    return {
        "schema": SCHEMA,
        "product_version": "0.10.8",
        "removed_modules": list(REMOVED_MODULES),
        "imported_removed_modules": imported_removed,
        "checks": checks,
        "passed": sum(bool(value) for value in checks.values()),
        "total": len(checks),
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
        "Native-only runtime audit: {} ({}/{})".format(
            "PASS" if report["success"] else "FAIL",
            report["passed"],
            report["total"],
        )
    )
    if not report["success"]:
        for name, passed in report["checks"].items():
            if not passed:
                print("- " + name)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
