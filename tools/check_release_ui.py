"""Headless Maya Qt checks; does not open or modify a Maya scene."""
from pathlib import Path
import sys

if "--installed" not in sys.argv:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "BifrostScales/scripts"))
from bifrost_scales.qt_compat import QtWidgets, QtGui
from bifrost_scales import i18n
from bifrost_scales.parameter_controls import FloatParameterControl
from bifrost_scales.settings import ScaleSettings
from bifrost_scales.ui import BifrostScalesWindow, _RETIRED_SHAPE_FIELDS


def main():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    # The offscreen platform does not discover Windows fonts automatically.
    if any(arg.startswith("--screenshot=") for arg in sys.argv):
        for font in ("segoeui.ttf", "YuGothM.ttc", "seguisym.ttf"):
            QtGui.QFontDatabase.addApplicationFont("C:/Windows/Fonts/" + font)
    window = BifrostScalesWindow.__new__(BifrostScalesWindow)
    QtWidgets.QDialog.__init__(window)
    defaults = ScaleSettings()
    window._scale_types = list(defaults.scale_types)
    window._sculpt_surface = {}
    window._legacy_cell_shape = {"cell_growth": 0.85, "cell_shape_divisions": 2}
    window._retained_shape_values = {name: getattr(defaults, name) for name in _RETIRED_SHAPE_FIELDS}
    window._legacy_curves = {"width_curve": defaults.width_curve, "profile_curve": defaults.profile_curve}
    window._preview_color = (defaults.color_r, defaults.color_g, defaults.color_b)
    window._build_ui()
    for index in range(window.tabs.count()):
        assert not window.tabs.tabIcon(index).pixmap(16, 16).isNull()
    assert not window.edit_sculpt.icon().pixmap(16, 16).isNull()
    assert not window.create_mesh_button.icon().pixmap(16, 16).isNull()
    assert "Maintenance" not in [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert window.maintenance_dialog.isHidden()
    assert window.log.parentWidget() is window.maintenance_dialog
    assert not hasattr(window, "preview_now_button")
    assert not hasattr(window, "settled_budget")
    assert not hasattr(window, "cell_mode")
    assert window._snapshot()["cell_mode"] == "auto"
    assert not hasattr(window, "cell_growth")
    assert not hasattr(window, "cell_shape_divisions")
    assert not hasattr(window, "type_tip_offset")
    for name in _RETIRED_SHAPE_FIELDS:
        assert not hasattr(window, name), name
    assert not hasattr(window, "cell_interactive_resolution")
    assert not hasattr(window, "sculpt_interactive_resolution")
    window.target_count.setValue(1234)
    snapshot = window._snapshot()
    assert snapshot["settled_budget"] == 1234
    assert snapshot["cell_interactive_resolution"] == 6
    assert snapshot["sculpt_interactive_resolution"] == 4
    for field in (window.cell_settled_resolution, window.sculpt_settled_resolution,
                  window.cell_projection_rings):
        assert not field.isHidden()
        assert all(field is not advanced for _, advanced in window._advanced_parameter_rows)
    for field in (window.normal_offset, window.type_offset):
        assert field._slider_maximum == 100.0
    old_language = i18n.language()
    try:
        hint = "配置を均す強さ。既定値: 0.45 / 影響: 配置 / 均し回数が0のため無効"
        assert i18n.translate(i18n.translate(hint, "en"), "ja") == hint
        window.system_combo.addItem("全体設定", "authored-system")
        window.guide_name.setText("名前")
        before = window._snapshot()
        for locale in ("en", "ja", "en"):
            window.language_switch.setCurrentIndex(window.language_switch.findData(locale))
            window._change_language()
            assert window.tabs.tabText(0) == ("Placement & Shape" if locale == "en" else "配置・形状")
            assert window.edit_sculpt.text() == ("Sculpt Scales" if locale == "en" else "鱗をスカルプト")
            assert window.edit_type_sculpt.text() == window.edit_sculpt.text()
            assert window.edit_sculpt.property("primary") is True
            assert not hasattr(window, "create_cards_button")
            assert window.system_combo.itemText(0) == "全体設定"
            assert window.guide_name.text() == "名前"
            assert window._snapshot() == before
    finally:
        i18n.set_language(old_language)
    control = FloatParameterControl(-100, 100, 0, slider_minimum=-2, slider_maximum=2)
    emissions = []
    control.valueChanged.connect(emissions.append)
    control.spin.setValue(7)
    assert control.value() == 7 and control._slider_maximum == 7
    assert emissions == [7]
    control.setValue(-9)
    assert control._slider_minimum == -9 and emissions == [7]
    for field, value, key in ((window.curvature, 8, "curvature"),
                               (window.normal_offset, 600, "normal_offset")):
        field.spin.setValue(value)
        expected = value / 100 if key == "normal_offset" else value
        assert ScaleSettings.from_mapping(window._snapshot()).to_mapping()[key] == expected
    window.direction.spin.setValue(1000)
    assert window.direction.value() == 360
    window._update_preview_limit_warning()
    assert window.preview_limit_warning.isHidden()
    window.target_count.setValue(50000)
    window._update_preview_limit_warning()
    assert not window.preview_limit_warning.isHidden()
    window.target_count.setValue(512)
    window._update_preview_limit_warning()
    assert window.preview_limit_warning.isHidden()
    window._show_maintenance()
    assert not window.maintenance_dialog.isHidden()
    window.maintenance_dialog.hide()
    for arg in sys.argv:
        if arg.startswith("--screenshot="):
            window.system_combo.clear()
            window.direction.setValue(defaults.direction_degrees)
            window.curvature.setValue(defaults.curvature)
            window.normal_offset.setValue(defaults.normal_offset * 100)
            window.resize(760, 900)
            window.show()
            app.processEvents()
            assert window.grab().save(arg.split("=", 1)[1])
            try:
                window.language_switch.setCurrentIndex(window.language_switch.findData("ja"))
                app.processEvents()
                path = Path(arg.split("=", 1)[1])
                assert window.grab().save(str(path.with_stem(path.stem + "-ja")))
                for index in range(1, window.tabs.count()):
                    window.tabs.setCurrentIndex(index)
                    app.processEvents()
                    assert window.grab().save(str(path.with_stem(path.stem + "-ja-tab" + str(index))))
            finally:
                i18n.set_language(old_language)
    # No scene callbacks were installed, so do not call the production close handler.
    window.deleteLater()
    app.processEvents()
    print("Release UI: maintenance/log, subdivisions, budgets, translation/data isolation, numeric soft ranges PASS")


if __name__ == "__main__":
    main()
