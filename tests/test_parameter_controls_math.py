import math

from bifrost_scales.parameter_mapping import normalized_to_value, value_to_normalized


def test_linear_slider_mapping_round_trip():
    for value in (-4.0, -1.25, 0.0, 2.5, 4.0):
        normalized = value_to_normalized(value, -4.0, 4.0)
        assert 0.0 <= normalized <= 1.0
        assert math.isclose(
            normalized_to_value(normalized, -4.0, 4.0),
            value,
            rel_tol=0.0,
            abs_tol=1.0e-12,
        )


def test_log_slider_mapping_round_trip_across_scene_scales():
    for value in (1.0e-6, 1.0e-3, 0.1, 1.0, 1000.0, 1.0e6):
        normalized = value_to_normalized(value, 1.0e-6, 1.0e6, "log")
        assert math.isclose(
            normalized_to_value(normalized, 1.0e-6, 1.0e6, "log"),
            value,
            rel_tol=1.0e-12,
            abs_tol=1.0e-12,
        )
