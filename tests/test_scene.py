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
