from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from installer import offline_install
from tools.build_one_click_installer import OUTPUT_NAME, build_one_click_bundle


ROOT = Path(__file__).resolve().parents[1]
PACK = offline_install.PACK_NAME


def _write_bundle(root: Path) -> Path:
    payload = root / "payload"
    files = {
        "BifrostScales.mod": b"+ BifrostScales 0.10.9 BifrostScales\n",
        "BifrostScales/scripts/bifrost_scales/version.py": b'VERSION = "0.10.9"\n',
        "BifrostScales/scripts/bifrost_scales/ui.py": b"UI = True\n",
        "BifrostScales/bifrost/pack/{}/BifrostScalesPackConfig.json".format(PACK): b"{}\n",
        "BifrostScales/bifrost/pack/{}/lib/BifrostScalesOps.dll".format(PACK): b"native-dll",
        "BifrostScales/bifrost/pack/{}/metadata/manifest.bifrost-scales.json".format(PACK): (
            json.dumps(
                {
                    "version": "0.10.9",
                    "native_payload_schema": "bifrost-scales/native-payload/10",
                    "native_profile_schema": "bifrost-scales/native-profile/11",
                }
            ).encode("utf-8")
        ),
    }
    for relative, data in files.items():
        path = payload / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    manifest = {
        "schema": "bifrost-scales/one-click-payload/1",
        "version": "0.10.9",
        "files": {
            relative: hashlib.sha256(data).hexdigest()
            for relative, data in files.items()
        },
    }
    (root / "payload_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return root


def test_offline_install_is_verified_transactional_and_idempotent(tmp_path):
    bundle = _write_bundle(tmp_path / "bundle")
    modules = tmp_path / "maya" / "modules"
    old_package = modules / "BifrostScales"
    old_package.mkdir(parents=True)
    (old_package / "old.txt").write_text("old", encoding="utf-8")
    old_mod = modules / "BifrostScales.mod"
    old_mod.write_text("old module", encoding="utf-8")

    first = offline_install.install(
        modules,
        skip_host_checks=True,
        bundle_root=bundle,
    )
    installed = modules / "BifrostScales"
    assert (installed / "scripts" / "bifrost_scales" / "ui.py").is_file()
    assert Path(first["backup_package"]).joinpath("old.txt").read_text() == "old"
    assert Path(first["backup_module"]).read_text() == "old module"
    mod_text = old_mod.read_text(encoding="utf-8")
    assert "BIFROST_LIB_CONFIG_FILES += " in mod_text
    assert (installed / "bifrost" / "pack" / PACK).as_posix() in mod_text

    second = offline_install.install(
        modules,
        skip_host_checks=True,
        bundle_root=bundle,
    )
    assert Path(second["backup_package"]).is_dir()
    assert Path(second["backup_module"]).is_file()
    assert second["verified_files"] == 6


def test_offline_install_rejects_unlisted_payload_file(tmp_path):
    bundle = _write_bundle(tmp_path / "bundle")
    extra = bundle / "payload" / "BifrostScales" / "unexpected.py"
    extra.write_text("unexpected", encoding="utf-8")
    with pytest.raises(offline_install.InstallError, match="ファイル一覧"):
        offline_install.install(
            tmp_path / "maya" / "modules",
            skip_host_checks=True,
            bundle_root=bundle,
        )


def test_offline_install_rejects_tampering_before_touching_existing_install(tmp_path):
    bundle = _write_bundle(tmp_path / "bundle")
    tampered = bundle / "payload" / "BifrostScales" / "scripts" / "bifrost_scales" / "ui.py"
    tampered.write_text("tampered", encoding="utf-8")
    modules = tmp_path / "maya" / "modules"
    package = modules / "BifrostScales"
    package.mkdir(parents=True)
    marker = package / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(offline_install.InstallError, match="SHA-256"):
        offline_install.install(
            modules,
            skip_host_checks=True,
            bundle_root=bundle,
        )
    assert marker.read_text(encoding="utf-8") == "keep"


def test_offline_install_rolls_back_when_post_copy_verification_fails(
    tmp_path, monkeypatch
):
    bundle = _write_bundle(tmp_path / "bundle")
    modules = tmp_path / "maya" / "modules"
    package = modules / "BifrostScales"
    package.mkdir(parents=True)
    (package / "keep.txt").write_text("keep", encoding="utf-8")
    module_file = modules / "BifrostScales.mod"
    module_file.write_text("keep module", encoding="utf-8")

    def fail_verification(*_args, **_kwargs):
        raise offline_install.InstallError("forced verification failure")

    monkeypatch.setattr(
        offline_install, "_verify_installed_files", fail_verification
    )
    with pytest.raises(offline_install.InstallError, match="forced"):
        offline_install.install(
            modules,
            skip_host_checks=True,
            bundle_root=bundle,
        )
    assert (package / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert module_file.read_text(encoding="utf-8") == "keep module"


def test_offline_uninstall_is_recoverable_and_idempotent(tmp_path):
    modules = tmp_path / "maya" / "modules"
    package = modules / "BifrostScales"
    package.mkdir(parents=True)
    (package / "keep.txt").write_text("installed", encoding="utf-8")
    module_file = modules / "BifrostScales.mod"
    module_file.write_text("installed module", encoding="utf-8")

    first = offline_install.uninstall(modules, skip_host_checks=True)
    assert first["removed"] is True
    assert not package.exists()
    assert not module_file.exists()
    assert Path(first["recovery_package"]).joinpath("keep.txt").read_text() == "installed"
    assert Path(first["recovery_module"]).read_text() == "installed module"

    second = offline_install.uninstall(modules, skip_host_checks=True)
    assert second["removed"] is False


def _write_builder_source(root: Path) -> None:
    installer_root = root / "installer"
    installer_root.mkdir(parents=True)
    for name in (
        "Install_BifrostScales.cmd",
        "Uninstall_BifrostScales.cmd",
        "offline_install.py",
        "README_JA.txt",
    ):
        shutil.copy2(ROOT / "installer" / name, installer_root / name)

    package = root / "BifrostScales"
    (package / "scripts" / "bifrost_scales").mkdir(parents=True)
    (package / "scripts" / "bifrost_scales" / "version.py").write_text(
        'VERSION = "0.10.9"\n', encoding="utf-8"
    )
    (package / "scripts" / "bifrost_scales" / "adaptive.py").write_text(
        "retired = True\n", encoding="utf-8"
    )
    pack = package / "bifrost" / "pack" / PACK
    required = {
        "BifrostScalesPackConfig.json": b"{}\n",
        "lib/BifrostScalesOps.dll": b"native-dll",
        "json/BifrostScales/operators/bifrost_scales_nodedef.json": b"{}\n",
        "json/BifrostScales/graphs/BifrostScales_native_scales_v4_graph.json": b"{}\n",
        "metadata/manifest.bifrost-scales.json": json.dumps(
            {
                "version": "0.10.9",
                "native_payload_schema": "bifrost-scales/native-payload/10",
                "native_profile_schema": "bifrost-scales/native-profile/11",
            }
        ).encode("utf-8"),
    }
    for relative, data in required.items():
        path = pack / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def test_bundle_builder_is_deterministic_native_and_machine_independent(tmp_path):
    source = tmp_path / "source"
    _write_builder_source(source)
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    report = build_one_click_bundle(source, first)
    build_one_click_bundle(source, second)

    assert first.read_bytes() == second.read_bytes()
    assert OUTPUT_NAME == (
        "BifrostScales_0_10_9_Beta_OneClick_Installer.zip"
    )
    assert report["sha256"] == hashlib.sha256(first.read_bytes()).hexdigest()
    with zipfile.ZipFile(first, "r") as archive:
        names = set(archive.namelist())
        assert "Install_BifrostScales.cmd" in names
        assert "Uninstall_BifrostScales.cmd" in names
        assert "installer/offline_install.py" in names
        assert "payload/BifrostScales/bifrost/pack/{}/lib/BifrostScalesOps.dll".format(PACK) in names
        assert "payload/BifrostScales/scripts/bifrost_scales/adaptive.py" not in names
        module_text = archive.read("payload/BifrostScales.mod").decode("utf-8")
        assert "D:/" not in module_text
        manifest = json.loads(archive.read("payload_manifest.json"))
        assert manifest["release_channel"] == "beta"
        dll_name = "BifrostScales/bifrost/pack/{}/lib/BifrostScalesOps.dll".format(PACK)
        assert manifest["files"][dll_name] == hashlib.sha256(b"native-dll").hexdigest()


def test_launcher_uses_mayapy_and_blocks_running_maya():
    launcher = (ROOT / "installer" / "Install_BifrostScales.cmd").read_text(
        encoding="utf-8"
    )
    assert "Maya2026\\bin\\mayapy.exe" in launcher
    assert "%MAYA_LOCATION%\\bin\\mayapy.exe" in launcher
    assert "EnableDelayedExpansion" in launcher
    assert "INSTALL_RESULT=!ERRORLEVEL!" in launcher
    assert "BIFROST_SCALES_INSTALLER_NO_PAUSE" in launcher
    assert 'tasklist /FI "IMAGENAME eq maya.exe"' in launcher
    assert "offline_install.py" in launcher
    assert "--uninstall" in launcher
    uninstaller = (ROOT / "installer" / "Uninstall_BifrostScales.cmd").read_text(
        encoding="utf-8"
    )
    assert "Install_BifrostScales.cmd" in uninstaller
    assert "--uninstall" in uninstaller
