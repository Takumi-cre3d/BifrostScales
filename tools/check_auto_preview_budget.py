"""Check Auto Preview Budget behavior with Maya's Qt implementation."""

from pathlib import Path
from types import MethodType, SimpleNamespace
import sys

if "--installed" not in sys.argv:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "BifrostScales/scripts"))

from bifrost_scales.qt_compat import QtWidgets
from bifrost_scales.ui import BifrostScalesWindow


def main() -> int:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = SimpleNamespace(
        _updating_widgets=False,
        _pending_interactive_budget=None,
        _pending_interactive_budget_reason="",
        auto_preview_budget=QtWidgets.QCheckBox(),
        interactive_budget=QtWidgets.QSpinBox(),
        settled_budget=QtWidgets.QSpinBox(),
        target_count=QtWidgets.QSpinBox(),
        auto_preview_budget_label=QtWidgets.QLabel(),
    )
    host.interactive_budget.setRange(8, 50000)
    host.interactive_budget.setValue(128)
    host.interactive_budget.setEnabled(False)
    host.settled_budget.setValue(512)
    host.target_count.setRange(1, 50000)
    host.target_count.setValue(1000)
    host.auto_preview_budget.setChecked(True)
    host._update_preview_budget_label = MethodType(
        BifrostScalesWindow._update_preview_budget_label, host
    )
    host._update_auto_preview_budget = MethodType(
        BifrostScalesWindow._update_auto_preview_budget, host
    )
    host._auto_preview_budget_toggled = MethodType(
        BifrostScalesWindow._auto_preview_budget_toggled, host
    )
    host._interactive_budget_changed = MethodType(
        BifrostScalesWindow._interactive_budget_changed, host
    )
    initial = host.interactive_budget.value()
    settled = host.settled_budget.value()
    next_budget = max(8, initial // 2)
    report = SimpleNamespace(
        effective_budget=initial,
        next_interactive_budget=next_budget,
        total_ms=121.0,
    )
    host._update_auto_preview_budget("interactive", report)
    assert host.interactive_budget.value() == initial
    assert "次回 {}".format(next_budget) in host.auto_preview_budget_label.text()

    host._update_auto_preview_budget("settled", report)
    assert host.interactive_budget.value() == next_budget
    assert host.settled_budget.value() == settled
    assert "121.0 ms" in host.auto_preview_budget_label.text()

    host._update_auto_preview_budget(
        "interactive",
        SimpleNamespace(
            effective_budget=1000,
            next_interactive_budget=1000,
            total_ms=10.0,
        ),
    )
    assert "目標鱗数 1000 が上限" in host.auto_preview_budget_label.text()

    host.auto_preview_budget.setChecked(False)
    host._auto_preview_budget_toggled(False)
    assert host.interactive_budget.isEnabled()
    assert host.auto_preview_budget_label.text().startswith("Manual:")
    host.interactive_budget.setValue(next_budget + 8)
    host._interactive_budget_changed(next_budget + 8)
    assert str(next_budget + 8) in host.auto_preview_budget_label.text()
    print("Auto Preview Budget: stable interaction/manual override PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
