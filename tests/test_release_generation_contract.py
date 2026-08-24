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
    assert module.VERSION == "0.10.6"
    assert module.INSTALLER_NAME == "BifrostScales_0_10_6_Standalone_Installer.py"
    assert module.SOURCE_ZIP_NAME == "BifrostScales_0_10_6.zip"
    assert module._current_release_prefix() == "BifrostScales_0_10_6"


def test_source_zip_filter_rejects_only_stale_top_level_release_artifacts():
    module = _load_build_release()
    assert module._is_stale_top_level_release_artifact(
        ROOT / "BifrostScales_0_9_5_Standalone_Installer.py"
    )
    assert module._is_stale_top_level_release_artifact(
        ROOT / "BifrostScales_0_9_6_POST_INSTALL_CHECK.py"
    )
    assert not module._is_stale_top_level_release_artifact(
        ROOT / "BifrostScales_0_10_6_Standalone_Installer.py"
    )
    assert not module._is_stale_top_level_release_artifact(
        ROOT / "docs" / "MIGRATION_0_9_4_TO_0_9_5_JA.md"
    )
