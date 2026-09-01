from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_build_release():
    path = ROOT / "tools" / "build_release.py"
    spec = importlib.util.spec_from_file_location("bifrost_scales_build_release", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_versioned_names_share_one_current_prefix():
    module = _load_build_release()
    assert module.VERSION == "0.10.9"
    assert module.INSTALLER_NAME == "BifrostScales_0_10_9_Standalone_Installer.py"
    assert module.POST_CHECK_NAME == "BifrostScales_0_10_9_POST_INSTALL_CHECK.py"
    assert module.SOURCE_ZIP_NAME == "BifrostScales_0_10_9.zip"
    assert module._current_release_prefix() == "BifrostScales_0_10_9"


def test_post_install_check_matches_current_native_contract():
    module = _load_build_release()
    source = module._post_install_check_source()
    assert source.count(repr(module.VERSION)) >= 3
    assert "payload_schema_contract_valid" in source
    assert "native_behavior_contract_valid" in source
    assert "native_profile_schema_contract_valid" in source
    assert "high-curvature target" in source


def test_release_archives_always_use_the_canonical_module_descriptor():
    module = _load_build_release()
    encoded = module._release_file_bytes(ROOT / "BifrostScales.mod")
    assert encoded.decode("utf-8") == module.CANONICAL_MOD
    assert "BifrostScales 0.10.9 BifrostScales" in module.CANONICAL_MOD
    assert "D:/" not in module.CANONICAL_MOD


def test_release_file_bytes_normalize_text_and_preserve_binary(tmp_path):
    module = _load_build_release()
    text = tmp_path / "source.cpp"
    text.write_bytes(b"first\r\nsecond\rthird\n")
    binary = tmp_path / "operator.dll"
    binary.write_bytes(b"MZ\0\r\n")
    assert module._release_file_bytes(text) == b"first\nsecond\nthird\n"
    assert module._release_file_bytes(binary) == b"MZ\0\r\n"

def test_source_zip_filter_rejects_only_stale_top_level_release_artifacts():
    module = _load_build_release()
    assert module._is_stale_top_level_release_artifact(
        ROOT / "BifrostScales_0_9_5_Standalone_Installer.py"
    )
    assert module._is_stale_top_level_release_artifact(
        ROOT / "BifrostScales_0_9_6_POST_INSTALL_CHECK.py"
    )
    assert not module._is_stale_top_level_release_artifact(
        ROOT / "BifrostScales_0_10_9_Standalone_Installer.py"
    )
    assert not module._is_stale_top_level_release_artifact(
        ROOT / "docs" / "MIGRATION_0_9_4_TO_0_9_5_JA.md"
    )

def test_release_inputs_follow_git_manifest_and_exclude_local_files(
    tmp_path, monkeypatch
):
    module = _load_build_release()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    tracked = {
        Path("BifrostScales.mod"),
        Path("BifrostScales/scripts/bifrost_scales/version.py"),
        Path("native/src/core.cpp"),
        Path("README.md"),
    }
    monkeypatch.setattr(module, "_git_tracked_relative_paths", lambda: tracked)
    for relative in tracked:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("tracked\n", encoding="utf-8")
    ignored = tmp_path / "BifrostScales/scripts/bifrost_scales/orientation.py"
    ignored.write_text("legacy\n", encoding="utf-8")
    installer = tmp_path / module.INSTALLER_NAME
    installer.write_text("installer\n", encoding="utf-8")
    (tmp_path / module.POST_CHECK_NAME).write_text("check\n", encoding="utf-8")
    (tmp_path / "SHA256SUMS.txt").write_text("sums\n", encoding="utf-8")

    runtime_names = {name for _path, name in module._runtime_paths()}
    assert "BifrostScales/scripts/bifrost_scales/version.py" in runtime_names
    assert "BifrostScales/bifrost/native/src/core.cpp" in runtime_names
    assert "BifrostScales/scripts/bifrost_scales/orientation.py" not in runtime_names

    source_names = {name for _path, name in module._source_paths(installer)}
    assert "README.md" in source_names
    assert module.INSTALLER_NAME in source_names
    assert module.POST_CHECK_NAME in source_names
    assert "SHA256SUMS.txt" in source_names
    assert "BifrostScales/scripts/bifrost_scales/orientation.py" not in source_names

    module._write_checksums()
    checksums = (tmp_path / "SHA256SUMS.txt").read_text(encoding="utf-8")
    assert "README.md" in checksums
    assert "orientation.py" not in checksums
