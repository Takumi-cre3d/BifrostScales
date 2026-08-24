from pathlib import Path

from bifrost_scales.legacy_cleanup import (
    remove_legacy_installations,
    scan_legacy_installations,
)


class FakeCmds:
    def __init__(self, user_app_dir: Path):
        self.user_app_dir = user_app_dir

    def internalVar(self, userAppDir=False):
        assert userAppDir
        return str(self.user_app_dir)


def _write(path: Path, text=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_scan_and_remove_known_legacy_installations(tmp_path):
    home = tmp_path / "home"
    user_app = home / "maya" / "2026"
    modules = user_app / "modules"
    maya_scales = modules / "MayaScales"
    integration = modules / "BifrostScalesIntegration"
    _write(maya_scales / "scripts" / "maya_scales" / "__init__.py")
    _write(integration / "scripts" / "bifrost_scales_integration" / "__init__.py")
    _write(modules / "MayaScales.mod", "+ MayaScales 0.3.5 MayaScales\n")
    _write(modules / "BifrostScalesIntegration.mod", "+ BifrostScalesIntegration 0.1.0 BifrostScalesIntegration\n")
    compound = home / "Autodesk" / "Bifrost" / "Compounds" / "MayaScales"
    _write(compound / "live_points" / "live_points.json", "{}")

    fake = FakeCmds(user_app)
    candidates = scan_legacy_installations(
        cmds_module=fake,
        home=home,
        module_dirs=[modules],
    )
    paths = {Path(candidate.path) for candidate in candidates}
    assert maya_scales in paths
    assert integration in paths
    assert compound in paths

    report = remove_legacy_installations(
        cmds_module=fake,
        include_external=True,
        home=home,
        module_dirs=[modules],
    )
    assert not maya_scales.exists()
    assert not integration.exists()
    assert not compound.exists()
    assert not report.pending
    assert not report.failed


def test_external_wout_root_requires_marker_and_explicit_flag(tmp_path):
    home = tmp_path / "home"
    user_app = home / "maya" / "2026"
    modules = user_app / "modules"
    external = tmp_path / "WoutScalesBifrost-0.1.1"
    pack = external / "pack"
    _write(external / "scripts" / "wout_scales" / "__init__.py")
    _write(pack / "WoutScalesPackConfig.json", "{}")
    _write(
        modules / "WoutScales2026.mod",
        "+ WoutScales 0.1.1 {}\nBIFROST_LIB_CONFIG_FILES +:= {}\n".format(
            external,
            pack / "WoutScalesPackConfig.json",
        ),
    )
    fake = FakeCmds(user_app)
    report = remove_legacy_installations(
        cmds_module=fake,
        include_external=False,
        home=home,
        module_dirs=[modules],
    )
    assert external.exists()
    assert report.skipped
    assert not (modules / "WoutScales2026.mod").exists()
