"""Transactional offline installer used by the Windows one-click bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path


VERSION = "0.10.9"
PACK_NAME = "BifrostScalesCore-0.10.9"
PROFILE_SCHEMA = "bifrost-scales/native-profile/11"
PAYLOAD_SCHEMA = "bifrost-scales/native-payload/10"


class InstallError(RuntimeError):
    """Raised when validation or the transactional install fails."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bundle_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_modules_dir() -> Path:
    maya_app_dir = os.environ.get("MAYA_APP_DIR", "").strip()
    if maya_app_dir:
        return Path(maya_app_dir).expanduser() / "modules"
    return Path.home() / "Documents" / "maya" / "modules"


def _validated_modules_dir(modules_dir: Path | None) -> Path:
    result = (modules_dir or _default_modules_dir()).expanduser().resolve()
    if result.name.lower() != "modules":
        raise InstallError("インストール先はMayaのmodulesフォルダである必要があります。")
    return result


def _maya_running() -> bool:
    if os.name != "nt":
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq maya.exe", "/NH"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
    except OSError:
        return False
    return "maya.exe" in result.stdout.lower()


def _maya_2026_available() -> bool:
    candidates = []
    maya_location = os.environ.get("MAYA_LOCATION", "").strip()
    if maya_location:
        candidates.append(Path(maya_location) / "bin" / "maya.exe")
    candidates.append(
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Autodesk"
        / "Maya2026"
        / "bin"
        / "maya.exe"
    )
    executable = Path(sys.executable).resolve()
    if executable.name.lower() == "mayapy.exe":
        candidates.append(executable.with_name("maya.exe"))
    return any(path.is_file() for path in candidates)


def _bifrost_available() -> bool:
    explicit = os.environ.get("BIFROST_LOCATION", "").strip()
    if explicit and Path(explicit).is_dir():
        return True
    root = (
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Autodesk"
        / "Bifrost"
        / "Maya2026"
    )
    if not root.is_dir():
        return False
    return any(
        (candidate / "bifrost").is_dir()
        for candidate in root.iterdir()
        if candidate.is_dir()
    )


def _load_payload_manifest(bundle_root: Path) -> dict:
    manifest_path = bundle_root / "payload_manifest.json"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InstallError(
            "payload_manifest.jsonを読み取れません。ZIPを再展開してください。"
        ) from exc
    if data.get("schema") != "bifrost-scales/one-click-payload/1":
        raise InstallError("インストーラーのPayload manifest schemaが不正です。")
    if str(data.get("version", "")) != VERSION:
        raise InstallError("インストーラーとPayloadのバージョンが一致しません。")
    if not isinstance(data.get("files"), dict) or not data["files"]:
        raise InstallError("Payloadのファイル一覧がありません。")
    return data


def _verify_payload(bundle_root: Path) -> tuple[Path, dict]:
    payload_root = bundle_root / "payload"
    manifest = _load_payload_manifest(bundle_root)
    expected_files = set(manifest["files"])
    actual_files = set()
    for path in payload_root.rglob("*"):
        if path.is_symlink():
            raise InstallError("Payloadにsymbolic linkが含まれています。")
        if path.is_file():
            actual_files.add(path.relative_to(payload_root).as_posix())
    if actual_files != expected_files:
        unexpected = sorted(actual_files - expected_files)
        missing = sorted(expected_files - actual_files)
        raise InstallError(
            "Payloadとmanifestのファイル一覧が一致しません。extra={} missing={}".format(
                unexpected, missing
            )
        )

    for relative, expected in sorted(manifest["files"].items()):
        relative_path = Path(relative)
        if (
            relative_path.is_absolute()
            or relative_path.drive
            or ".." in relative_path.parts
        ):
            raise InstallError("Payload manifestに安全でないパスがあります。")
        source = payload_root / relative_path
        if not source.is_file():
            raise InstallError(
                "Payloadファイルが不足しています: {}".format(relative)
            )
        if _sha256(source).lower() != str(expected).lower():
            raise InstallError(
                "PayloadのSHA-256検証に失敗しました: {}".format(relative)
            )

    required = (
        "BifrostScales.mod",
        "BifrostScales/scripts/bifrost_scales/version.py",
        "BifrostScales/bifrost/pack/{}/BifrostScalesPackConfig.json".format(
            PACK_NAME
        ),
        "BifrostScales/bifrost/pack/{}/lib/BifrostScalesOps.dll".format(
            PACK_NAME
        ),
        "BifrostScales/bifrost/pack/{}/metadata/manifest.bifrost-scales.json".format(
            PACK_NAME
        ),
    )
    missing = [
        relative for relative in required if not (payload_root / relative).is_file()
    ]
    if missing:
        raise InstallError(
            "Native Packを含む必須ファイルが不足しています: {}".format(
                ", ".join(missing)
            )
        )

    native_manifest = json.loads(
        (payload_root / required[-1]).read_text(encoding="utf-8")
    )
    if str(native_manifest.get("version", "")) != VERSION:
        raise InstallError("Native Packのバージョンが一致しません。")
    if str(native_manifest.get("native_payload_schema", "")) != PAYLOAD_SCHEMA:
        raise InstallError("Native PackのPayload schemaが一致しません。")
    if str(native_manifest.get("native_profile_schema", "")) != PROFILE_SCHEMA:
        raise InstallError("Native PackのProfile schemaが一致しません。")
    return payload_root, manifest


def _installed_mod_text(pack_config: Path) -> str:
    return (
        "+ BifrostScales {} BifrostScales\n".format(VERSION)
        + "PYTHONPATH +:= scripts\n"
        + "PATH +:= bin\n"
        + "plug-ins: plug-ins\n"
        + "BIFROST_LIB_CONFIG_FILES += {}\n".format(pack_config.as_posix())
    )


def _verify_installed_files(
    destination_package: Path,
    payload_root: Path,
    manifest: dict,
) -> None:
    prefix = "BifrostScales/"
    for relative, expected in manifest["files"].items():
        if not relative.startswith(prefix):
            continue
        destination = destination_package / relative[len(prefix) :]
        source = payload_root / relative
        if not destination.is_file() or _sha256(destination) != _sha256(source):
            raise InstallError(
                "インストール後のSHA-256検証に失敗しました: {}".format(relative)
            )
        if _sha256(destination).lower() != str(expected).lower():
            raise InstallError(
                "インストール後のmanifest検証に失敗しました: {}".format(relative)
            )


def install(
    modules_dir: Path | None = None,
    *,
    skip_host_checks: bool = False,
    bundle_root: Path | None = None,
) -> dict:
    if not skip_host_checks:
        if os.name != "nt" or platform.machine().lower() not in {
            "amd64",
            "x86_64",
        }:
            raise InstallError("このインストーラーはWindows x64専用です。")
        if _maya_running():
            raise InstallError(
                "Mayaが起動しています。完全に終了してから再実行してください。"
            )
        if not _maya_2026_available():
            raise InstallError("Maya 2026が見つかりません。")
        if not _bifrost_available():
            raise InstallError("Maya 2026用Bifrostが見つかりません。")

    bundle_root = (bundle_root or _bundle_root()).resolve()
    payload_root, manifest = _verify_payload(bundle_root)
    modules_dir = _validated_modules_dir(modules_dir)
    modules_dir.mkdir(parents=True, exist_ok=True)
    destination_package = modules_dir / "BifrostScales"
    destination_mod = modules_dir / "BifrostScales.mod"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    backup_package = modules_dir / "_BifrostScales_backup_{}_{}".format(
        stamp, suffix
    )
    backup_mod = modules_dir / "_BifrostScales_mod_backup_{}_{}.mod".format(
        stamp, suffix
    )
    package_moved = False
    mod_moved = False

    try:
        if destination_package.exists():
            destination_package.rename(backup_package)
            package_moved = True
        if destination_mod.exists():
            destination_mod.rename(backup_mod)
            mod_moved = True

        shutil.copytree(payload_root / "BifrostScales", destination_package)
        shutil.copy2(payload_root / "BifrostScales.mod", destination_mod)
        pack_config = (
            destination_package
            / "bifrost"
            / "pack"
            / PACK_NAME
            / "BifrostScalesPackConfig.json"
        )
        destination_mod.write_text(
            _installed_mod_text(pack_config), encoding="utf-8", newline="\n"
        )
        _verify_installed_files(destination_package, payload_root, manifest)
    except Exception as exc:
        rollback_errors = []
        try:
            if destination_package.exists():
                shutil.rmtree(destination_package)
            if package_moved:
                backup_package.rename(destination_package)
        except Exception as rollback_error:  # pragma: no cover
            rollback_errors.append("package: {}".format(rollback_error))
        try:
            if destination_mod.exists():
                destination_mod.unlink()
            if mod_moved:
                backup_mod.rename(destination_mod)
        except Exception as rollback_error:  # pragma: no cover
            rollback_errors.append("module: {}".format(rollback_error))
        if rollback_errors:
            raise InstallError(
                "インストールとロールバックに失敗しました: {}".format(
                    " | ".join(rollback_errors)
                )
            ) from exc
        if isinstance(exc, InstallError):
            raise
        raise InstallError(
            "インストールに失敗し、以前の状態へ戻しました: {}".format(exc)
        ) from exc

    return {
        "version": VERSION,
        "modules_dir": str(modules_dir),
        "package": str(destination_package),
        "module_file": str(destination_mod),
        "backup_package": str(backup_package) if package_moved else "",
        "backup_module": str(backup_mod) if mod_moved else "",
        "verified_files": len(manifest["files"]),
    }


def uninstall(
    modules_dir: Path | None = None,
    *,
    skip_host_checks: bool = False,
) -> dict:
    if not skip_host_checks:
        if os.name != "nt" or platform.machine().lower() not in {
            "amd64",
            "x86_64",
        }:
            raise InstallError("このアンインストーラーはWindows x64専用です。")
        if _maya_running():
            raise InstallError(
                "Mayaが起動しています。完全に終了してから再実行してください。"
            )

    modules_dir = _validated_modules_dir(modules_dir)
    destination_package = modules_dir / "BifrostScales"
    destination_mod = modules_dir / "BifrostScales.mod"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    recovery_package = modules_dir / "_BifrostScales_uninstalled_{}_{}".format(
        stamp, suffix
    )
    recovery_mod = modules_dir / "_BifrostScales_mod_uninstalled_{}_{}.mod".format(
        stamp, suffix
    )
    package_moved = False
    mod_moved = False
    try:
        if destination_package.exists():
            destination_package.rename(recovery_package)
            package_moved = True
        if destination_mod.exists():
            destination_mod.rename(recovery_mod)
            mod_moved = True
    except Exception as exc:
        rollback_errors = []
        try:
            if mod_moved and not destination_mod.exists():
                recovery_mod.rename(destination_mod)
        except Exception as rollback_error:  # pragma: no cover
            rollback_errors.append("module: {}".format(rollback_error))
        try:
            if package_moved and not destination_package.exists():
                recovery_package.rename(destination_package)
        except Exception as rollback_error:  # pragma: no cover
            rollback_errors.append("package: {}".format(rollback_error))
        if rollback_errors:
            raise InstallError(
                "アンインストールとロールバックに失敗しました: {}".format(
                    " | ".join(rollback_errors)
                )
            ) from exc
        raise InstallError(
            "アンインストールに失敗し、以前の状態へ戻しました: {}".format(exc)
        ) from exc

    return {
        "version": VERSION,
        "modules_dir": str(modules_dir),
        "removed": package_moved or mod_moved,
        "recovery_package": str(recovery_package) if package_moved else "",
        "recovery_module": str(recovery_mod) if mod_moved else "",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install or uninstall Bifrost Scales for Maya 2026."
    )
    parser.add_argument("--modules-dir", type=Path)
    parser.add_argument("--bundle-root", type=Path)
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument(
        "--skip-host-checks", action="store_true", help=argparse.SUPPRESS
    )
    arguments = parser.parse_args(argv)
    try:
        if arguments.uninstall:
            report = uninstall(
                arguments.modules_dir,
                skip_host_checks=arguments.skip_host_checks,
            )
        else:
            report = install(
                arguments.modules_dir,
                skip_host_checks=arguments.skip_host_checks,
                bundle_root=arguments.bundle_root,
            )
    except InstallError as exc:
        print("ERROR: {}".format(exc), file=sys.stderr)
        return 1
    if arguments.uninstall:
        print("Bifrost Scales {} uninstallation complete.".format(report["version"]))
        if report["removed"]:
            if report["recovery_package"]:
                print("Package recovery: {}".format(report["recovery_package"]))
            if report["recovery_module"]:
                print("Module recovery: {}".format(report["recovery_module"]))
        else:
            print("Bifrost Scalesは既にアンインストールされています。")
    else:
        print("Bifrost Scales {} installation complete.".format(report["version"]))
        print("Module: {}".format(report["module_file"]))
        print("Verified files: {}".format(report["verified_files"]))
        if report["backup_package"]:
            print("Backup: {}".format(report["backup_package"]))
        print("Maya 2026を起動し、Bifrost Scalesを開いて動作確認してください。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
