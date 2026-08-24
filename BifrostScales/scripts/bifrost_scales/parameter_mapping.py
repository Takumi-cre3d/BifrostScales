"""Host-independent slider mapping helpers."""

from __future__ import annotations

import math


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(float(minimum), min(float(maximum), float(value)))


def value_to_normalized(
    value: float,
    minimum: float,
    maximum: float,
    mapping: str = "linear",
) -> float:
    minimum = float(minimum)
    maximum = float(maximum)
    value = clamp(value, minimum, maximum)
    if maximum <= minimum:
        return 0.0
    if mapping == "log":
        if minimum <= 0.0:
            raise ValueError("Logarithmic slider minimum must be positive")
        return (math.log(value) - math.log(minimum)) / (
            math.log(maximum) - math.log(minimum)
        )
    return (value - minimum) / (maximum - minimum)


def normalized_to_value(
    normalized: float,
    minimum: float,
    maximum: float,
    mapping: str = "linear",
) -> float:
    normalized = clamp(normalized, 0.0, 1.0)
    minimum = float(minimum)
    maximum = float(maximum)
    if mapping == "log":
        if minimum <= 0.0:
            raise ValueError("Logarithmic slider minimum must be positive")
        return math.exp(
            math.log(minimum)
            + normalized * (math.log(maximum) - math.log(minimum))
        )
    return minimum + normalized * (maximum - minimum)
