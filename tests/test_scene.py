from bifrost_scales.scene import MayaSceneManager
from bifrost_scales.settings import ScaleSettings

from fake_maya import FakeCmds


def _mesh(cmds, name):
    transform = cmds.createNode("transform", name)
    shape = cmds.createNode("mesh", name + "Shape", parent=transform)
    return transform, shape


def test_scene_manager_owns_only_settings_and_preview():
    cmds = FakeCmds()
    target_transform, target_shape = _mesh(cmds, "target")
    manager = MayaSceneManager(cmds)
    settings = ScaleSettings(target_count=77, seed=9)
    binding = manager.create_system(target_transform, settings)

    assert binding.target_mesh == target_shape
    assert binding.settings_node in manager.list_systems()
    assert manager.read_settings(binding.settings_node) == settings
    rebound = manager.bind(binding.settings_node)
    assert rebound == binding

    manager.set_stats(binding.preview_transform, 10, 60, 50)
    assert manager.get_stats(binding.preview_transform) == (10, 60, 50)

    manager.delete_system(binding.settings_node)
    assert not cmds.objExists(binding.settings_node)
    assert not cmds.objExists(binding.preview_transform)
    assert cmds.objExists(target_transform)
    assert cmds.objExists(target_shape)


def test_scene_manager_owns_point_and_curve_guides():
    from bifrost_scales.guides import GuideKind

    cmds = FakeCmds()
    target_transform, _target_shape = _mesh(cmds, "target")
    manager = MayaSceneManager(cmds)
    binding = manager.create_system(target_transform, ScaleSettings())

    point = manager.create_point_guide(binding.settings_node, GuideKind.DENSITY_POINT)
    manager.update_guide(
        point,
        radius=2.5,
        density_multiplier=3.0,
        size_multiplier=1.25,
    )
    cmds.xform(point, translation=(0.5, 0.0, -0.25), worldSpace=True)

    curve = cmds.createNode("transform", "sourceCurve")
    curve_shape = cmds.createNode("nurbsCurve", "sourceCurveShape", parent=curve)
    cmds.cv_points[curve_shape] = [(-1.0, 0.0, 0.0), (0.0, 0.0, 0.5), (1.0, 0.0, 1.0)]
    cmds.select(curve, replace=True)
    curve_guide = manager.create_curve_guide_from_selection(
        binding.settings_node,
        GuideKind.DIRECTION_CURVE,
    )

    guides = manager.read_guides(binding.settings_node)
    assert len(guides.guides) == 2
    assert len(guides.density) == 1
    assert len(guides.direction) == 1
    density = manager.read_guide(point)
    assert density.radius == 2.5
    assert density.density_multiplier == 3.0
    assert density.position == (0.5, 0.0, -0.25)
    direction = manager.read_guide(curve_guide)
    assert direction.kind == GuideKind.DIRECTION_CURVE
    assert len(direction.points) == 3
    assert direction.center_alignment == 0.35
    assert direction.cell_anisotropy == 1.0
    manager.update_guide(
        curve_guide,
        center_alignment=0.2,
        cell_anisotropy=0.75,
    )
    updated_direction = manager.read_guide(curve_guide)
    assert updated_direction.center_alignment == 0.2
    assert updated_direction.cell_anisotropy == 0.75

    manager.delete_system(binding.settings_node)
    assert not cmds.objExists(point)
    assert not cmds.objExists(curve_guide)
    assert cmds.objExists(target_transform)
    assert cmds.objExists(curve)


def test_breaking_schema_hides_and_rejects_older_development_systems():
    import pytest

    cmds = FakeCmds()
    target_transform, _target_shape = _mesh(cmds, "target")
    manager = MayaSceneManager(cmds)
    binding = manager.create_system(target_transform, ScaleSettings())
    assert binding.settings_node in manager.list_systems()

    cmds.setAttr(
        binding.settings_node + ".bsSchemaVersion",
        "bifrost-scales/4",
        type="string",
    )

    assert binding.settings_node not in manager.list_systems()
    with pytest.raises(ValueError, match="Incompatible Bifrost Scales system schema"):
        manager.bind(binding.settings_node)
    assert cmds.objExists(target_transform)


def test_scene_manager_creates_curve_guide_directly_from_surface_points():
    from bifrost_scales.guides import GuideKind

    cmds = FakeCmds()
    target_transform, _target_shape = _mesh(cmds, "target")
    manager = MayaSceneManager(cmds)
    binding = manager.create_system(target_transform, ScaleSettings())
    points = [(-1.0, 0.1, 0.0), (0.0, 0.2, 0.5), (1.0, 0.1, 1.0)]

    guide = manager.create_curve_guide_from_points(
        binding.settings_node,
        GuideKind.DENSITY_CURVE,
        points,
    )

    assert cmds.listRelatives(guide, parent=True) == [binding.guide_root]
    assert cmds.selection == [guide]
    data = manager.read_guide(guide)
    assert data.kind == GuideKind.DENSITY_CURVE
    assert data.points == tuple(points)
    assert guide in manager.list_guides(binding.settings_node)


def test_guide_display_names_order_selection_and_undo_contract():
    from bifrost_scales.guides import GuideKind

    cmds = FakeCmds()
    target_transform, _target_shape = _mesh(cmds, "guideTarget")
    manager = MayaSceneManager(cmds)
    binding = manager.create_system(target_transform, ScaleSettings())
    cmds.undo_events.clear()

    first = manager.create_point_guide(binding.settings_node, GuideKind.DENSITY_POINT)
    second = manager.create_point_guide(binding.settings_node, GuideKind.DIRECTION_POINT)
    curve = manager.create_curve_guide_from_points(
        binding.settings_node,
        GuideKind.FLOW_CURVE,
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
    )

    assert first.startswith("bifrostScalesGuidePoint")
    assert second.startswith("bifrostScalesGuidePoint")
    assert curve.startswith("bifrostScalesGuideCurve")
    assert [manager.read_guide(node).name for node in (first, second, curve)] == [
        "Guide 1",
        "Guide 2",
        "Guide 3",
    ]
    assert cmds.selection == [curve]
    assert [event[0] for event in cmds.undo_events if event[0] in {"open", "close"}] == [
        "open",
        "close",
        "open",
        "close",
        "open",
        "close",
    ]
    assert cmds.undo_chunk_depth == 0

    renamed = manager.rename_guide(second, "  Main   Direction  ")
    assert renamed == "Main Direction"
    assert manager.read_guide(second).name == "Main Direction"

    reordered = manager.reorder_guides(
        binding.settings_node,
        [curve, second, first],
    )
    assert reordered == [curve, second, first]
    # Management order changes, while the authored evaluation order remains stable.
    assert [manager.read_guide(node).order for node in reordered] == [2, 1, 0]
    assert [
        item.guide_id for item in manager.read_guides(binding.settings_node).guides
    ] == [
        manager.read_guide(first).guide_id,
        manager.read_guide(second).guide_id,
        manager.read_guide(curve).guide_id,
    ]

    cmds.select(first, replace=True)
    assert manager.selected_guides(binding.settings_node) == [first]
    point_shape = cmds.listRelatives(first, shapes=True)[0]
    cmds.select(point_shape, replace=True)
    assert manager.selected_guides(binding.settings_node) == [first]
    curve_shape = cmds.listRelatives(curve, shapes=True, type="nurbsCurve")[0]
    cmds.select(curve_shape + ".cv[0]", replace=True)
    assert manager.selected_guides(binding.settings_node) == [curve]
    cmds.select(target_transform, replace=True)
    assert manager.selected_guides(binding.settings_node) == []


def test_legacy_guides_gain_metadata_without_compacting_existing_order_gaps():
    from bifrost_scales.guides import GuideKind

    cmds = FakeCmds()
    target_transform, _target_shape = _mesh(cmds, "migrationTarget")
    manager = MayaSceneManager(cmds)
    binding = manager.create_system(target_transform, ScaleSettings())
    first = manager.create_point_guide(binding.settings_node, GuideKind.DENSITY_POINT)
    second = manager.create_point_guide(binding.settings_node, GuideKind.DENSITY_POINT)
    third = manager.create_point_guide(binding.settings_node, GuideKind.DENSITY_POINT)

    # Simulate 0.8.1 data: evaluation order/name exist, while group/UI metadata do not.
    for node in (first, second, third):
        cmds.deleteAttr(node + ".bsGuideUiOrder")
        cmds.deleteAttr(node + ".bsGuideGroupId")
    cmds.setAttr(first + ".bsGuideOrder", 0)
    cmds.setAttr(third + ".bsGuideOrder", 8)
    cmds.deleteAttr(second + ".bsGuideOrder")
    cmds.deleteAttr(second + ".bsGuideDisplayName")
    cmds.undo_events.clear()

    assert manager.list_guides(binding.settings_node) == [first, third, second]
    assert manager.read_guide(first).order == 0
    assert manager.read_guide(third).order == 8
    assert manager.read_guide(second).order == 9
    assert manager.read_guide(second).name == "Guide 10"
    # Lazy migration is host maintenance, not a user Undo step.
    assert not [event for event in cmds.undo_events if event[0] in {"open", "close"}]


def test_scene_manager_groups_are_non_destructive_and_restore_members_on_delete():
    from bifrost_scales.guides import GuideKind

    cmds = FakeCmds()
    target_transform, _target_shape = _mesh(cmds, "groupTarget")
    manager = MayaSceneManager(cmds)
    binding = manager.create_system(target_transform, ScaleSettings())

    guide = manager.create_point_guide(
        binding.settings_node,
        GuideKind.DENSITY_POINT,
    )
    manager.rename_guide(guide, "Face Density")
    manager.update_guide(guide, radius=2.0, density_multiplier=3.0)
    group = manager.create_guide_group(binding.settings_node, "Head Guides")
    group_data = manager.read_guide_group(group)
    guide = manager.move_guide_to_group(binding.settings_node, guide, group)
    manager.update_guide_group(
        group,
        radius_multiplier=1.5,
        density_strength=0.5,
    )

    authored = manager.read_guide(guide)
    effective = manager.read_guide(guide, effective=True)
    assert authored.name == "Face Density"
    assert authored.group_id == group_data.group_id
    assert authored.radius == 2.0
    assert authored.density_multiplier == 3.0
    assert effective.radius == 3.0
    assert effective.density_multiplier == 2.0
    assert cmds.listRelatives(guide, parent=True) == [group]

    moved = manager.delete_guide_group(binding.settings_node, group)
    assert len(moved) == 1
    restored = manager.read_guide(moved[0])
    assert restored.group_id == ""
    assert restored.radius == 2.0
    assert restored.density_multiplier == 3.0
    assert cmds.listRelatives(moved[0], parent=True) == [binding.guide_root]


def test_new_guide_group_contains_selected_guides_in_one_undo_step():
    from bifrost_scales.guides import GuideKind

    cmds = FakeCmds()
    target_transform, _target_shape = _mesh(cmds, "newGroupTarget")
    manager = MayaSceneManager(cmds)
    binding = manager.create_system(target_transform, ScaleSettings())
    first = manager.create_point_guide(
        binding.settings_node,
        GuideKind.DENSITY_POINT,
    )
    second = manager.create_point_guide(
        binding.settings_node,
        GuideKind.DIRECTION_POINT,
    )
    cmds.undo_events.clear()

    group = manager.create_guide_group(
        binding.settings_node,
        guide_nodes=[first, second],
    )
    group_id = manager.read_guide_group(group).group_id

    assert cmds.listRelatives(first, parent=True) == [group]
    assert cmds.listRelatives(second, parent=True) == [group]
    assert manager.read_guide(first).group_id == group_id
    assert manager.read_guide(second).group_id == group_id
    assert cmds.selection == [group]
    assert [
        event[0] for event in cmds.undo_events if event[0] in {"open", "close"}
    ] == ["open", "close"]


def test_maya_group_selection_is_classified_before_ctrl_g():
    from bifrost_scales.guides import GuideKind

    cmds = FakeCmds()
    target_transform, _target_shape = _mesh(cmds, "groupSelectionTarget")
    manager = MayaSceneManager(cmds)
    binding = manager.create_system(target_transform, ScaleSettings())
    first = manager.create_point_guide(
        binding.settings_node,
        GuideKind.DENSITY_POINT,
    )
    second = manager.create_point_guide(
        binding.settings_node,
        GuideKind.DIRECTION_POINT,
    )
    ordinary = cmds.createNode("transform", "ordinaryObject")

    cmds.select([first, second], replace=True)
    assert manager.guide_grouping_selection(binding.settings_node) == (
        [first, second],
        True,
        False,
    )
    cmds.select([first, ordinary], replace=True)
    assert manager.guide_grouping_selection(binding.settings_node) == (
        [first],
        True,
        True,
    )
    cmds.select(ordinary, replace=True)
    assert manager.guide_grouping_selection(binding.settings_node) == (
        [],
        False,
        True,
    )


def test_maya_ctrl_g_style_group_is_adopted_only_for_pure_guides():
    from bifrost_scales.guides import GuideKind

    cmds = FakeCmds()
    target_transform, _target_shape = _mesh(cmds, "mayaGroupTarget")
    manager = MayaSceneManager(cmds)
    binding = manager.create_system(target_transform, ScaleSettings())
    first = manager.create_point_guide(
        binding.settings_node,
        GuideKind.DENSITY_POINT,
    )
    second = manager.create_point_guide(
        binding.settings_node,
        GuideKind.DIRECTION_POINT,
    )
    group = cmds.createNode("transform", "group1", parent=binding.guide_root)
    cmds.parent(first, group)
    cmds.parent(second, group)
    cmds.select(group, replace=True)

    assert manager.selected_guide_items(binding.settings_node) == [group]
    assert manager.read_guide_group(group).name == "group1"
    group_id = manager.read_guide_group(group).group_id
    assert manager.read_guide(first).group_id == group_id
    assert manager.read_guide(second).group_id == group_id


def test_guide_tree_layout_changes_management_only_and_preserves_evaluation_order():
    from bifrost_scales.guides import GuideKind

    cmds = FakeCmds()
    target_transform, _target_shape = _mesh(cmds, "layoutTarget")
    manager = MayaSceneManager(cmds)
    binding = manager.create_system(target_transform, ScaleSettings())
    first = manager.create_point_guide(binding.settings_node, GuideKind.DENSITY_POINT)
    second = manager.create_point_guide(binding.settings_node, GuideKind.DIRECTION_POINT)
    third = manager.create_point_guide(binding.settings_node, GuideKind.DENSITY_POINT)
    group_a = manager.create_guide_group(binding.settings_node, "A")
    group_b = manager.create_guide_group(binding.settings_node, "B")
    evaluation_before = [
        item.guide_id for item in manager.read_guides(binding.settings_node).guides
    ]

    manager.apply_guide_tree_layout(
        binding.settings_node,
        [group_b, group_a],
        {
            "": [second],
            group_b: [third],
            group_a: [first],
        },
    )

    assert manager.list_guide_groups(binding.settings_node) == [group_b, group_a]
    assert manager.read_guide(second).group_id == ""
    assert manager.read_guide(third).group_id == manager.read_guide_group(
        group_b
    ).group_id
    assert manager.read_guide(first).group_id == manager.read_guide_group(
        group_a
    ).group_id
    visible = manager.list_guides(binding.settings_node)
    assert [manager.read_guide(node).guide_id for node in visible] == [
        manager.read_guide(second).guide_id,
        manager.read_guide(third).guide_id,
        manager.read_guide(first).guide_id,
    ]
    assert [
        item.guide_id for item in manager.read_guides(binding.settings_node).guides
    ] == evaluation_before


def test_selected_guide_item_resolves_curve_shapes_components_and_groups():
    from bifrost_scales.guides import GuideKind

    cmds = FakeCmds()
    target_transform, _target_shape = _mesh(cmds, "selectionTarget")
    manager = MayaSceneManager(cmds)
    binding = manager.create_system(target_transform, ScaleSettings())
    curve = manager.create_curve_guide_from_points(
        binding.settings_node,
        GuideKind.DIRECTION_CURVE,
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
    )
    curve_shape = cmds.listRelatives(curve, shapes=True, type="nurbsCurve")[0]
    group = manager.create_guide_group(binding.settings_node, "Primary")

    cmds.select(curve_shape, replace=True)
    assert manager.selected_guide_item(binding.settings_node) == curve
    cmds.select(curve_shape + ".cv[0]", replace=True)
    assert manager.selected_guide_item(binding.settings_node) == curve
    cmds.select(group, replace=True)
    assert manager.selected_guide_item(binding.settings_node) == group
    cmds.select(target_transform, replace=True)
    assert manager.selected_guide_item(binding.settings_node) == ""


def test_multiple_selected_guide_items_sync_in_scene_selection_order():
    from bifrost_scales.guides import GuideKind

    cmds = FakeCmds()
    target_transform, _target_shape = _mesh(cmds, "multiSelectionTarget")
    manager = MayaSceneManager(cmds)
    binding = manager.create_system(target_transform, ScaleSettings())
    first = manager.create_point_guide(
        binding.settings_node,
        GuideKind.DENSITY_POINT,
    )
    second = manager.create_point_guide(
        binding.settings_node,
        GuideKind.DIRECTION_POINT,
    )
    second_shape = cmds.listRelatives(second, shapes=True)[0]
    group = manager.create_guide_group(binding.settings_node, "Primary")

    cmds.select([group, first, second_shape], replace=True)
    assert manager.selected_guide_items(binding.settings_node) == [
        group,
        first,
        second,
    ]
    assert manager.selected_guide_item(binding.settings_node) == group
    assert manager.selected_guides(binding.settings_node) == [first, second]

    manager.select_guide_items([second, group, second])
    assert cmds.selection == [second, group]
    manager.select_guide_items([])
    assert cmds.selection == []


def test_scene_symmetry_resolves_world_and_target_local_planes_without_dag_clones():
    from bifrost_scales.guides import GuideKind

    cmds = FakeCmds()
    target_transform, _target_shape = _mesh(cmds, "symmetryTarget")
    manager = MayaSceneManager(cmds)
    binding = manager.create_system(target_transform, ScaleSettings())
    guide = manager.create_point_guide(
        binding.settings_node,
        GuideKind.DIRECTION_POINT,
    )
    cmds.xform(guide, translation=(2.0, 0.0, 0.0), worldSpace=True)
    manager.update_guide(
        guide,
        symmetry_enabled=True,
        symmetry_axis="x",
        symmetry_space="world",
    )

    world_guides = manager.read_guides(binding.settings_node)
    assert len(manager.list_guides(binding.settings_node)) == 1
    assert len(world_guides.guides) == 1
    assert [item.position for item in world_guides.evaluated_guides] == [
        (2.0, 0.0, 0.0),
        (-2.0, 0.0, 0.0),
    ]
    assert world_guides.guides[0].symmetry_origin == (0.0, 0.0, 0.0)
    assert world_guides.guides[0].symmetry_normal == (1.0, 0.0, 0.0)

    # Maya xform matrices expose local basis rows followed by world translation.
    cmds.xform(
        target_transform,
        matrix=(
            0.0, 1.0, 0.0, 0.0,
            -1.0, 0.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            10.0, 0.0, 0.0, 1.0,
        ),
        worldSpace=True,
    )
    cmds.xform(guide, translation=(10.0, 2.0, 0.0), worldSpace=True)
    manager.update_guide(
        guide,
        symmetry_enabled=True,
        symmetry_axis="x",
        symmetry_space="target_local",
    )

    local_guides = manager.read_guides(binding.settings_node)
    assert local_guides.guides[0].symmetry_origin == (10.0, 0.0, 0.0)
    assert local_guides.guides[0].symmetry_normal == (0.0, 1.0, 0.0)
    assert [item.position for item in local_guides.evaluated_guides] == [
        (10.0, 2.0, 0.0),
        (10.0, -2.0, 0.0),
    ]


def test_scene_group_symmetry_overrides_members_non_destructively_and_migrates_old_nodes():
    from bifrost_scales.guides import GuideKind

    cmds = FakeCmds()
    target_transform, _target_shape = _mesh(cmds, "groupSymmetryTarget")
    manager = MayaSceneManager(cmds)
    binding = manager.create_system(target_transform, ScaleSettings())
    guide = manager.create_point_guide(
        binding.settings_node,
        GuideKind.DENSITY_POINT,
    )
    cmds.xform(guide, translation=(0.0, 0.0, 3.0), worldSpace=True)
    group = manager.create_guide_group(binding.settings_node, "Mirrored")
    guide = manager.move_guide_to_group(binding.settings_node, guide, group)
    manager.update_guide(
        guide,
        symmetry_enabled=False,
        symmetry_axis="x",
        symmetry_space="world",
    )
    manager.update_guide_group(
        group,
        symmetry_enabled=True,
        symmetry_axis="z",
        symmetry_space="world",
    )

    authored = manager.read_guide(guide)
    effective = manager.read_guides(binding.settings_node)
    assert authored.symmetry_enabled is False
    assert authored.symmetry_axis == "x"
    assert len(effective.evaluated_guides) == 2
    assert [item.position for item in effective.evaluated_guides] == [
        (0.0, 0.0, 3.0),
        (0.0, 0.0, -3.0),
    ]
    assert effective.guides[0].symmetry_axis == "z"

    # Simulate a 0.8.4 scene. Lazy migration adds neutral symmetry metadata
    # without putting maintenance operations on Maya's user Undo stack.
    for node, attributes in (
        (guide, (
            "bsGuideSymmetryEnabled",
            "bsGuideSymmetryAxis",
            "bsGuideSymmetrySpace",
            "bsGuideCenterAlignment",
            "bsGuideCellAnisotropy",
        )),
        (group, (
            "bsGuideGroupSymmetryEnabled",
            "bsGuideGroupSymmetryAxis",
            "bsGuideGroupSymmetrySpace",
        )),
    ):
        for attribute in attributes:
            cmds.deleteAttr(node + "." + attribute)
    cmds.undo_events.clear()

    manager.list_guides(binding.settings_node)
    migrated_guide = manager.read_guide(guide)
    migrated_group = manager.read_guide_group(group)
    assert migrated_guide.symmetry_enabled is False
    assert migrated_guide.symmetry_axis == "x"
    assert migrated_guide.symmetry_space == "world"
    assert migrated_guide.center_alignment == 0.35
    assert migrated_guide.cell_anisotropy == 1.0
    assert migrated_group.symmetry_enabled is False
    assert migrated_group.symmetry_axis == "x"
    assert migrated_group.symmetry_space == "world"
    assert not [event for event in cmds.undo_events if event[0] in {"open", "close"}]


def test_mask_guide_metadata_round_trips_and_colors_shape_magenta():
    from bifrost_scales.guides import GuideKind

    cmds = FakeCmds()
    target_transform, _target_shape = _mesh(cmds, "target")
    manager = MayaSceneManager(cmds)
    binding = manager.create_system(target_transform, ScaleSettings())
    guide = manager.create_point_guide(
        binding.settings_node,
        GuideKind.DENSITY_POINT,
    )

    manager.update_guide(
        guide,
        use_density=False,
        use_size=False,
        use_direction=False,
        use_mask=True,
    )
    stored = manager.read_guide(guide)
    assert stored.affects_mask is True
    shapes = cmds.listRelatives(guide, shapes=True) or []
    assert shapes
    assert cmds.getAttr(shapes[0] + ".overrideColorRGB") == (1.0, 0.08, 0.72)

    manager.update_guide(guide, use_mask=False)
    assert manager.read_guide(guide).affects_mask is False
    assert cmds.getAttr(shapes[0] + ".overrideColorRGB") != (1.0, 0.08, 0.72)


def test_guide_styling_skips_equal_viewport_attributes():
    from bifrost_scales.guides import GuideKind

    cmds = FakeCmds()
    target_transform, _target_shape = _mesh(cmds, "target")
    manager = MayaSceneManager(cmds)
    binding = manager.create_system(target_transform, ScaleSettings())
    guide = manager.create_point_guide(
        binding.settings_node,
        GuideKind.DENSITY_POINT,
    )
    writes = []
    original_set_attr = cmds.setAttr

    def record_set_attr(plug, *values, **kwargs):
        writes.append(str(plug))
        return original_set_attr(plug, *values, **kwargs)

    cmds.setAttr = record_set_attr
    manager._style_guide_node(guide, GuideKind.DENSITY_POINT, False)

    assert writes == []


def test_nested_guide_groups_preserve_hierarchy_and_evaluation_order():
    from bifrost_scales.guides import GuideKind

    cmds = FakeCmds()
    target_transform, _target_shape = _mesh(cmds, "nestedTarget")
    manager = MayaSceneManager(cmds)
    binding = manager.create_system(target_transform, ScaleSettings())
    first = manager.create_point_guide(binding.settings_node, GuideKind.DENSITY_POINT)
    second = manager.create_point_guide(
        binding.settings_node, GuideKind.DIRECTION_POINT
    )
    parent = manager.create_guide_group(binding.settings_node, "Parent")
    child = manager.create_guide_group(binding.settings_node, "Child")
    evaluation_before = [
        guide.guide_id for guide in manager.read_guides(binding.settings_node).guides
    ]

    manager.apply_guide_tree_layout(
        binding.settings_node,
        [parent, child],
        {"": [], parent: [first], child: [second]},
        {parent: "", child: parent},
    )
    cmds.undo_events.clear()
    manager.set_guide_group_collapsed(parent, True)
    assert cmds.undo_events == [("state", False), ("state", True)]

    assert manager.list_guide_groups(binding.settings_node) == [parent, child]
    assert manager.guide_group_layout_state(binding.settings_node) == {
        parent: ("", True),
        child: (parent, False),
    }
    assert cmds.listRelatives(child, parent=True) == [parent]
    assert cmds.listRelatives(first, parent=True) == [parent]
    assert cmds.listRelatives(second, parent=True) == [child]
    assert [
        guide.guide_id for guide in manager.read_guides(binding.settings_node).guides
    ] == evaluation_before


def test_guide_item_visibility_and_lock_are_management_only_and_undoable():
    from bifrost_scales.guides import GuideKind

    cmds = FakeCmds()
    target_transform, _target_shape = _mesh(cmds, "presentationTarget")
    manager = MayaSceneManager(cmds)
    binding = manager.create_system(target_transform, ScaleSettings())
    guide = manager.create_point_guide(
        binding.settings_node,
        GuideKind.DENSITY_POINT,
    )
    group = manager.create_guide_group(binding.settings_node, "Presentation")
    evaluation_before = manager.read_guides(binding.settings_node).fingerprint()
    management_before = manager.guide_management_fingerprint(binding.settings_node)

    assert manager.guide_item_presentation_state(binding.settings_node) == {
        guide: (True, False),
        group: (True, False),
    }

    cmds.undo_events.clear()
    manager.set_guide_item_visible(binding.settings_node, guide, False)
    assert cmds.undo_events == [
        ("open", "Bifrost Scales Set Guide Visibility"),
        ("close", ""),
    ]

    cmds.undo_events.clear()
    manager.set_guide_item_locked(binding.settings_node, group, True)
    assert cmds.undo_events == [
        ("open", "Bifrost Scales Set Guide Lock"),
        ("close", ""),
    ]

    assert manager.guide_item_presentation_state(binding.settings_node) == {
        guide: (False, False),
        group: (True, True),
    }
    assert manager.guide_management_fingerprint(
        binding.settings_node
    ) != management_before
    assert manager.read_guides(binding.settings_node).fingerprint() == evaluation_before

def test_guide_presentation_noop_does_not_open_undo_chunks():
    import pytest
    from bifrost_scales.guides import GuideKind

    cmds = FakeCmds()
    target, _ = _mesh(cmds, "noopTarget")
    manager = MayaSceneManager(cmds)
    binding = manager.create_system(target, ScaleSettings())
    nodes = [manager.create_point_guide(binding.settings_node, GuideKind.DENSITY_POINT),
             manager.create_guide_group(binding.settings_node, "Noop Group")]
    before = manager.read_guides(binding.settings_node).fingerprint()
    for node in nodes:
        for setter in (manager.set_guide_item_visible, manager.set_guide_item_locked):
            for value in (False, True):
                setter(binding.settings_node, node, value)
                cmds.undo_events.clear()
                setter(binding.settings_node, node, value)
                assert not cmds.undo_events, "Unchanged presentation must not add Undo work"
    assert manager.read_guides(binding.settings_node).fingerprint() == before
    foreign = cmds.createNode("transform", "notOwned")
    cmds.undo_events.clear()
    for setter in (manager.set_guide_item_visible, manager.set_guide_item_locked):
        for value in (False, True):
            with pytest.raises(ValueError, match="not owned"):
                setter(binding.settings_node, foreign, value)
    assert not cmds.undo_events


def test_nested_guide_group_layout_rejects_cycles_before_changing_dag():
    cmds = FakeCmds()
    target_transform, _target_shape = _mesh(cmds, "cycleTarget")
    manager = MayaSceneManager(cmds)
    binding = manager.create_system(target_transform, ScaleSettings())
    first = manager.create_guide_group(binding.settings_node, "First")
    second = manager.create_guide_group(binding.settings_node, "Second")

    try:
        manager.apply_guide_tree_layout(
            binding.settings_node,
            [first, second],
            {"": [], first: [], second: []},
            {first: second, second: first},
        )
    except ValueError as exc:
        assert "cycle" in str(exc)
    else:
        raise AssertionError("Cyclic Guide Group layout was accepted")

    assert cmds.listRelatives(first, parent=True) == [binding.guide_root]
    assert cmds.listRelatives(second, parent=True) == [binding.guide_root]


def test_deleting_parent_guide_group_preserves_child_group_and_guides():
    from bifrost_scales.guides import GuideKind

    cmds = FakeCmds()
    target_transform, _target_shape = _mesh(cmds, "deleteNestedTarget")
    manager = MayaSceneManager(cmds)
    binding = manager.create_system(target_transform, ScaleSettings())
    direct = manager.create_point_guide(binding.settings_node, GuideKind.DENSITY_POINT)
    nested = manager.create_point_guide(
        binding.settings_node, GuideKind.DIRECTION_POINT
    )
    parent = manager.create_guide_group(binding.settings_node, "Parent")
    child = manager.create_guide_group(binding.settings_node, "Child")
    manager.apply_guide_tree_layout(
        binding.settings_node,
        [parent, child],
        {"": [], parent: [direct], child: [nested]},
        {parent: "", child: parent},
    )

    moved = manager.delete_guide_group(binding.settings_node, parent)

    assert not cmds.objExists(parent)
    assert cmds.objExists(child)
    assert cmds.objExists(direct)
    assert cmds.objExists(nested)
    assert moved == [direct]
    assert cmds.listRelatives(child, parent=True) == [binding.guide_root]
    assert cmds.listRelatives(direct, parent=True) == [binding.guide_root]
    assert cmds.listRelatives(nested, parent=True) == [child]
    assert manager.read_guide(direct).group_id == ""
    assert manager.read_guide(nested).group_id == manager.read_guide_group(child).group_id
