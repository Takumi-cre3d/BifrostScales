"""Verify that every Bifrost Scales release artifact comes from one versioned source."""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.10.8"
PREFIX = "BifrostScales_0_10_8"
INSTALLER_NAME = PREFIX + "_Standalone_Installer.py"
POST_CHECK_NAME = PREFIX + "_POST_INSTALL_CHECK.py"
SOURCE_ZIP_NAME = PREFIX + ".zip"
SCHEMA = "bifrost-scales/release-consistency-audit/2"

REMOVED_PYTHON_MODULES = (
    "adaptive.py",
    "cells.py",
    "generator.py",
    "maya_mesh.py",
    "maya_smoke.py",
    "mesh.py",
    "orientation.py",
    "relaxation.py",
    "sampling.py",
    "surface_features.py",
)


def _assignment(source: str, name: str):
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                return ast.literal_eval(node.value)
    raise KeyError(name)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _version_from_source(source: str) -> str:
    match = re.search(r'^VERSION\s*=\s*["\']([^"\']+)["\']', source, re.MULTILINE)
    return match.group(1) if match else ""


def _module_version(module_text: str) -> str:
    match = re.search(r'^\+\s+BifrostScales\s+([^\s]+)\s+', module_text, re.MULTILINE)
    return match.group(1) if match else ""


def _plugin_version(plugin_text: str) -> str:
    match = re.search(
        r'MFnPlugin\(plugin,\s*["\']Bifrost Scales["\'],\s*["\']([^"\']+)["\']',
        plugin_text,
    )
    return match.group(1) if match else ""


def _manifest_checks(archive: zipfile.ZipFile) -> tuple[bool, list[str]]:
    names = set(archive.namelist())
    errors: list[str] = []
    try:
        manifest = archive.read("SHA256SUMS.txt").decode("utf-8")
    except KeyError:
        return False, ["SHA256SUMS.txt is missing"]
    for line in manifest.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            expected, relative = line.split("  ", 1)
        except ValueError:
            errors.append("malformed checksum line: {}".format(line))
            continue
        if relative not in names:
            errors.append("checksum target missing: {}".format(relative))
            continue
        actual = _sha(archive.read(relative))
        if actual != expected:
            errors.append("checksum mismatch: {}".format(relative))
    return not errors, errors


def build_report(
    *,
    root: Path = ROOT,
    installer_path: Path | None = None,
    source_zip_path: Path | None = None,
) -> dict[str, object]:
    installer_path = installer_path or (root / INSTALLER_NAME)
    source_zip_path = source_zip_path or (root.parent / SOURCE_ZIP_NAME)
    checks: dict[str, bool] = {}
    details: dict[str, object] = {}
    errors: list[str] = []

    installer_bytes = installer_path.read_bytes()
    installer_source = installer_bytes.decode("utf-8")
    installer_version = str(_assignment(installer_source, "_VERSION"))
    payload_digest_declared = str(_assignment(installer_source, "_PAYLOAD_SHA256"))
    payload_encoded = str(_assignment(installer_source, "_PAYLOAD_B64"))
    payload = base64.b64decode(payload_encoded.encode("ascii"))
    checks["installer_version"] = installer_version == VERSION
    checks["installer_payload_digest"] = _sha(payload) == payload_digest_declared

    with zipfile.ZipFile(io.BytesIO(payload), "r") as payload_zip:
        payload_names = set(payload_zip.namelist())
        payload_version = _version_from_source(
            payload_zip.read("BifrostScales/scripts/bifrost_scales/version.py").decode("utf-8")
        )
        payload_module_version = _module_version(
            payload_zip.read("BifrostScales.mod").decode("utf-8")
        )
        payload_plugin_version = _plugin_version(
            payload_zip.read("BifrostScales/plug-ins/bifrostScalesCellPicker.py").decode("utf-8")
        )
        checks["payload_version"] = payload_version == VERSION
        checks["payload_module_version"] = payload_module_version == VERSION
        checks["payload_plugin_version"] = payload_plugin_version == VERSION
        checks["payload_contains_runtime"] = all(
            name in payload_names
            for name in (
                "BifrostScales.mod",
                "BifrostScales/scripts/bifrost_scales/version.py",
                "BifrostScales/plug-ins/bifrostScalesCellPicker.py",
            )
        )
        checks["payload_excludes_python_reference_modules"] = all(
            "BifrostScales/scripts/bifrost_scales/" + name not in payload_names
            for name in REMOVED_PYTHON_MODULES
        )

    with zipfile.ZipFile(source_zip_path, "r") as source_zip:
        names = source_zip.namelist()
        name_set = set(names)
        stale = [
            name
            for name in names
            if "/" not in name
            and name.startswith("BifrostScales_0_")
            and not name.startswith(PREFIX)
        ]
        checks["source_contains_current_installer"] = INSTALLER_NAME in name_set
        checks["source_contains_current_post_check"] = POST_CHECK_NAME in name_set
        checks["source_has_no_stale_top_level_release_artifacts"] = not stale
        details["stale_top_level_release_artifacts"] = stale
        if INSTALLER_NAME in name_set:
            checks["source_installer_matches_public"] = (
                source_zip.read(INSTALLER_NAME) == installer_bytes
            )
        else:
            checks["source_installer_matches_public"] = False

        source_version = _version_from_source(
            source_zip.read("BifrostScales/scripts/bifrost_scales/version.py").decode("utf-8")
        )
        source_module_version = _module_version(
            source_zip.read("BifrostScales.mod").decode("utf-8")
        )
        source_plugin_version = _plugin_version(
            source_zip.read("BifrostScales/plug-ins/bifrostScalesCellPicker.py").decode("utf-8")
        )
        checks["source_version"] = source_version == VERSION
        checks["source_module_version"] = source_module_version == VERSION
        checks["source_plugin_version"] = source_plugin_version == VERSION
        checks["source_excludes_python_reference_modules"] = all(
            "BifrostScales/scripts/bifrost_scales/" + name not in name_set
            for name in REMOVED_PYTHON_MODULES
        )
        manifest_ok, manifest_errors = _manifest_checks(source_zip)
        checks["source_checksum_manifest"] = manifest_ok
        errors.extend(manifest_errors)

    for name, passed in checks.items():
        if not passed:
            errors.append("failed check: {}".format(name))
    report = {
        "schema": SCHEMA,
        "product_version": VERSION,
        "success": all(checks.values()),
        "passed": sum(bool(value) for value in checks.values()),
        "total": len(checks),
        "installer": str(installer_path),
        "installer_sha256": _sha(installer_bytes),
        "source_zip": str(source_zip_path),
        "source_zip_sha256": _sha(source_zip_path.read_bytes()),
        "payload_sha256": _sha(payload),
        "checks": checks,
        "details": details,
        "errors": errors,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--installer")
    parser.add_argument("--source-zip")
    parser.add_argument("--output", default=str(ROOT / "RELEASE_CONSISTENCY_AUDIT.json"))
    args = parser.parse_args()
    root = Path(args.root).resolve()
    report = build_report(
        root=root,
        installer_path=Path(args.installer).resolve() if args.installer else None,
        source_zip_path=Path(args.source_zip).resolve() if args.source_zip else None,
    )
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        "Release consistency audit: {} ({}/{})".format(
            "PASS" if report["success"] else "FAIL",
            report["passed"],
            report["total"],
        )
    )
    if not report["success"]:
        for error in report["errors"]:
            print("- " + str(error))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
