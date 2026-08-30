"""Build the deterministic Windows one-click installer bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.10.7"
PACK_NAME = "BifrostScalesCore-0.10.7"
OUTPUT_NAME = "BifrostScales_0_10_7_OneClick_Installer.zip"
FIXED_TIME = (2026, 8, 29, 0, 0, 0)

_RETIRED_RUNTIME_MODULES = {
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
}

_CANONICAL_MOD = """+ BifrostScales 0.10.7 BifrostScales
PYTHONPATH +:= scripts
PATH +:= bin
plug-ins: plug-ins
"""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _runtime_files(source_root: Path) -> list[tuple[Path, str]]:
    package_root = source_root / "BifrostScales"
    pack_root = package_root / "bifrost" / "pack" / PACK_NAME
    required = (
        pack_root / "BifrostScalesPackConfig.json",
        pack_root / "lib" / "BifrostScalesOps.dll",
        pack_root / "json" / "BifrostScales" / "operators" / "bifrost_scales_nodedef.json",
        pack_root / "json" / "BifrostScales" / "graphs" / "BifrostScales_native_scales_v4_graph.json",
        pack_root / "metadata" / "manifest.bifrost-scales.json",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(
            "Build the Maya 2026 Native Pack before creating the one-click bundle: "
            + ", ".join(missing)
        )

    manifest = json.loads(required[-1].read_text(encoding="utf-8"))
    if str(manifest.get("version", "")) != VERSION:
        raise RuntimeError("Native Pack version does not match the installer version")
    if str(manifest.get("native_payload_schema", "")) != "bifrost-scales/native-payload/10":
        raise RuntimeError("Native Pack payload schema is incompatible")
    if str(manifest.get("native_profile_schema", "")) != "bifrost-scales/native-profile/9":
        raise RuntimeError("Native Pack profile schema is incompatible")

    result: list[tuple[Path, str]] = []
    for path in sorted(package_root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(package_root)
        parts = relative.parts
        if (
            "__pycache__" in parts
            or path.suffix.lower() in {".pyc", ".pdb", ".lib", ".exp", ".ilk"}
            or (parts and parts[0] in {"docs", "tests"})
            or (len(parts) >= 2 and parts[0] == "bifrost" and parts[1] in {"native", "out"})
            or (
                len(parts) >= 3
                and parts[0] == "scripts"
                and parts[1] == "bifrost_scales"
                and parts[2] in _RETIRED_RUNTIME_MODULES
            )
        ):
            continue
        archive_name = "BifrostScales/{}".format(relative.as_posix())
        result.append((path, archive_name))
    return result


def _write_entry(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, FIXED_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (0o100644 & 0xFFFF) << 16
    archive.writestr(info, data)


def build_one_click_bundle(
    source_root: Path = ROOT,
    output_path: Path | None = None,
) -> dict[str, object]:
    source_root = source_root.resolve()
    output_path = (output_path or source_root / "dist" / OUTPUT_NAME).resolve()
    runtime = _runtime_files(source_root)

    payload_entries: list[tuple[str, bytes]] = [
        ("BifrostScales.mod", _CANONICAL_MOD.encode("utf-8"))
    ]
    payload_entries.extend(
        (archive_name, source.read_bytes()) for source, archive_name in runtime
    )
    payload_entries.sort(key=lambda item: item[0])
    file_hashes = {
        name: _sha256_bytes(data) for name, data in payload_entries
    }
    payload_manifest = {
        "schema": "bifrost-scales/one-click-payload/1",
        "product": "Bifrost Scales",
        "version": VERSION,
        "platform": "windows-x64",
        "maya_version": 2026,
        "pack": PACK_NAME,
        "files": file_hashes,
    }

    launcher = source_root / "installer" / "Install_BifrostScales.cmd"
    installer = source_root / "installer" / "offline_install.py"
    readme = source_root / "installer" / "README_JA.txt"
    for required in (launcher, installer, readme):
        if not required.is_file():
            raise RuntimeError("One-click installer source is missing: {}".format(required))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        output_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        _write_entry(
            archive,
            "Install_BifrostScales.cmd",
            launcher.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8"),
        )
        _write_entry(archive, "README_JA.txt", readme.read_bytes())
        _write_entry(archive, "installer/offline_install.py", installer.read_bytes())
        _write_entry(
            archive,
            "payload_manifest.json",
            (json.dumps(payload_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
        for name, data in payload_entries:
            _write_entry(archive, "payload/{}".format(name), data)

    digest = _sha256_file(output_path)
    checksum_path = output_path.with_suffix(output_path.suffix + ".sha256")
    checksum_path.write_text(
        "{}  {}\n".format(digest, output_path.name),
        encoding="utf-8",
        newline="\n",
    )
    return {
        "schema": "bifrost-scales/one-click-build/1",
        "version": VERSION,
        "bundle": str(output_path),
        "sha256": digest,
        "checksum": str(checksum_path),
        "payload_files": len(payload_entries),
        "bundle_bytes": output_path.stat().st_size,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args(argv)
    report = build_one_click_bundle(arguments.source_root, arguments.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
