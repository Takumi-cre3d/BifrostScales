import pytest
from bifrost_scales.sculpt_surface import normalize_surface, editor_points, capture_surface, sample_surface
from bifrost_scales.settings import ScaleSettings, ScaleTypeSettings


def test_vector_surface_roundtrip_overhang_and_boundary():
    surface = normalize_surface(dict(schema="vector-surface/1", resolution=8))
    points = editor_points(surface)
    points[40] = (1.5, 0.7, -0.8)
    authored = capture_surface(surface, points)
    assert sample_surface(authored, .5, .5) == pytest.approx((1.5, -.8, .7))
    assert editor_points(authored)[40] == pytest.approx(points[40])
    assert sample_surface(authored, 0, .5) == (0, 0, 0)
    settings = ScaleSettings.from_mapping(dict(sculpt_surface=authored, scale_types=[dict(type_id="a", sculpt_surface=authored)]))
    assert ScaleSettings.from_json(settings.to_json()) == settings
    assert settings.scale_types[0].sculpt_surface == authored
    assert ScaleSettings().sculpt_surface == {}
    assert ScaleTypeSettings().sculpt_surface == {}
    with pytest.raises(ValueError):
        normalize_surface(dict(surface, deltas=[(0, 0, 0)]))
    points[0] = (9, 0, 0)
    with pytest.raises(ValueError, match="boundary"):
        capture_surface(surface, points)


def test_full_surface_boundary_roundtrip():
    surface = normalize_surface(dict(schema="vector-surface/2", resolution=8))
    points = editor_points(surface)
    points[0] = (-.7, .4, -.3)
    points[40] = (.3, .7, -.2)
    captured = capture_surface(surface, points)
    for actual, expected in zip(editor_points(captured), points):
        assert actual == pytest.approx(expected)
    assert sample_surface(captured, 0, 0) == pytest.approx((-.2, .2, .4))
    assert ScaleSettings.from_json(ScaleSettings(sculpt_surface=captured).to_json()).sculpt_surface == captured


def test_pinned_surface_ignores_boundary_edits_without_losing_interior():
    surface = normalize_surface(dict(schema="vector-surface/3", resolution=8))
    points = editor_points(surface)
    points[0] = (-.8, .4, -.7)
    points[40] = (.8, .2, -.5)
    captured = capture_surface(surface, points)
    assert editor_points(captured)[0] == (-.5, 0., -.5)
    assert editor_points(captured)[40] == pytest.approx(points[40])
    assert sample_surface(captured, 0, 0) == (0., 0., 0.)
    settings = ScaleSettings.from_mapping(dict(normal_offset=.002, sculpt_surface=captured))
    assert ScaleSettings.from_json(settings.to_json()) == settings


def test_disk_patch_roundtrip_and_circular_boundary():
    import math
    surface = normalize_surface(dict(schema="vector-surface/3", resolution=8))
    points = editor_points(surface, disk=True)
    for j in range(9):
        for i in range(9):
            x, _, z = points[j*9+i]
            if min(i,j,8-i,8-j) == 0:
                assert math.hypot(x,z) == pytest.approx(.5)
    points[30] = tuple(a+b for a,b in zip(points[30],(.2,.3,-.1)))
    captured = capture_surface(surface,points,disk=True)
    for actual, expected in zip(editor_points(captured,disk=True),points):
        assert actual == pytest.approx(expected)
