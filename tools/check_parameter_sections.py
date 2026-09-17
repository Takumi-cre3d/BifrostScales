"""Check Global parameter disclosure and dependency states with Maya's Qt."""

from pathlib import Path
from types import MethodType, SimpleNamespace
import sys

if "--installed" not in sys.argv:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "BifrostScales/scripts"))

from bifrost_scales.qt_compat import QtWidgets
from bifrost_scales.ui import BifrostScalesWindow


def main() -> int:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = QtWidgets.QWidget()
    form = QtWidgets.QFormLayout(panel)
    host = SimpleNamespace(
        relax_iterations=QtWidgets.QSpinBox(),
        relax_strength=QtWidgets.QDoubleSpinBox(),
        direction_relax_iterations=QtWidgets.QSpinBox(),
        direction_relax_strength=QtWidgets.QDoubleSpinBox(),
        cell_project_to_surface=QtWidgets.QCheckBox(),
        cell_projection_rings=QtWidgets.QSpinBox(),
    )
    for label, field in (
        ("Density iterations", host.relax_iterations),
        ("Density strength", host.relax_strength),
        ("Direction iterations", host.direction_relax_iterations),
        ("Direction strength", host.direction_relax_strength),
        ("Project", host.cell_project_to_surface),
        ("Projection rings", host.cell_projection_rings),
    ):
        form.addRow(label, field)
    host._advanced_parameter_rows = tuple(
        (form, field)
        for field in (
            host.relax_iterations,
            host.relax_strength,
            host.direction_relax_iterations,
            host.direction_relax_strength,
            host.cell_project_to_surface,
            host.cell_projection_rings,
        )
    )
    host._set_advanced_parameters_visible = MethodType(
        BifrostScalesWindow._set_advanced_parameters_visible, host
    )
    host._sync_parameter_dependencies = MethodType(
        BifrostScalesWindow._sync_parameter_dependencies, host
    )

    host._set_advanced_parameters_visible(False)
    assert all(field.isHidden() for _layout, field in host._advanced_parameter_rows)
    assert all(
        form.labelForField(field).isHidden()
        for _layout, field in host._advanced_parameter_rows
    )
    host._set_advanced_parameters_visible(True)
    assert all(not field.isHidden() for _layout, field in host._advanced_parameter_rows)

    host.relax_iterations.setValue(0)
    host.direction_relax_iterations.setValue(0)
    host.cell_project_to_surface.setChecked(False)
    host._sync_parameter_dependencies()
    for field in (
        host.relax_strength,
        host.direction_relax_strength,
        host.cell_projection_rings,
    ):
        assert not field.isEnabled()
        assert "既定値" in field.toolTip()
        assert "影響" in field.toolTip()
        assert "無効" in field.toolTip()

    host.relax_iterations.setValue(1)
    host.direction_relax_iterations.setValue(1)
    host.cell_project_to_surface.setChecked(True)
    host._sync_parameter_dependencies()
    assert all(
        field.isEnabled()
        for field in (
            host.relax_strength,
            host.direction_relax_strength,
            host.cell_projection_rings,
        )
    )
    print("Parameter sections: disclosure/dependencies/tooltips PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
