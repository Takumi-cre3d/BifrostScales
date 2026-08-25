from bifrost_scales.settings import ScaleSettings


def test_settings_round_trip_and_clamping():
    settings = ScaleSettings.from_mapping(
        {
            "target_count": 999999,
            "interactive_budget": 999999,
            "spacing_factor": 0.01,
            "size": -1.0,
            "random_size": 2.0,
            "color_r": 4.0,
        }
    )
    assert settings.target_count == 50000
    assert settings.interactive_budget == 50000
    assert settings.spacing_factor == 0.15
    assert settings.size == 1.0e-6
    assert settings.random_size == 0.95
    assert settings.color_r == 1.0
    assert ScaleSettings.from_json(settings.to_json()) == settings


def test_mode_budgets_are_independent():
    settings = ScaleSettings(
        target_count=1000,
        interactive_budget=64,
        settled_budget=400,
    )
    assert settings.effective_count("interactive") == 64
    assert settings.effective_count("settled") == 400
    assert settings.effective_count("final") == 1000


def test_schema_one_payload_migrates_with_native_preview_defaults():
    legacy = '{"schema":"bifrost-scales/1","settings":{"target_count":42,"seed":7}}'
    settings = ScaleSettings.from_json(legacy)
    assert settings.target_count == 42
    assert settings.seed == 7
    assert settings.interactive_delay_ms == 50


def test_schema_three_scale_types_and_relax_round_trip():
    settings = ScaleSettings.from_mapping(
        {
            "relax_iterations": 7,
            "relax_strength": 0.6,
            "direction_relax_iterations": 4,
            "direction_relax_strength": 0.5,
            "inset": 0.2,
            "squash": 0.15,
            "expand": 0.3,
            "scale_types": [
                {"type_id": "classic", "name": "Classic", "enabled": True, "weight": 1.0},
                {
                    "type_id": "wide",
                    "name": "Wide",
                    "enabled": True,
                    "weight": 0.4,
                    "width_multiplier": 1.4,
                    "use_custom_color": True,
                    "color_g": 0.9,
                },
            ],
        }
    )
    restored = ScaleSettings.from_json(settings.to_json())
    assert restored == settings
    assert restored.relax_iterations == 7
    assert restored.direction_relax_iterations == 4
    assert len(restored.scale_types) == 2
    assert restored.scale_types[1].use_custom_color is True


def test_schema_two_settings_gain_relax_shape_and_scale_type_defaults():
    legacy = ScaleSettings.from_json(
        '{"schema":"bifrost-scales/2","settings":{"target_count":42,"size":0.25}}'
    )
    assert legacy.target_count == 42
    assert legacy.size == 0.25
    assert legacy.relax_iterations == 0
    assert legacy.tip_roundness > 0.0
    assert legacy.scale_types[0].enabled


def test_scale_type_mapping_clamps_values_and_repairs_duplicate_ids():
    values = {
        "scale_types": [
            {"type_id": "same", "name": "A", "enabled": True, "weight": 1.0},
            {
                "type_id": "same",
                "name": "B",
                "enabled": True,
                "weight": 2.0,
                "width_multiplier": 99.0,
                "round_sharp": -99.0,
            },
        ]
    }
    parsed = ScaleSettings.from_mapping(values)
    assert parsed.scale_types[0].type_id == "same"
    assert parsed.scale_types[1].type_id == "same_2"
    assert parsed.scale_types[1].width_multiplier == 8.0
    assert "weight" not in parsed.scale_types[1].__dict__
    assert "round_sharp" not in parsed.scale_types[1].__dict__
    assert "weight" not in parsed.to_mapping()["scale_types"][1]
    assert "round_sharp" not in parsed.to_mapping()["scale_types"][1]


def test_schema_four_cell_defaults_and_geometry_modes():
    auto = ScaleSettings.from_json(
        '{"schema":"bifrost-scales/3","settings":{"target_count":42}}'
    )
    assert auto.cell_mode == "auto"
    assert auto.geometry_kind("interactive") == "card"
    assert auto.geometry_kind("settled") == "cell"
    assert auto.geometry_kind("final") == "cell"
    assert auto.effective_cell_resolution("settled") == 10
    assert auto.effective_cell_resolution("final") == 14

    cards = ScaleSettings.from_mapping({"cell_mode": "card"})
    cells = ScaleSettings.from_mapping({"cell_mode": "cell"})
    assert cards.cell_mode == "cards"
    assert cards.geometry_kind("final") == "card"
    assert cells.cell_mode == "cells"
    assert cells.geometry_kind("interactive") == "cell"


def test_cell_settings_clamp_and_round_trip():
    settings = ScaleSettings.from_mapping(
        {
            "cell_mode": "unknown",
            "cell_growth": 9.0,
            "cell_gap": 2.0,
            "cell_collision_margin": -1.0,
            "cell_radius_multiplier": 99.0,
            "cell_direction_pair_strength": 9.0,
            "cell_direction_pair_length": 99.0,
            "cell_shape_divisions": 99,
            "cell_interactive_resolution": 2,
            "cell_settled_resolution": 99,
            "cell_projection_rings": 99,
            "cell_project_to_surface": "off",
        }
    )
    assert settings.cell_mode == "auto"
    assert settings.cell_growth == 1.0
    assert settings.cell_gap == 0.49
    assert settings.cell_collision_margin == 0.0
    assert settings.cell_radius_multiplier == 6.0
    assert not hasattr(settings, "cell_direction_pair_strength")
    assert not hasattr(settings, "cell_direction_pair_length")
    assert "cell_direction_pair_strength" not in settings.to_mapping()
    assert "cell_direction_pair_length" not in settings.to_mapping()
    assert settings.cell_shape_divisions == 6
    assert settings.cell_interactive_resolution == 4
    assert settings.cell_settled_resolution == 32
    assert settings.cell_projection_rings == 16
    assert settings.cell_project_to_surface is False
    assert ScaleSettings.from_json(settings.to_json()) == settings


def test_removed_unique_scales_from_legacy_scene_are_ignored():
    settings = ScaleSettings.from_mapping(
        {
            "target_count": 17,
            "unique_scales": [
                {
                    "cell_id": "00000000000000ab",
                    "name": "Legacy Landmark",
                    "override": {"enabled": True, "size_multiplier": 2.0},
                }
            ],
        }
    )

    assert settings.target_count == 17
    assert not hasattr(settings, "unique_scales")
    assert "unique_scales" not in settings.to_mapping()
    assert "unique_scales" not in settings.to_json()
