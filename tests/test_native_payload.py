import json

import pytest

from bifrost_scales.guides import GuideData, GuideKind, GuideSet
from bifrost_scales.native_payload import (
    NATIVE_PAYLOAD_SCHEMA,
    build_native_payload,
    validate_native_payload,
)
from bifrost_scales.settings import ScaleSettings


def test_native_payload_is_deterministic_compact_and_complete():
    settings = ScaleSettings(target_count=73, tip_offset=0.25)
    guides = GuideSet(
        (
            GuideData(
                guide_id="flow_a",
                name="Flow A",
                kind=GuideKind.FLOW_CURVE,
                points=((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
                group_id="group_primary",
                center_alignment=0.2,
                cell_anisotropy=0.75,
                use_density=True,
                use_direction=True,
            ),
        )
    )
    first = build_native_payload(settings, guides, mode="settled")
    second = build_native_payload(settings, guides, mode="settled")
    assert first == second
    assert "\n" not in first
    assert ": " not in first
    assert ", " not in first
    payload = validate_native_payload(first)
    assert payload["schema"] == NATIVE_PAYLOAD_SCHEMA
    assert payload["mode"] == "settled"
    assert payload["settings"]["target_count"] == 73
    assert payload["settings"]["tip_offset"] == 0.25
    assert payload["guides"][0]["guide_id"] == "flow_a"
    assert payload["guides"][0]["group_id"] == "group_primary"
    assert payload["guides"][0]["center_alignment"] == 0.2
    assert payload["guides"][0]["cell_anisotropy"] == 0.75
    assert payload["guides"][0]["use_density"] is True
    assert payload["guides"][0]["use_direction"] is True
    assert json.loads(first) == payload


def test_native_payload_rejects_unknown_mode_and_envelope():
    with pytest.raises(ValueError):
        build_native_payload(ScaleSettings(), mode="preview")
    with pytest.raises(ValueError):
        validate_native_payload("{}")



def test_native_payload_expands_transient_symmetry_guides_exactly_once():
    guide = GuideData(
        guide_id="mirror_flow",
        name="Mirror Flow",
        kind=GuideKind.FLOW_CURVE,
        points=((1.0, 0.0, -0.5), (2.0, 0.0, 0.5)),
        direction=(1.0, 0.0, 0.0),
        angle_degrees=20.0,
        symmetry_enabled=True,
        symmetry_axis="x",
        symmetry_space="world",
        symmetry_origin=(0.0, 0.0, 0.0),
        symmetry_normal=(1.0, 0.0, 0.0),
    )
    payload = validate_native_payload(
        build_native_payload(ScaleSettings(), GuideSet((guide,)), mode="settled")
    )

    assert len(payload["guides"]) == 2
    assert [item["guide_id"] for item in payload["guides"]] == [
        "mirror_flow",
        "mirror_flow",
    ]
    assert payload["guides"][0]["points"] == [[1.0, 0.0, -0.5], [2.0, 0.0, 0.5]]
    assert payload["guides"][1]["points"] == [[-1.0, 0.0, -0.5], [-2.0, 0.0, 0.5]]
    assert payload["guides"][1]["angle_degrees"] == -20.0
    assert "symmetry_enabled" not in payload["guides"][0]


def test_native_payload_does_not_duplicate_a_center_plane_guide():
    guide = GuideData(
        guide_id="center",
        name="Center",
        kind=GuideKind.DIRECTION_POINT,
        points=((0.0, 1.0, 0.0),),
        symmetry_enabled=True,
        symmetry_axis="x",
        symmetry_origin=(0.0, 0.0, 0.0),
        symmetry_normal=(1.0, 0.0, 0.0),
    )
    payload = validate_native_payload(
        build_native_payload(ScaleSettings(), GuideSet((guide,)), mode="interactive")
    )
    assert len(payload["guides"]) == 1


def test_native_payload_serializes_mask_and_resolved_symmetry_planes():
    guide = GuideData(
        guide_id="masked_mirror",
        name="Masked Mirror",
        kind=GuideKind.DENSITY_POINT,
        points=((1.0, 0.0, 0.0),),
        radius=0.4,
        use_density=False,
        use_size=False,
        use_direction=False,
        use_mask=True,
        symmetry_enabled=True,
        symmetry_axis="x",
        symmetry_origin=(0.0, 0.0, 0.0),
        symmetry_normal=(1.0, 0.0, 0.0),
    )
    payload = validate_native_payload(
        build_native_payload(ScaleSettings(), GuideSet((guide,)), mode="settled")
    )

    assert payload["guides"][0]["use_mask"] is True
    assert payload["guides"][1]["use_mask"] is True
    assert payload["symmetry_planes"] == [
        {"origin": [0.0, 0.0, 0.0], "normal": [1.0, 0.0, 0.0]}
    ]
