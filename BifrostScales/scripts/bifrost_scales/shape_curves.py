"""Normalized Root-to-Tip shape curve contract."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

NEUTRAL_SHAPE_CURVE = ((0.0, 1.0), (1.0, 1.0))
MAX_SHAPE_CURVE_POINTS = 16


def normalize_shape_curve(
    values: Any,
    minimum: float,
    maximum: float,
) -> tuple[tuple[float, float], ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return NEUTRAL_SHAPE_CURVE
    points: dict[float, float] = {}
    for value in values[:MAX_SHAPE_CURVE_POINTS]:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) < 2:
            continue
        try:
            x, y = float(value[0]), float(value[1])
        except (TypeError, ValueError):
            continue
        if not math.isfinite(x) or not math.isfinite(y):
            continue
        points[max(0.0, min(1.0, x))] = max(minimum, min(maximum, y))
    normalized = sorted(points.items())
    if len(normalized) < 2:
        return NEUTRAL_SHAPE_CURVE
    normalized[0] = (0.0, normalized[0][1])
    normalized[-1] = (1.0, normalized[-1][1])
    return tuple(normalized)


def sample_shape_curve(
    points: Sequence[Sequence[float]],
    position: float,
) -> float:
    x = max(0.0, min(1.0, float(position)))
    for index in range(1, len(points)):
        right_x, right_y = points[index]
        if x <= right_x:
            left_x, left_y = points[index - 1]
            span = right_x - left_x
            if span <= 0.0:
                return float(right_y)
            amount = (x - left_x) / span
            return float(left_y) + (float(right_y) - float(left_y)) * amount
    return float(points[-1][1]) if points else 1.0
