"""Slider + numeric editor controls for interactive parameter editing."""

from __future__ import annotations

from typing import Any

from .qt_compat import QtCore, QtWidgets

_SLIDER_STEPS = 2000


from .parameter_mapping import clamp, normalized_to_value, value_to_normalized


class FloatParameterControl(QtWidgets.QWidget):
    valueChanged = QtCore.Signal(float)
    interactionStarted = QtCore.Signal()
    interactionFinished = QtCore.Signal()

    def __init__(
        self,
        minimum: float,
        maximum: float,
        value: float,
        decimals: int = 3,
        single_step: float = 0.01,
        suffix: str = "",
        mapping: str = "linear",
        slider_minimum: float | None = None,
        slider_maximum: float | None = None,
        parent: Any | None = None,
    ) -> None:
        super().__init__(parent)
        self._mapping = str(mapping)
        self._slider_minimum = float(
            minimum if slider_minimum is None else slider_minimum
        )
        self._slider_maximum = float(
            maximum if slider_maximum is None else slider_maximum
        )
        self._syncing = False

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setRange(0, _SLIDER_STEPS)
        self.slider.setTracking(True)
        self.spin = QtWidgets.QDoubleSpinBox()
        self.spin.setRange(float(minimum), float(maximum))
        self.spin.setDecimals(int(decimals))
        self.spin.setSingleStep(float(single_step))
        self.spin.setKeyboardTracking(True)
        if suffix:
            self.spin.setSuffix(str(suffix))
        self.spin.setMinimumWidth(112)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.spin)

        self.slider.sliderPressed.connect(self.interactionStarted)
        self.slider.sliderReleased.connect(self.interactionFinished)
        self.slider.valueChanged.connect(self._slider_changed)
        self.spin.valueChanged.connect(self._spin_changed)
        self.spin.editingFinished.connect(self.interactionFinished)
        self.setValue(value)

    def value(self) -> float:
        return float(self.spin.value())

    def setValue(self, value: float) -> None:  # noqa: N802 - Qt naming
        clamped = clamp(value, self.spin.minimum(), self.spin.maximum())
        self._syncing = True
        try:
            self.spin.setValue(clamped)
            self.slider.setValue(self._slider_position(clamped))
        finally:
            self._syncing = False

    def setKeyboardTracking(self, enabled: bool) -> None:  # noqa: N802
        self.spin.setKeyboardTracking(bool(enabled))

    def setDecimals(self, decimals: int) -> None:  # noqa: N802
        self.spin.setDecimals(int(decimals))

    def setSingleStep(self, value: float) -> None:  # noqa: N802
        self.spin.setSingleStep(float(value))

    def setSuffix(self, value: str) -> None:  # noqa: N802
        self.spin.setSuffix(str(value))

    def _slider_position(self, value: float) -> int:
        normalized = value_to_normalized(
            clamp(value, self._slider_minimum, self._slider_maximum),
            self._slider_minimum,
            self._slider_maximum,
            self._mapping,
        )
        return int(round(normalized * _SLIDER_STEPS))

    @QtCore.Slot(int)
    def _slider_changed(self, position: int) -> None:
        if self._syncing:
            return
        value = normalized_to_value(
            float(position) / float(_SLIDER_STEPS),
            self._slider_minimum,
            self._slider_maximum,
            self._mapping,
        )
        self._syncing = True
        try:
            self.spin.setValue(value)
            actual = float(self.spin.value())
        finally:
            self._syncing = False
        self.valueChanged.emit(actual)

    @QtCore.Slot(float)
    def _spin_changed(self, value: float) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            self.slider.setValue(self._slider_position(float(value)))
        finally:
            self._syncing = False
        self.valueChanged.emit(float(value))


class IntParameterControl(QtWidgets.QWidget):
    valueChanged = QtCore.Signal(int)
    interactionStarted = QtCore.Signal()
    interactionFinished = QtCore.Signal()

    def __init__(
        self,
        minimum: int,
        maximum: int,
        value: int,
        single_step: int = 1,
        suffix: str = "",
        parent: Any | None = None,
    ) -> None:
        super().__init__(parent)
        self._syncing = False
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setRange(int(minimum), int(maximum))
        self.slider.setSingleStep(max(1, int(single_step)))
        self.slider.setTracking(True)
        self.spin = QtWidgets.QSpinBox()
        self.spin.setRange(int(minimum), int(maximum))
        self.spin.setSingleStep(max(1, int(single_step)))
        self.spin.setKeyboardTracking(True)
        if suffix:
            self.spin.setSuffix(str(suffix))
        self.spin.setMinimumWidth(112)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.spin)

        self.slider.sliderPressed.connect(self.interactionStarted)
        self.slider.sliderReleased.connect(self.interactionFinished)
        self.slider.valueChanged.connect(self._slider_changed)
        self.spin.valueChanged.connect(self._spin_changed)
        self.spin.editingFinished.connect(self.interactionFinished)
        self.setValue(value)

    def value(self) -> int:
        return int(self.spin.value())

    def setValue(self, value: int) -> None:  # noqa: N802
        clamped = max(self.spin.minimum(), min(self.spin.maximum(), int(value)))
        self._syncing = True
        try:
            self.spin.setValue(clamped)
            self.slider.setValue(clamped)
        finally:
            self._syncing = False

    def setKeyboardTracking(self, enabled: bool) -> None:  # noqa: N802
        self.spin.setKeyboardTracking(bool(enabled))

    @QtCore.Slot(int)
    def _slider_changed(self, value: int) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            self.spin.setValue(int(value))
        finally:
            self._syncing = False
        self.valueChanged.emit(int(value))

    @QtCore.Slot(int)
    def _spin_changed(self, value: int) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            self.slider.setValue(int(value))
        finally:
            self._syncing = False
        self.valueChanged.emit(int(value))
