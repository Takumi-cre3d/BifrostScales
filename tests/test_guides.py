from dataclasses import replace

from bifrost_scales.guides import GuideData, GuideKind, GuideSet


def _density(position=(0.0, 0.0, 0.0), multiplier=4.0):
    return GuideData(
        guide_id="density_a",
        name="Density A",
        kind=GuideKind.DENSITY_POINT,
        points=(position,),
        radius=2.0,
        density_multiplier=multiplier,
        size_multiplier=1.5,
    )


def _direction(
    position=(1.0, 0.0, 0.0),
    direction=(0.0, 1.0, 0.0),
):
    return GuideData(
        guide_id="direction_a",
        name="Direction A",
        kind=GuideKind.DIRECTION_POINT,
        points=(position,),
        direction=direction,
        radius=2.0,
        strength=1.0,
    )


def test_stage_fingerprints_are_independent():
    base = GuideSet.from_iterable((_density(), _direction()))
    rotated_point = GuideSet.from_iterable(
        (_density(), _direction(direction=(0.0, 0.0, 1.0)))
    )
    moved_point = GuideSet.from_iterable(
        (_density(), _direction(position=(0.0, 0.0, 1.0)))
    )
    assert base.fingerprint("density") == moved_point.fingerprint("density")
    assert base.fingerprint("direction") == rotated_point.fingerprint("direction")
    assert base.fingerprint("direction") != moved_point.fingerprint("direction")


def test_density_and_direction_fields_are_local():
    guides = GuideSet.from_iterable((_density(), _direction()))
    near_density, near_size = guides.density_factors((0.0, 0.0, 0.0))
    far_density, far_size = guides.density_factors((10.0, 0.0, 0.0))
    assert near_density > far_density == 1.0
    assert near_size > far_size == 1.0

    guided = guides.guided_direction(
        (0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    )
    far = guides.guided_direction(
        (10.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    )
    assert guided[0] > 0.0
    assert guided[2] < 1.0
    assert far == (0.0, 0.0, 1.0)


def test_direction_point_aims_toward_its_position_from_both_sides():
    guides = GuideSet.from_iterable((_direction(position=(0.0, 0.0, 0.0)),))
    normal = (0.0, 1.0, 0.0)
    left = guides.guided_direction(
        (-0.5, 0.0, 0.0),
        normal,
        (0.0, 0.0, 1.0),
    )
    right = guides.guided_direction(
        (0.5, 0.0, 0.0),
        normal,
        (0.0, 0.0, 1.0),
    )
    assert left[0] > 0.9
    assert right[0] < -0.9
    assert abs(left[0] + right[0]) < 1.0e-12


def test_curve_guide_uses_nearest_segment_tangent():
    guide = GuideData(
        guide_id="curve",
        name="Curve",
        kind=GuideKind.DIRECTION_CURVE,
        points=((-1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 2.0)),
        radius=3.0,
    )
    distance, nearest, tangent = guide.nearest((0.0, 0.0, 0.5))
    assert distance == 0.5
    assert nearest == (0.0, 0.0, 0.0)
    assert tangent == (1.0, 0.0, 0.0)


def test_direction_curve_preserves_stroke_start_to_end_sign():
    forward = GuideData(
        guide_id="forward",
        name="Forward",
        kind=GuideKind.DIRECTION_CURVE,
        points=((-1.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        radius=3.0,
        strength=1.0,
    )
    reverse = GuideData(
        guide_id="reverse",
        name="Reverse",
        kind=GuideKind.DIRECTION_CURVE,
        points=((1.0, 0.0, 0.0), (-1.0, 0.0, 0.0)),
        radius=3.0,
        strength=1.0,
    )
    normal = (0.0, 1.0, 0.0)
    forward_result = GuideSet.from_iterable((forward,)).guided_direction(
        (0.0, 0.0, 0.0),
        normal,
        (-1.0, 0.0, 0.0),
    )
    reverse_result = GuideSet.from_iterable((reverse,)).guided_direction(
        (0.0, 0.0, 0.0),
        normal,
        (1.0, 0.0, 0.0),
    )
    assert forward_result[0] > 0.999
    assert reverse_result[0] < -0.999


def test_combined_flow_curve_controls_density_and_direction_with_independent_fingerprints():
    base_guide = GuideData(
        guide_id="flow",
        name="Flow",
        kind=GuideKind.FLOW_CURVE,
        points=((-1.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        radius=3.0,
        density_multiplier=2.5,
        strength=0.8,
    ).normalized()
    assert base_guide.affects_density
    assert not base_guide.affects_size
    assert base_guide.affects_direction

    base = GuideSet.from_iterable((base_guide,))
    density_changed = GuideSet.from_iterable(
        (
            GuideData.from_mapping(
                {
                    **base.to_mappings()[0],
                    "density_multiplier": 0.5,
                }
            ),
        )
    )
    direction_changed = GuideSet.from_iterable(
        (
            GuideData.from_mapping(
                {
                    **base.to_mappings()[0],
                    "strength": 0.2,
                }
            ),
        )
    )

    assert base.fingerprint("density") != density_changed.fingerprint("density")
    assert base.fingerprint("direction") == density_changed.fingerprint("direction")
    assert base.fingerprint("density") == direction_changed.fingerprint("density")
    # Positive-to-positive Direction Strength edits affect Orientation only.
    # Distribution changes only when the centerline is toggled through zero.
    assert base.fingerprint("distribution") == direction_changed.fingerprint(
        "distribution"
    )
    direction_disabled = GuideSet.from_iterable(
        (
            replace(base_guide, strength=0.0),
        )
    )
    assert base.fingerprint("distribution") != direction_disabled.fingerprint(
        "distribution"
    )
    assert base.fingerprint("direction") != direction_changed.fingerprint("direction")

    density, size = base.density_factors((0.0, 0.0, 0.0))
    direction, influence = base.direction_solution(
        (0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    )
    assert density > 1.0
    assert size == 1.0
    assert direction[0] > 0.5
    assert influence > 0.5


def test_combined_guide_role_flags_can_be_reassigned_without_changing_geometry_kind():
    guide = GuideData(
        guide_id="flow_roles",
        name="Flow Roles",
        kind=GuideKind.FLOW_CURVE,
        points=((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        use_density=False,
        use_size=True,
        use_direction=True,
    ).normalized()
    assert not guide.affects_density
    assert guide.affects_size
    assert guide.affects_direction
    assert guide.kind.is_curve


def test_guide_order_is_stable_and_display_names_do_not_invalidate_generation_stages():
    late = GuideData(
        guide_id="late",
        name="Late",
        kind=GuideKind.DIRECTION_POINT,
        points=((0.0, 0.0, 0.0),),
        order=5,
    )
    early = GuideData(
        guide_id="early",
        name="Early",
        kind=GuideKind.DIRECTION_POINT,
        points=((0.0, 0.0, 0.0),),
        order=1,
    )
    ordered = GuideSet.from_iterable((late, early))
    assert [item.guide_id for item in ordered.guides] == ["early", "late"]
    assert [item["order"] for item in ordered.to_mappings()] == [1, 5]

    renamed = GuideSet.from_iterable(
        (
            GuideData.from_mapping({**ordered.to_mappings()[0], "name": "Readable Name"}),
            ordered.guides[1],
        )
    )
    assert ordered.fingerprint() != renamed.fingerprint()
    assert ordered.fingerprint("density") == renamed.fingerprint("density")
    assert ordered.fingerprint("direction") == renamed.fingerprint("direction")


def test_direction_guide_order_is_part_of_the_orientation_contract():
    first = GuideData(
        guide_id="first",
        name="First",
        kind=GuideKind.DIRECTION_POINT,
        points=((0.0, 0.0, 0.0),),
        direction=(1.0, 0.0, 0.0),
        order=0,
    )
    second = GuideData(
        guide_id="second",
        name="Second",
        kind=GuideKind.DIRECTION_POINT,
        points=((0.0, 0.0, 0.0),),
        direction=(0.0, 0.0, 1.0),
        order=1,
    )
    forward = GuideSet.from_iterable((first, second))
    reverse = GuideSet.from_iterable(
        (
            GuideData.from_mapping({**forward.to_mappings()[0], "order": 1}),
            GuideData.from_mapping({**forward.to_mappings()[1], "order": 0}),
        )
    )
    assert forward.fingerprint("direction") != reverse.fingerprint("direction")


def test_guide_group_modifiers_are_non_destructive_and_composed_at_read_time():
    from bifrost_scales.guides import GuideGroupData

    authored = GuideData(
        guide_id="density_grouped",
        name="Authored",
        kind=GuideKind.FLOW_CURVE,
        points=((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        group_id="group_primary",
        radius=2.0,
        falloff=1.0,
        density_multiplier=3.0,
        size_multiplier=1.5,
        strength=0.4,
        angle_degrees=10.0,
    ).normalized()
    group = GuideGroupData(
        group_id="group_primary",
        name="Primary",
        radius_multiplier=1.5,
        falloff_multiplier=0.5,
        density_strength=0.5,
        size_strength=2.0,
        direction_strength=1.5,
        angle_offset_degrees=25.0,
    )

    effective = group.apply(authored)

    assert authored.radius == 2.0
    assert authored.density_multiplier == 3.0
    assert authored.angle_degrees == 10.0
    assert effective.group_id == "group_primary"
    assert effective.radius == 3.0
    assert effective.falloff == 0.5
    assert effective.density_multiplier == 2.0
    assert effective.size_multiplier == 2.0
    assert group.normalized().direction_strength == 1.0
    assert abs(effective.strength - 0.4) < 1.0e-12
    assert effective.angle_degrees == 35.0


def test_direction_curve_creates_centerline_anchors_but_not_cell_pair_influence():
    curve = GuideData(
        guide_id="centerline",
        name="Centerline",
        kind=GuideKind.DIRECTION_CURVE,
        points=((-2.0, 0.0, 0.0), (2.0, 0.0, 0.0)),
        radius=2.0,
        strength=1.0,
    ).normalized()
    point = GuideData(
        guide_id="attractor",
        name="Attractor",
        kind=GuideKind.DIRECTION_POINT,
        points=((0.0, 0.0, 0.0),),
        radius=2.0,
        strength=1.0,
    ).normalized()

    curve_set = GuideSet.from_iterable((curve,))
    anchors = curve_set.curve_center_anchor_positions(spacing=1.0, limit=20)
    assert len(anchors) == 4
    assert all(abs(position[2]) < 1.0e-12 for position in anchors)
    assert curve_set.point_direction_influence((0.25, 0.0, 0.0)) == 0.0
    assert GuideSet.from_iterable((point,)).point_direction_influence(
        (0.25, 0.0, 0.0)
    ) > 0.0


def test_direction_curve_centerline_candidates_are_independent_of_positive_strength():
    base = GuideData(
        guide_id="centerline",
        name="Centerline",
        kind=GuideKind.DIRECTION_CURVE,
        points=((-2.0, 0.0, 0.0), (2.0, 0.0, 0.0)),
        radius=2.0,
        strength=1.0,
    ).normalized()
    full = GuideSet.from_iterable((base,)).curve_center_anchor_positions(1.0, 20)
    half = GuideSet.from_iterable((replace(base, strength=0.5),)).curve_center_anchor_positions(
        1.0, 20
    )
    off = GuideSet.from_iterable((replace(base, strength=0.0),)).curve_center_anchor_positions(
        1.0, 20
    )
    assert len(full) == 4
    assert half == full
    assert off == ()


def test_scale_type_group_link_uses_maximum_member_influence():
    first = GuideData(
        guide_id="first",
        name="First",
        kind=GuideKind.DENSITY_POINT,
        points=((0.0, 0.0, 0.0),),
        group_id="group_primary",
        radius=2.0,
        falloff=1.0,
    ).normalized()
    second = GuideData(
        guide_id="second",
        name="Second",
        kind=GuideKind.DENSITY_POINT,
        points=((1.0, 0.0, 0.0),),
        group_id="group_primary",
        radius=2.0,
        falloff=1.0,
    ).normalized()
    guides = GuideSet.from_iterable((first, second))
    position = (0.25, 0.0, 0.0)

    expected = max(
        guides.influence_for_id("first", position),
        guides.influence_for_id("second", position),
    )
    assert guides.influence_for_id("group_primary", position) == expected
    assert guides.influence_for_id("missing_group", position) == 0.0

    disabled_near = replace(
        first,
        guide_id="disabled_near",
        points=(position,),
        enabled=False,
    )
    with_disabled = GuideSet.from_iterable((first, second, disabled_near))
    assert with_disabled.influence_for_id("group_primary", position) == expected


def test_exact_guide_id_precedes_a_colliding_group_id():
    exact = GuideData(
        guide_id="group_primary",
        name="Exact",
        kind=GuideKind.DENSITY_POINT,
        points=((10.0, 0.0, 0.0),),
        radius=0.25,
        falloff=1.0,
    ).normalized()
    member = GuideData(
        guide_id="member",
        name="Member",
        kind=GuideKind.DENSITY_POINT,
        points=((0.0, 0.0, 0.0),),
        group_id="group_primary",
        radius=2.0,
        falloff=1.0,
    ).normalized()
    guides = GuideSet.from_iterable((member, exact))

    assert guides.influence_for_id("member", (0.0, 0.0, 0.0)) == 1.0
    assert guides.influence_for_id("group_primary", (0.0, 0.0, 0.0)) == 0.0


def test_display_name_is_management_only_but_group_membership_changes_links():
    from bifrost_scales.backend import NativeMayaBackend
    from bifrost_scales.scheduler import ChangeCategory

    base_guide = _density()
    base = GuideSet.from_iterable((base_guide,))
    renamed = GuideSet.from_iterable((replace(base_guide, name="Renamed"),))
    grouped = GuideSet.from_iterable(
        (replace(base_guide, group_id="group_primary"),)
    )

    assert NativeMayaBackend._guide_change_category(base, renamed) \
        is ChangeCategory.DISPLAY
    assert NativeMayaBackend._guide_change_category(base, grouped) \
        is ChangeCategory.SHAPE


def test_short_direction_curve_still_authors_one_center_anchor():
    guide = GuideData(
        guide_id="short",
        name="Short",
        kind=GuideKind.FLOW_CURVE,
        points=((0.0, 0.0, 0.0), (0.25, 0.0, 0.0)),
        radius=2.0,
        strength=0.1,
        use_direction=True,
    )
    anchors = GuideSet.from_iterable((guide,)).curve_center_anchor_positions(
        spacing=1.0,
        limit=20,
    )
    assert anchors == ((0.125, 0.0, 0.0),)


def test_symmetry_expands_one_transient_world_mirror_without_mutating_authored_guide():
    authored = GuideData(
        guide_id="symmetric_density",
        name="Symmetric Density",
        kind=GuideKind.DENSITY_POINT,
        points=((1.0, 0.0, 0.0),),
        radius=0.75,
        density_multiplier=3.0,
        symmetry_enabled=True,
        symmetry_axis="x",
        symmetry_space="world",
        symmetry_origin=(0.0, 0.0, 0.0),
        symmetry_normal=(1.0, 0.0, 0.0),
    ).normalized()
    guides = GuideSet.from_iterable((authored,))

    assert len(guides.guides) == 1
    assert guides.guides[0].points == ((1.0, 0.0, 0.0),)
    assert len(guides.evaluated_guides) == 2
    assert [item.points[0] for item in guides.evaluated_guides] == [
        (1.0, 0.0, 0.0),
        (-1.0, 0.0, 0.0),
    ]
    assert [item.guide_id for item in guides.evaluated_guides] == [
        "symmetric_density",
        "symmetric_density",
    ]
    assert len(guides.to_mappings()) == 2
    assert len(guides.authored_to_mappings()) == 1
    assert guides.authored_to_mappings()[0]["symmetry_enabled"] is True

    right_density, _ = guides.density_factors((1.0, 0.0, 0.0))
    left_density, _ = guides.density_factors((-1.0, 0.0, 0.0))
    assert right_density == left_density == 3.0
    assert guides.influence_for_id(
        "symmetric_density", (-1.0, 0.0, 0.0)
    ) == 1.0


def test_symmetry_reflects_curve_order_and_negates_direction_angle():
    curve = GuideData(
        guide_id="symmetric_flow",
        name="Symmetric Flow",
        kind=GuideKind.DIRECTION_CURVE,
        points=((1.0, 0.0, -1.0), (2.0, 0.0, 1.0)),
        direction=(1.0, 0.0, 0.0),
        radius=2.0,
        angle_degrees=25.0,
        symmetry_enabled=True,
        symmetry_axis="x",
        symmetry_origin=(0.0, 0.0, 0.0),
        symmetry_normal=(1.0, 0.0, 0.0),
    ).normalized()
    evaluated = GuideSet.from_iterable((curve,)).evaluated_guides

    assert len(evaluated) == 2
    mirrored = evaluated[1]
    assert mirrored.points == ((-1.0, 0.0, -1.0), (-2.0, 0.0, 1.0))
    assert mirrored.direction == (-1.0, 0.0, 0.0)
    assert mirrored.angle_degrees == -25.0
    assert mirrored.symmetry_enabled is False


def test_symmetry_does_not_duplicate_guides_that_are_on_the_center_plane():
    point = GuideData(
        guide_id="center_point",
        name="Center Point",
        kind=GuideKind.DIRECTION_POINT,
        points=((0.0, 0.0, 0.0),),
        radius=2.0,
        angle_degrees=30.0,
        symmetry_enabled=True,
        symmetry_axis="x",
    ).normalized()
    curve = GuideData(
        guide_id="center_curve",
        name="Center Curve",
        kind=GuideKind.DIRECTION_CURVE,
        points=((0.0, 0.0, -1.0), (0.0, 0.0, 1.0)),
        radius=2.0,
        symmetry_enabled=True,
        symmetry_axis="x",
    ).normalized()

    assert len(GuideSet.from_iterable((point,)).evaluated_guides) == 1
    assert len(GuideSet.from_iterable((curve,)).evaluated_guides) == 1


def test_group_symmetry_is_a_non_destructive_member_override():
    from bifrost_scales.guides import GuideGroupData

    authored = GuideData(
        guide_id="member",
        name="Member",
        kind=GuideKind.DIRECTION_POINT,
        points=((2.0, 0.0, 0.0),),
        group_id="group_symmetry",
        symmetry_enabled=False,
        symmetry_axis="x",
        symmetry_space="world",
    ).normalized()
    group = GuideGroupData(
        group_id="group_symmetry",
        name="Symmetry Group",
        symmetry_enabled=True,
        symmetry_axis="z",
        symmetry_space="target_local",
    ).normalized()

    effective = group.apply(authored)

    assert authored.symmetry_enabled is False
    assert authored.symmetry_axis == "x"
    assert authored.symmetry_space == "world"
    assert effective.symmetry_enabled is True
    assert effective.symmetry_axis == "z"
    assert effective.symmetry_space == "target_local"


def test_symmetry_invalidation_starts_at_the_earliest_affected_stage():
    from bifrost_scales.backend import NativeMayaBackend
    from bifrost_scales.scheduler import ChangeCategory

    density = GuideData(
        guide_id="density_symmetry",
        name="Density Symmetry",
        kind=GuideKind.DENSITY_POINT,
        points=((1.0, 0.0, 0.0),),
        use_density=True,
        use_size=False,
        use_direction=False,
    ).normalized()
    density_mirrored = replace(
        density,
        symmetry_enabled=True,
        symmetry_axis="x",
    ).normalized()
    assert NativeMayaBackend._guide_change_category(
        GuideSet.from_iterable((density,)),
        GuideSet.from_iterable((density_mirrored,)),
    ) is ChangeCategory.DISTRIBUTION

    point_direction = GuideData(
        guide_id="point_direction_symmetry",
        name="Point Direction Symmetry",
        kind=GuideKind.DIRECTION_POINT,
        points=((1.0, 0.0, 0.0),),
        use_density=False,
        use_size=False,
        use_direction=True,
    ).normalized()
    point_direction_mirrored = replace(
        point_direction,
        symmetry_enabled=True,
        symmetry_axis="x",
    ).normalized()
    assert NativeMayaBackend._guide_change_category(
        GuideSet.from_iterable((point_direction,)),
        GuideSet.from_iterable((point_direction_mirrored,)),
    ) is ChangeCategory.ORIENTATION

    curve_direction = replace(
        point_direction,
        guide_id="curve_direction_symmetry",
        kind=GuideKind.DIRECTION_CURVE,
        points=((1.0, 0.0, -1.0), (1.0, 0.0, 1.0)),
    ).normalized()
    curve_direction_mirrored = replace(
        curve_direction,
        symmetry_enabled=True,
        symmetry_axis="x",
    ).normalized()
    # Direction curves author deterministic cell-center samples, so symmetry
    # changes the Distribution stage rather than Orientation alone.
    assert NativeMayaBackend._guide_change_category(
        GuideSet.from_iterable((curve_direction,)),
        GuideSet.from_iterable((curve_direction_mirrored,)),
    ) is ChangeCategory.DISTRIBUTION

    link_only = replace(
        point_direction,
        guide_id="link_only_symmetry",
        use_direction=False,
    ).normalized()
    link_only_mirrored = replace(
        link_only,
        symmetry_enabled=True,
        symmetry_axis="x",
    ).normalized()
    assert NativeMayaBackend._guide_change_category(
        GuideSet.from_iterable((link_only,)),
        GuideSet.from_iterable((link_only_mirrored,)),
    ) is ChangeCategory.SHAPE


def test_mask_falloff_is_normalized_width_within_range():
    def acceptance(falloff: float) -> tuple[float, ...]:
        mask = GuideData(
            guide_id="soft_mask",
            name="Soft Mask",
            kind=GuideKind.DENSITY_POINT,
            points=((0.0, 0.0, 0.0),),
            radius=1.0,
            falloff=falloff,
            use_density=False,
            use_size=False,
            use_direction=False,
            use_mask=True,
        ).normalized()
        guides = GuideSet.from_iterable((mask,))
        return tuple(
            guides.mask_acceptance_probability((distance, 0.0, 0.0))
            for distance in (0.0, 0.25, 0.5, 0.75, 1.0)
        )

    assert acceptance(0.0) == (0.0, 0.0, 0.0, 0.0, 1.0)
    assert acceptance(0.5) == (0.0, 0.0, 0.0, 0.5, 1.0)
    assert acceptance(1.0) == (0.0, 0.15625, 0.5, 0.84375, 1.0)


def test_falloff_normalization_migrates_legacy_values_to_valid_width():
    assert GuideData.from_mapping(
        {
            "guide_id": "legacy",
            "name": "Legacy",
            "kind": GuideKind.DENSITY_POINT.value,
            "points": ((0.0, 0.0, 0.0),),
            "falloff": 2.0,
        }
    ).falloff == 1.0
    assert GuideData(
        guide_id="negative",
        name="Negative",
        kind=GuideKind.DENSITY_POINT,
        points=((0.0, 0.0, 0.0),),
        falloff=-1.0,
    ).normalized().falloff == 0.0


def test_mask_geometry_changes_shape_but_not_distribution_or_direction_fingerprint():
    from bifrost_scales.backend import NativeMayaBackend
    from bifrost_scales.scheduler import ChangeCategory

    base = GuideData(
        guide_id="mask_fingerprint",
        name="Mask",
        kind=GuideKind.DENSITY_POINT,
        points=((0.0, 0.0, 0.0),),
        radius=0.4,
        use_density=False,
        use_size=False,
        use_direction=False,
        use_mask=True,
    ).normalized()
    moved = replace(base, points=((1.0, 0.0, 0.0),)).normalized()
    base_set = GuideSet.from_iterable((base,))
    moved_set = GuideSet.from_iterable((moved,))
    assert base_set.fingerprint("distribution") == moved_set.fingerprint(
        "distribution"
    )
    assert base_set.fingerprint("direction") == moved_set.fingerprint(
        "direction"
    )
    assert base_set.fingerprint("links") != moved_set.fingerprint("links")
    assert NativeMayaBackend._guide_change_category(
        base_set,
        moved_set,
    ) is ChangeCategory.SHAPE
