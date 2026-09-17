from bifrost_scales.shape_curves import (
    NEUTRAL_SHAPE_CURVE,
    normalize_shape_curve,
    sample_shape_curve,
)
from bifrost_scales.settings import ScaleSettings


def test_shape_curve_contract_and_legacy_defaults():
    curve = normalize_shape_curve(
        ((-1.0, 0.0), (0.5, 9.0), (0.5, 2.0), (2.0, -9.0)),
        0.05,
        4.0,
    )
    assert curve == ((0.0, 0.05), (0.5, 2.0), (1.0, 0.05))
    assert sample_shape_curve(curve, 0.25) == 1.025
    assert normalize_shape_curve("invalid", 0.05, 4.0) == NEUTRAL_SHAPE_CURVE

    legacy = ScaleSettings.from_json(
        '{"schema":"bifrost-scales/5","settings":{"curvature":0.7}}'
    )
    assert legacy.width_curve == NEUTRAL_SHAPE_CURVE
    assert legacy.profile_curve == NEUTRAL_SHAPE_CURVE
    assert ScaleSettings.from_json(legacy.to_json()) == legacy
