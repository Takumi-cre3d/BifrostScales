"""Measure one Bifrost Scales slider drag through the real Maya UI path."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback
from types import MethodType, SimpleNamespace
from pathlib import Path


def _mark(step: str) -> None:
    print("MAYA_SLIDER_STEP={}".format(step), file=sys.stderr, flush=True)


def _launch_maya(args, script: Path) -> int:
    if args.output is None:
        raise ValueError("--output is required when launching Maya")
    maya = args.maya.resolve()
    if not maya.is_file():
        raise FileNotFoundError("Maya executable was not found: {}".format(maya))
    child_args = [
        str(script),
        "--inside-maya",
        "--scene-preopened",
        "--scene",
        str(args.scene.resolve()),
        "--timeout",
        str(args.timeout),
        "--output",
        str(args.output.resolve()),
    ]
    if args.settings:
        child_args.extend(("--settings", args.settings))
    if args.source_runtime:
        child_args.append("--source-runtime")
    if args.warmup:
        child_args.append("--warmup")
    if args.ui_idle_seconds > 0.0:
        child_args.extend(("--ui-idle-seconds", str(args.ui_idle_seconds)))
    if args.touch_guide:
        child_args.append("--touch-guide")
    if args.camera_steps > 0:
        child_args.extend(("--camera-steps", str(args.camera_steps)))
    if args.select_guide_count > 0:
        child_args.extend(("--select-guide-count", str(args.select_guide_count)))
    if args.group_selection:
        child_args.extend(("--group-selection", args.group_selection))
    if args.ui_screenshot:
        child_args.extend(("--ui-screenshot", str(args.ui_screenshot.resolve())))
        child_args.extend(("--ui-screenshot-section", args.ui_screenshot_section))
    if args.auto_budget_probe:
        child_args.append("--auto-budget-probe")
    if args.stable_id_probe:
        child_args.append("--stable-id-probe")
    with tempfile.TemporaryDirectory(prefix="bifrost-scales-slider-") as temp:
        startup = Path(temp)
        bootstrap = startup / "bootstrap.py"
        bootstrap.write_text(
            "import maya.cmds as cmds, runpy, sys\n"
            "cmds.loadPlugin('bifrostGraph', quiet=True)\n"
            "cmds.file({!r}, open=True, force=True, prompt=False, ignoreVersion=True, "
            "executeScriptNodes=False, loadReferenceDepth='none')\n"
            "def _run_bifrost_scales_check():\n"
            "    sys.argv = {!r}\n"
            "    runpy.run_path({!r}, run_name='__main__')\n"
            "cmds.evalDeferred(_run_bifrost_scales_check, lowestPriority=True)\n".format(
                str(args.scene.resolve()), child_args, str(script)
            ),
            encoding="utf-8",
        )
        (startup / "userSetup.py").write_text(
            "import maya.utils\n"
            "maya.utils.executeDeferred(lambda: exec(open({!r}).read(), globals()))\n".format(
                str(bootstrap)
            ),
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment.pop("MAYA_SKIP_USERSETUP_PY", None)
        environment["PYTHONPATH"] = os.pathsep.join(
            item
            for item in (str(startup), environment.get("PYTHONPATH", ""))
            if item
        )
        startup_info = None
        if os.name == "nt":
            startup_info = subprocess.STARTUPINFO()
            startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup_info.wShowWindow = subprocess.SW_HIDE
        completed = subprocess.run(
            [str(maya), "-noAutoloadPlugins"],
            env=environment,
            startupinfo=startup_info,
            timeout=max(180.0, args.timeout * 3.0),
            check=False,
        )
    if not args.output.is_file():
        raise RuntimeError("Maya exited without writing the measurement result")
    result = json.loads(args.output.read_text(encoding="utf-8"))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    return 1 if (
        completed.returncode or result.get("error")
        or result.get("grouping_probe", {}).get("error")
        or result.get("auto_budget_probe", {}).get("error")
        or result.get("auto_budget_probe", {}).get("passed") is False
    ) else 0


def _measure_ui_idle(args, backend_type) -> int:
    from bifrost_scales.qt_compat import QtCore, QtGui, QtWidgets
    from bifrost_scales.scheduler import ChangeCategory
    from bifrost_scales.ui import BifrostScalesWindow

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    poll_times = []
    guide_touched = [False]
    guide_tick_times = []
    scene_tick_times = []
    apply_times = []
    apply_modes = []
    guide_dirty_calls = [0]
    guide_attribute_events = []
    camera_refresh_times = []
    selection_probe = {}
    grouping_probe = {}
    auto_budget_probe = {}
    original_poll = backend_type.poll_guide_state
    original_apply = backend_type.apply
    original_guide_tick = BifrostScalesWindow._poll_guide_changes
    original_guide_dirty = BifrostScalesWindow._guide_node_dirtied
    original_guide_attribute = BifrostScalesWindow._guide_attribute_changed
    original_scene_tick = BifrostScalesWindow._poll_scene_selection_and_tool

    def measured_poll(self):
        started = time.monotonic()
        try:
            return original_poll(self)
        finally:
            poll_times.append((time.monotonic() - started) * 1000.0)

    def measured_apply(self, request):
        started = time.monotonic()
        try:
            return original_apply(self, request)
        finally:
            apply_times.append((time.monotonic() - started) * 1000.0)
            apply_modes.append(str(getattr(request, "mode", "")))

    def measured_guide_dirty(self, *callback_args):
        guide_dirty_calls[0] += 1
        return original_guide_dirty(self, *callback_args)

    def measured_guide_attribute(self, message, *callback_args):
        plug = callback_args[0] if callback_args else None
        try:
            guide_attribute_events.append(
                (int(message), str(plug.name()) if plug is not None else "")
            )
        except Exception:
            guide_attribute_events.append((int(message), "<unavailable>"))
        return original_guide_attribute(self, message, *callback_args)

    def measured_tick(times, function):
        def measured(self):
            started = time.monotonic()
            try:
                return function(self)
            finally:
                times.append((time.monotonic() - started) * 1000.0)

        return measured

    backend_type.poll_guide_state = measured_poll
    backend_type.apply = measured_apply
    BifrostScalesWindow._poll_guide_changes = measured_tick(
        guide_tick_times, original_guide_tick
    )
    BifrostScalesWindow._guide_node_dirtied = measured_guide_dirty
    BifrostScalesWindow._guide_attribute_changed = measured_guide_attribute
    BifrostScalesWindow._poll_scene_selection_and_tool = measured_tick(
        scene_tick_times, original_scene_tick
    )
    window = BifrostScalesWindow()
    if args.settings:
        window._refresh_systems(preferred=args.settings)
        if window.system_combo.currentText() != args.settings or window.status_label.text() == "Error":
            raise RuntimeError("Requested System could not be selected through the UI: " + args.settings)
    window.show()
    warmup_loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(500, warmup_loop.quit)
    run_warmup = getattr(warmup_loop, "exec", None) or warmup_loop.exec_
    run_warmup()
    ui_screenshot = ""
    ui_focus_confirmed = False
    if args.ui_screenshot:
        screenshot = args.ui_screenshot.resolve()
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        window.show_advanced_parameters.setFocus()
        QtWidgets.QApplication.processEvents()
        ui_focus_confirmed = bool(
            window.show_advanced_parameters.focusPolicy()
            & QtCore.Qt.TabFocus
        )
        if not ui_focus_confirmed:
            raise RuntimeError("Advanced parameter toggle is not keyboard-focusable")
        if args.ui_screenshot_section == "shape":
            scroll = window.edit_sculpt.parentWidget()
            while scroll is not None and not isinstance(scroll, QtWidgets.QScrollArea):
                scroll = scroll.parentWidget()
            if scroll is not None:
                scroll.ensureWidgetVisible(window.edit_sculpt, 0, 16)
            window.edit_sculpt.setFocus()
            QtWidgets.QApplication.processEvents()
        if not window.grab().save(str(screenshot), "PNG"):
            raise RuntimeError("Failed to save UI screenshot: {}".format(screenshot))
        ui_screenshot = str(screenshot)
    poll_times.clear()
    apply_times.clear()
    apply_modes.clear()
    guide_dirty_calls[0] = 0
    guide_attribute_events.clear()
    guide_tick_times.clear()
    scene_tick_times.clear()
    if args.auto_budget_probe:
        initial_budget = window.interactive_budget.value()
        settled_budget = window.settled_budget.value()
        auto_budget_probe.update(
            {
                "initial_budget": initial_budget,
                "settled_budget": settled_budget,
                "finished": [],
            }
        )

        def record_auto_budget(_revision, mode, report):
            auto_budget_probe["finished"].append(
                {
                    "mode": str(mode),
                    "widget_budget": window.interactive_budget.value(),
                    "effective_budget": report.effective_budget,
                    "next_budget": report.next_interactive_budget,
                    "settled_budget": window.settled_budget.value(),
                }
            )

        def trigger_auto_budget():
            try:
                window.auto_preview_budget.setChecked(True)
                window._begin_interaction()
                window.scheduler.queue_change(ChangeCategory.SHAPE, window._snapshot())
                QtCore.QTimer.singleShot(250, window._finish_interaction)
            except Exception as exc:
                auto_budget_probe["error"] = "{}: {}".format(
                    type(exc).__name__, exc
                )

        window.scheduler.request_finished.connect(record_auto_budget)
        QtCore.QTimer.singleShot(100, trigger_auto_budget)
    if args.touch_guide:
        window.auto_preview.setChecked(False)

        def touch_guide():
            if not window._guide_nodes:
                return
            node = window._guide_nodes[0]
            cmds = window.backend.scene.cmds
            cmds.select(node, replace=True)
            value = float(cmds.getAttr(node + ".translateX") or 0.0)
            cmds.setAttr(node + ".translateX", value + 0.001)
            guide_touched[0] = True

        QtCore.QTimer.singleShot(100, touch_guide)
    graph = window.backend.native.graph_for_system(window.backend.binding)
    snapshot = window.backend.native._read_output_snapshot(graph)
    counter_before = window.backend.native._execution_counter(graph)
    camera_restore = None
    if args.camera_steps > 0:
        cmds = window.backend.scene.cmds
        panels = cmds.getPanel(visiblePanels=True) or cmds.getPanel(type="modelPanel") or []
        panel = next(
            (item for item in panels if cmds.getPanel(typeOf=item) == "modelPanel"),
            "",
        )
        if not panel:
            raise RuntimeError("No Maya modelPanel is available for camera measurement")
        camera = cmds.modelPanel(panel, query=True, camera=True)
        if cmds.nodeType(camera) == "camera":
            camera = (
                cmds.listRelatives(camera, parent=True, fullPath=True) or [camera]
            )[0]
        rotation = tuple(
            float(value) for value in cmds.getAttr(camera + ".rotate")[0]
        )
        camera_restore = (camera, rotation)

        def move_camera():
            for step in range(1, args.camera_steps + 1):
                cmds.setAttr(camera + ".rotateY", rotation[1] + step * 0.05)
                started = time.monotonic()
                cmds.refresh(force=True)
                camera_refresh_times.append(
                    (time.monotonic() - started) * 1000.0
                )

        QtCore.QTimer.singleShot(100, move_camera)
    if args.select_guide_count > 0:
        selected_nodes = window._guide_nodes[: args.select_guide_count]
        if len(selected_nodes) != args.select_guide_count:
            raise RuntimeError("Not enough guides for selection measurement")

        def record_scene_to_ui():
            selection_probe["scene_to_ui"] = {
                "maya": window.backend.selected_guide_items(),
                "ui": window._selected_guide_item_nodes(),
            }

        def select_in_scene():
            requested = list(reversed(selected_nodes))
            window.backend.scene.cmds.select(requested, replace=True)
            selection_probe["scene_requested"] = requested
            QtCore.QTimer.singleShot(100, record_scene_to_ui)

        def select_in_ui():
            window.guide_tree.clearSelection()
            first_item = window._guide_tree_items_by_node[selected_nodes[0]]
            window.guide_tree.setCurrentItem(first_item)
            for node in selected_nodes:
                window._guide_tree_items_by_node[node].setSelected(True)
            selection_probe["ui_requested"] = list(selected_nodes)
            selection_probe["ui_to_scene"] = {
                "maya": window.backend.selected_guide_items(),
                "ui": window._selected_guide_item_nodes(),
            }
            QtCore.QTimer.singleShot(250, select_in_scene)

        QtCore.QTimer.singleShot(100, select_in_ui)
    if args.group_selection:
        selected_nodes = window._guide_nodes[:2]
        if len(selected_nodes) != 2:
            raise RuntimeError("Not enough guides for grouping measurement")
        selected_guide_ids = [
            window._guide_data_by_node[node].guide_id for node in selected_nodes
        ]

        def current_nodes_by_id():
            return {
                data.guide_id: node
                for node, data in window._guide_data_by_node.items()
                if data.guide_id in selected_guide_ids
            }

        def trigger_grouping():
            try:
                cmds = window.backend.scene.cmds
                before_groups = window.backend.list_guide_groups()
                status_before = window.status_label.text()
                if args.group_selection == "parameter-reset-undo":
                    current_settings = window.backend.read_settings()
                    defaults = type(current_settings)()
                    probe_count = defaults.target_count + 17
                    window._updating_widgets = True
                    try:
                        window.target_count.setValue(probe_count)
                    finally:
                        window._updating_widgets = False
                    window.backend.persist_settings(window._snapshot())
                    baseline_settings = window.backend.read_settings()

                    window._reset_global_section("distribution")
                    apply_deadline = time.monotonic() + 8.0
                    while (
                        window._parameter_undo_open
                        and time.monotonic() < apply_deadline
                    ):
                        QtWidgets.QApplication.processEvents()
                        time.sleep(0.01)
                    reset_settings = window.backend.read_settings()
                    cmds.undo()
                    undo_deadline = time.monotonic() + 0.75
                    while time.monotonic() < undo_deadline:
                        QtWidgets.QApplication.processEvents()
                        time.sleep(0.01)
                    restored_settings = window.backend.read_settings()
                    grouping_probe.update(
                        {
                            "mode": "parameter-reset-undo",
                            "reset_scene_default": (
                                reset_settings.target_count == defaults.target_count
                                and reset_settings.seed == defaults.seed
                                and reset_settings.spacing_factor
                                == defaults.spacing_factor
                                and reset_settings.relax_iterations
                                == defaults.relax_iterations
                                and reset_settings.relax_strength
                                == defaults.relax_strength
                            ),
                            "undo_scene_restored": (
                                restored_settings == baseline_settings
                            ),
                            "undo_ui_restored": (
                                window.target_count.value() == probe_count
                            ),
                            "undo_chunk_closed": not window._parameter_undo_open,
                        }
                    )
                    assert grouping_probe["reset_scene_default"]
                    assert grouping_probe["undo_scene_restored"]
                    assert grouping_probe["undo_ui_restored"]
                    assert grouping_probe["undo_chunk_closed"]
                    return
                if args.group_selection in {
                    "outliner", "type-links", "type-link-undo"
                }:
                    from dataclasses import replace

                    guide_node = selected_nodes[0]
                    other_node = selected_nodes[1]
                    item = window._guide_tree_items_by_node[guide_node]
                    other_item = window._guide_tree_items_by_node[other_node]
                    previous_name = window._guide_data_by_node[guide_node].name
                    original_types = list(window._scale_types)
                    probe_type = replace(
                        original_types[0],
                        name="Linked Type Probe",
                        guide_id=(
                            ""
                            if args.group_selection == "type-link-undo"
                            else window._guide_data_by_node[guide_node].guide_id
                        ),
                        use_custom_color=True,
                        color_r=0.2, color_g=0.7, color_b=0.4,
                    )
                    window._scale_types = [probe_type]
                    window._refresh_scale_type_list(select_row=0)
                    if args.group_selection == "type-link-undo":
                        window.guide_search.clear()
                        window.guide_tree.clearSelection()
                        window.guide_tree.setCurrentItem(item)
                        item.setSelected(True)
                        window._refresh_guide_type_combo()
                        # Establish an undo-neutral Scene baseline so this probe
                        # measures only the user-authored link assignment.
                        window.backend.persist_settings(window._snapshot())
                        baseline_types = list(
                            window.backend.read_settings().scale_types
                        )
                        window._assign_current_scale_type()
                        apply_deadline = time.monotonic() + 8.0
                        while (
                            window._parameter_undo_open
                            and time.monotonic() < apply_deadline
                        ):
                            QtWidgets.QApplication.processEvents()
                            time.sleep(0.01)
                        assigned_types = list(
                            window.backend.read_settings().scale_types
                        )
                        cmds.undo()
                        undo_deadline = time.monotonic() + 0.75
                        while time.monotonic() < undo_deadline:
                            QtWidgets.QApplication.processEvents()
                            time.sleep(0.01)
                        restored_types = list(
                            window.backend.read_settings().scale_types
                        )
                        grouping_probe.update(
                            {
                                "mode": "type-link-undo",
                                "assigned_scene": (
                                    len(assigned_types) == 1
                                    and assigned_types[0].guide_id
                                    == window._guide_data_by_node[guide_node].guide_id
                                ),
                                "undo_scene_restored": restored_types == baseline_types,
                                "undo_ui_restored": window._scale_types == baseline_types,
                                "undo_chunk_closed": not window._parameter_undo_open,
                            }
                        )
                        assert grouping_probe["assigned_scene"]
                        assert grouping_probe["undo_scene_restored"]
                        assert grouping_probe["undo_ui_restored"]
                        assert grouping_probe["undo_chunk_closed"]
                        return
                    if args.group_selection == "type-links":
                        grouping_probe["type_link_display"] = item.text(4)
                        window.guide_search.setText("Linked Type Probe")
                        grouping_probe["type_search_matches"] = not item.isHidden()
                        grouping_probe["type_search_excludes_other"] = other_item.isHidden()
                        window.guide_search.clear()
                        window.guide_tree.clearSelection()
                        window.guide_tree.setCurrentItem(item)
                        item.setSelected(True)
                        window._refresh_guide_type_combo()
                        grouping_probe["guide_combo_linked"] = (
                            "Linked here" in window.guide_type_combo.currentText()
                        )
                        original_parameter_changed = window._parameter_changed
                        link_changes = []
                        window._parameter_changed = (
                            lambda category, settle=False: link_changes.append(
                                (category, settle)
                            )
                        )
                        try:
                            window._unassign_current_scale_type()
                            grouping_probe["unassigned"] = (
                                window._scale_types[0].guide_id == ""
                            )
                            window._assign_current_scale_type()
                            grouping_probe["assigned"] = (
                                window._scale_types[0].guide_id
                                == window._guide_data_by_node[guide_node].guide_id
                            )
                            window._filter_guides_for_scale_type()
                            grouping_probe["filter_opened_guides"] = (
                                window.tabs.currentWidget() is window.guides_tab
                                and not item.isHidden()
                                and other_item.isHidden()
                            )
                            window._jump_to_scale_type_link()
                            grouping_probe["jump_selected_target"] = (
                                window._guide_item_node(
                                    window.guide_tree.currentItem()
                                )
                                == guide_node
                            )
                        finally:
                            window._parameter_changed = original_parameter_changed
                            window._scale_types = original_types
                            window._refresh_scale_type_list(select_row=0)
                            window.guide_search.clear()
                        assert grouping_probe["type_link_display"] == "Linked Type Probe"
                        assert grouping_probe["type_search_matches"]
                        assert grouping_probe["type_search_excludes_other"]
                        assert grouping_probe["guide_combo_linked"]
                        assert grouping_probe["unassigned"]
                        assert grouping_probe["assigned"]
                        assert grouping_probe["filter_opened_guides"]
                        assert grouping_probe["jump_selected_target"]
                        assert len(link_changes) == 2
                        grouping_probe["mode"] = "type-links"
                        return
                    window._scale_types = original_types
                    window._refresh_scale_type_list(select_row=0)
                    window.guide_search.clear()
                    probe_name = "Outliner Rename Probe"
                    item.setText(0, probe_name)
                    QtWidgets.QApplication.processEvents()
                    renamed = window.backend.read_guide(guide_node).name

                    item.setCheckState(2, QtCore.Qt.Unchecked)
                    QtWidgets.QApplication.processEvents()
                    visible_after = window.backend.guide_item_presentation_state()[
                        guide_node
                    ][0]

                    grouping_probe["lock_initial"] = window.backend.guide_item_presentation_state()[guide_node][1]
                    grouping_probe["status_before"] = status_before
                    grouping_probe["undo_before_lock"] = cmds.undoInfo(query=True, undoName=True)
                    item.setCheckState(3, QtCore.Qt.Checked)
                    QtWidgets.QApplication.processEvents()
                    locked_after = window.backend.guide_item_presentation_state()[
                        guide_node
                    ][1]
                    grouping_probe["undo_after_lock"] = cmds.undoInfo(query=True, undoName=True)

                    cmds.undo()
                    grouping_probe["redo_empty_immediate"] = cmds.undoInfo(query=True, redoQueueEmpty=True)
                    undo_deadline = time.monotonic() + 0.35
                    while time.monotonic() < undo_deadline:
                        QtWidgets.QApplication.processEvents()
                        time.sleep(0.01)
                    item = window._guide_tree_items_by_node[guide_node]
                    lock_undo_scene = window.backend.guide_item_presentation_state()[
                        guide_node
                    ][1]
                    lock_undo_ui_synced = (
                        item.checkState(3) == QtCore.Qt.Unchecked
                    )

                    grouping_probe["redo_empty_settled"] = cmds.undoInfo(query=True, redoQueueEmpty=True)
                    grouping_probe["undo_after_settled"] = cmds.undoInfo(query=True, undoName=True)
                    cmds.redo()
                    redo_deadline = time.monotonic() + 0.35
                    while time.monotonic() < redo_deadline:
                        QtWidgets.QApplication.processEvents()
                        time.sleep(0.01)
                    item = window._guide_tree_items_by_node[guide_node]
                    lock_redo_scene = window.backend.guide_item_presentation_state()[
                        guide_node
                    ][1]
                    lock_redo_ui_synced = (
                        item.checkState(3) == QtCore.Qt.Checked
                    )

                    cmds.undo()
                    restore_lock_deadline = time.monotonic() + 0.35
                    while time.monotonic() < restore_lock_deadline:
                        QtWidgets.QApplication.processEvents()
                        time.sleep(0.01)
                    item = window._guide_tree_items_by_node[guide_node]
                    other_item = window._guide_tree_items_by_node[other_node]
                    window.guide_search.setText(probe_name)
                    QtWidgets.QApplication.processEvents()
                    grouping_probe.update(
                        {
                            "mode": "outliner",
                            "renamed": renamed,
                            "rename_matches": renamed == probe_name,
                            "visible_after": visible_after,
                            "locked_after": locked_after,
                            "lock_undo_scene": lock_undo_scene,
                            "lock_undo_ui_synced": lock_undo_ui_synced,
                            "lock_redo_scene": lock_redo_scene,
                            "lock_redo_ui_synced": lock_redo_ui_synced,
                            "messages": window.log.toPlainText().splitlines(),
                            "matched_item_visible": not item.isHidden(),
                            "other_item_hidden": other_item.isHidden(),
                            "parent_visible": (
                                item.parent() is None
                                or not item.parent().isHidden()
                            ),
                            "status_before": status_before,
                            "status": window.status_label.text(),
                        }
                    )

                    window.guide_search.clear()
                    item.setCheckState(2, QtCore.Qt.Checked)
                    item.setText(0, previous_name)
                    QtWidgets.QApplication.processEvents()
                    return
                if args.group_selection == "nested":
                    if len(before_groups) < 2:
                        raise RuntimeError("Not enough Guide Groups for nesting measurement")
                    parent_before, child_before = before_groups[:2]
                    parent_id = window._guide_group_data_by_node[parent_before].group_id
                    child_id = window._guide_group_data_by_node[child_before].group_id
                    parent_item = window._guide_tree_items_by_node[parent_before]
                    child_item = window._guide_tree_items_by_node[child_before]
                    old_parent = child_item.parent()
                    if old_parent is None:
                        window.guide_tree.takeTopLevelItem(
                            window.guide_tree.indexOfTopLevelItem(child_item)
                        )
                    else:
                        old_parent.takeChild(old_parent.indexOfChild(child_item))
                    parent_item.addChild(child_item)
                    window._apply_guide_tree_layout_from_ui()

                    current_groups = {
                        data.group_id: node
                        for node, data in window._guide_group_data_by_node.items()
                    }
                    parent_node = current_groups[parent_id]
                    child_node = current_groups[child_id]
                    layout = window.backend.guide_group_layout_state()
                    parent_item = window._guide_tree_items_by_node[parent_node]
                    parent_item.setExpanded(True)
                    parent_item.setExpanded(False)
                    QtWidgets.QApplication.processEvents()
                    collapsed_saved = window.backend.guide_group_collapsed(parent_node)
                    reload_scene = args.output.with_name(
                        args.output.stem + "-nested-reload.mb"
                    ).resolve()
                    cmds.file(rename=str(reload_scene))
                    cmds.file(save=True, type="mayaBinary", force=True)
                    cmds.file(
                        str(reload_scene),
                        open=True,
                        force=True,
                        prompt=False,
                        ignoreVersion=True,
                    )
                    window.backend.bind(args.settings)
                    window._refresh_guides(preferred=parent_id)
                    current_groups = {
                        data.group_id: node
                        for node, data in window._guide_group_data_by_node.items()
                    }
                    parent_node = current_groups[parent_id]
                    child_node = current_groups[child_id]
                    parent_item = window._guide_tree_items_by_node[parent_node]
                    child_item = window._guide_tree_items_by_node[child_node]
                    grouping_probe.update(
                        {
                            "mode": "nested",
                            "parent_id": parent_id,
                            "child_id": child_id,
                            "scene_parent": layout[child_node][0],
                            "scene_nested": layout[child_node][0] == parent_node,
                            "ui_nested_after_reload": child_item.parent() is parent_item,
                            "collapsed_saved": collapsed_saved,
                            "collapsed_after_reload": not parent_item.isExpanded(),
                            "scene_path_after_reload": cmds.file(
                                query=True, sceneName=True
                            ),
                            "scene_reloaded": Path(
                                cmds.file(query=True, sceneName=True)
                            ).resolve()
                            == reload_scene,
                            "status_before": status_before,
                            "status": window.status_label.text(),
                        }
                    )
                    return
                before_nodes = current_nodes_by_id()
                before_parents = {
                    guide_id: cmds.listRelatives(node, parent=True, fullPath=True)
                    for guide_id, node in before_nodes.items()
                }
                if args.group_selection == "mixed":
                    requested = [selected_nodes[0], window.backend.binding.target_mesh]
                else:
                    requested = list(selected_nodes)
                cmds.select(requested, replace=True)
                if args.group_selection == "button":
                    window._sync_guide_selection_from_maya()
                    window._create_guide_group()
                    handled = True
                else:
                    event = QtGui.QKeyEvent(
                        QtCore.QEvent.KeyPress,
                        QtCore.Qt.Key_G,
                        QtCore.Qt.ControlModifier,
                    )
                    handled = bool(QtWidgets.QApplication.sendEvent(window, event))
                after_groups = window.backend.list_guide_groups()
                added_groups = [
                    group for group in after_groups if group not in before_groups
                ]
                after_nodes = current_nodes_by_id()
                grouping_probe.update(
                    {
                        "mode": args.group_selection,
                        "requested": requested,
                        "handled": handled,
                        "status_before": status_before,
                        "groups_added": len(added_groups),
                        "before_parents": before_parents,
                        "after_parents": {
                            guide_id: cmds.listRelatives(
                                node, parent=True, fullPath=True
                            )
                            for guide_id, node in after_nodes.items()
                        },
                        "maya_selection": window.backend.selected_guide_items(),
                        "ui_groups_present": all(
                            group in window._guide_tree_items_by_node
                            for group in added_groups
                        ),
                        "status": window.status_label.text(),
                    }
                )
            except Exception as exc:
                grouping_probe.update(
                    {
                        "mode": args.group_selection,
                        "error": "{}: {}".format(type(exc).__name__, exc),
                    }
                )

        QtCore.QTimer.singleShot(100, trigger_grouping)
    loop = QtCore.QEventLoop()
    duration_seconds = max(
        args.ui_idle_seconds,
        0.5 + args.camera_steps * 0.15 if args.camera_steps else 0.0,
        1.0 if args.select_guide_count else 0.0,
        2.5 if args.group_selection else 0.0,
        10.0 if args.auto_budget_probe else 0.0,
    )
    QtCore.QTimer.singleShot(max(1, int(duration_seconds * 1000.0)), loop.quit)
    try:
        run_loop = getattr(loop, "exec", None) or loop.exec_
        run_loop()
        binding_active = bool(window.backend.binding)
        guide_timer_active = window._guide_poll.isActive()
        scene_timer_active = window._scene_poll.isActive()
        guide_callback_count = len(window._guide_callback_ids)
        scene_callback_count = len(window._scene_callback_ids)
        counter_after = window.backend.native._execution_counter(graph)
        if args.auto_budget_probe and not auto_budget_probe.get("error"):
            finished = auto_budget_probe["finished"]
            interactive = next(
                (item for item in finished if item["mode"] == "interactive"),
                None,
            )
            settled_item = next(
                (item for item in finished if item["mode"] == "settled"),
                None,
            )
            auto_budget_probe.update(
                {
                    "final_budget": window.interactive_budget.value(),
                    "reason": window.auto_preview_budget_label.text(),
                    "passed": bool(
                        interactive
                        and settled_item
                        and interactive["widget_budget"] == initial_budget
                        and settled_item["widget_budget"]
                        == interactive["next_budget"]
                        and all(
                            item["settled_budget"] == settled_budget
                            for item in finished
                        )
                    ),
                }
            )
    finally:
        if camera_restore is not None:
            camera, rotation = camera_restore
            window.backend.scene.cmds.setAttr(camera + ".rotate", *rotation)
        window.close()
        backend_type.poll_guide_state = original_poll
        backend_type.apply = original_apply
        BifrostScalesWindow._poll_guide_changes = original_guide_tick
        BifrostScalesWindow._guide_node_dirtied = original_guide_dirty
        BifrostScalesWindow._guide_attribute_changed = original_guide_attribute
        BifrostScalesWindow._poll_scene_selection_and_tool = original_scene_tick
    result = {
        "schema": "bifrost-scales/maya-ui-idle/1",
        "duration_seconds": duration_seconds,
        "binding": binding_active,
        "settings": window.backend.binding.settings_node,
        "graph": graph,
        "scales": snapshot.scale_count,
        "points": snapshot.point_count,
        "faces": snapshot.face_count,
        "execution_counter_before": counter_before,
        "execution_counter_after": counter_after,
        "guide_timer_active": guide_timer_active,
        "guide_callback_count": guide_callback_count,
        "guide_touched": guide_touched[0],
        "scene_timer_active": scene_timer_active,
        "scene_callback_count": scene_callback_count,
        "poll_calls": len(poll_times),
        "poll_total_ms": round(sum(poll_times), 3),
        "max_poll_ms": round(max(poll_times, default=0.0), 3),
        "guide_tick_calls": len(guide_tick_times),
        "max_guide_tick_ms": round(max(guide_tick_times, default=0.0), 3),
        "scene_tick_calls": len(scene_tick_times),
        "max_scene_tick_ms": round(max(scene_tick_times, default=0.0), 3),
        "guide_dirty_calls": guide_dirty_calls[0],
        "guide_attribute_events": [
            {"message": message, "plug": plug}
            for message, plug in guide_attribute_events[:40]
        ],
        "guide_attribute_event_count": len(guide_attribute_events),
        "apply_calls": len(apply_times),
        "apply_modes": apply_modes,
        "apply_total_ms": round(sum(apply_times), 3),
        "camera_steps": args.camera_steps,
        "camera_steps_completed": len(camera_refresh_times),
        "camera_refresh_total_ms": round(sum(camera_refresh_times), 3),
        "camera_refresh_max_ms": round(max(camera_refresh_times, default=0.0), 3),
        "selection_probe": selection_probe,
        "grouping_probe": grouping_probe,
        "auto_budget_probe": auto_budget_probe,
        "ui_screenshot": ui_screenshot,
        "ui_focus_confirmed": ui_focus_confirmed,
    }
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True)
    args.output.resolve().write_text(encoded + "\n", encoding="utf-8")
    print(encoded, flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--settings")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--maya",
        type=Path,
        default=Path(
            os.environ.get("MAYA_LOCATION", r"C:\Program Files\Autodesk\Maya2026")
        )
        / "bin"
        / "maya.exe",
    )
    parser.add_argument("--inside-maya", action="store_true")
    parser.add_argument("--scene-preopened", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--source-runtime", action="store_true")
    parser.add_argument("--warmup", action="store_true")
    parser.add_argument("--ui-idle-seconds", type=float, default=0.0)
    parser.add_argument("--touch-guide", action="store_true")
    parser.add_argument("--camera-steps", type=int, default=0)
    parser.add_argument("--select-guide-count", type=int, default=0)
    parser.add_argument("--ui-screenshot", type=Path)
    parser.add_argument(
        "--ui-screenshot-section", choices=("top", "shape"), default="top"
    )
    parser.add_argument("--auto-budget-probe", action="store_true")
    parser.add_argument("--stable-id-probe", action="store_true")
    parser.add_argument(
        "--group-selection",
        choices=(
            "button", "pure", "mixed", "nested", "outliner",
            "type-links", "type-link-undo", "parameter-reset-undo",
        ),
        default="",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if not args.inside_maya:
        return _launch_maya(args, Path(__file__).resolve())
    _mark("maya_ui_ready")
    import maya.cmds as cmds

    if not args.scene_preopened:
        cmds.loadPlugin("bifrostGraph", quiet=True)
        cmds.file(
            str(args.scene.resolve()), open=True, force=True, prompt=False,
            ignoreVersion=True, executeScriptNodes=False, loadReferenceDepth="none",
        )
    _mark("scene_opened")
    scripts = Path(__file__).resolve().parents[1] / "BifrostScales" / "scripts"
    if args.source_runtime:
        sys.path.insert(0, str(scripts))
    from bifrost_scales.backend import NativeMayaBackend
    from bifrost_scales.scheduler import ChangeCategory
    if args.source_runtime:
        from bifrost_scales import native_backend

        pack_configs = sorted(
            (scripts.parent / "bifrost" / "pack").glob(
                "*/BifrostScalesPackConfig.json"
            )
        )
        if len(pack_configs) != 1:
            raise RuntimeError(
                "Expected one source PackConfig, found {}".format(len(pack_configs))
            )
        pack_config = pack_configs[0]
        native_backend._registered_pack_configs = lambda _root: (pack_config,)
        os.environ["BIFROST_LIB_CONFIG_FILES"] = str(pack_config)
    if (
        args.ui_idle_seconds > 0.0
        or args.camera_steps > 0
        or args.select_guide_count > 0
        or bool(args.group_selection)
        or args.auto_budget_probe
        or args.ui_screenshot is not None
    ):
        return _measure_ui_idle(args, NativeMayaBackend)
    backend = NativeMayaBackend()
    systems = [args.settings] if args.settings else backend.list_systems()
    if not systems:
        raise RuntimeError("The scene contains no Bifrost Scales system")
    bind_errors = []
    for system in systems:
        try:
            backend._binding = backend.scene.bind(system)
            backend._reset_authoring_caches()
            break
        except Exception as exc:
            bind_errors.append("{}: {}".format(system, exc))
    else:
        raise RuntimeError("No valid system: {}".format("; ".join(bind_errors)))
    loaded_settings = backend.read_settings()
    settings = loaded_settings.to_mapping()
    warmup = None
    if args.warmup:
        started_at = time.monotonic()
        report = backend.apply(
            backend._request_for_settings(loaded_settings, mode="settled", revision=0)
        )
        warmup = {
            "main_thread_block_ms": round(
                (time.monotonic() - started_at) * 1000.0, 3
            ),
            "backend_total_ms": round(float(report.total_ms), 3),
        }
    from bifrost_scales.parameter_controls import FloatParameterControl
    from bifrost_scales.qt_compat import QtCore, QtGui, QtWidgets
    from bifrost_scales.qt_scheduler import QtPreviewScheduler
    from bifrost_scales.ui import BifrostScalesWindow
    _mark("ui_imported")

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    _mark("application_ready")
    control = FloatParameterControl(
        0.000001,
        1000000.0,
        float(settings["size"]),
        decimals=6,
        single_step=0.01,
        mapping="log",
    )
    scheduler = QtPreviewScheduler(backend)
    _mark("measurement_path_ready")

    graph = backend.native.graph_for_system(backend.binding)

    def output_snapshot():
        payload = str(cmds.getAttr(graph + ".payload_json") or "")
        snapshot = backend.native._read_output_snapshot(graph)
        return {
            "graph": graph,
            "payload_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            "execution_counter": backend.native._execution_counter(graph),
            "success": snapshot.success,
            "status": snapshot.status,
            "scales": snapshot.scale_count,
            "points": snapshot.point_count,
            "faces": snapshot.face_count,
        }
    metrics = {
        "schema": "bifrost-scales/maya-slider-drag/1",
        "scene": str(args.scene.resolve()),
        "control": "size",
        "settings": backend.binding.settings_node,
        "warmup": warmup,
        "value_callbacks": 0,
        "requests": [],
        "statuses": [],
        "failures": [],
        "undo_open": 0,
        "undo_close": 0,
    }
    metrics["initial_output"] = output_snapshot()
    scheduler.status_changed.connect(
        lambda status: metrics["statuses"].append(str(status))
    )
    started = {}
    phase_times = {}

    def timed_phase(name, function):
        def measured(*call_args, **call_kwargs):
            phase_started = time.monotonic()
            try:
                return function(*call_args, **call_kwargs)
            finally:
                phase_times[name] = round(
                    (time.monotonic() - phase_started) * 1000.0, 3
                )

        return measured

    backend.scene.write_settings = timed_phase(
        "write_settings", backend.scene.write_settings
    )
    backend.read_guides = timed_phase("read_guides", backend.read_guides)
    backend.native.evaluate = timed_phase("native_evaluate", backend.native.evaluate)
    backend.scene.set_stats = timed_phase("set_stats", backend.scene.set_stats)

    interaction = type("InteractionHost", (), {})()
    interaction._updating_widgets = False
    interaction._parameter_undo_open = False
    interaction._guide_undo_open = False
    interaction.auto_preview = SimpleNamespace(isChecked=lambda: True)
    interaction.backend = backend
    interaction.scheduler = scheduler
    interaction._inactivity = SimpleNamespace(
        stop=lambda: None, start=lambda _delay: None
    )
    interaction.settled_delay = SimpleNamespace(value=lambda: 180)
    interaction._snapshot = lambda: dict(settings)
    interaction._begin_interaction = MethodType(
        BifrostScalesWindow._begin_interaction, interaction
    )
    interaction._finish_interaction = MethodType(
        BifrostScalesWindow._finish_interaction, interaction
    )
    interaction._close_parameter_undo = MethodType(
        BifrostScalesWindow._close_parameter_undo, interaction
    )
    interaction._parameter_changed = MethodType(
        BifrostScalesWindow._parameter_changed, interaction
    )

    def value_changed(value):
        metrics["value_callbacks"] += 1
        settings["size"] = float(value)
        interaction._parameter_changed(ChangeCategory.SHAPE)

    control.valueChanged.connect(value_changed)
    control.interactionStarted.connect(interaction._begin_interaction)
    control.interactionFinished.connect(interaction._finish_interaction)

    def request_started(revision, mode):
        phase_times.clear()
        started[int(revision)] = time.monotonic()

    def request_finished(revision, mode, report):
        elapsed_ms = (time.monotonic() - started.pop(int(revision))) * 1000.0
        metrics["requests"].append(
            {
                "revision": int(revision),
                "mode": str(mode),
                "main_thread_block_ms": round(elapsed_ms, 3),
                "backend_total_ms": round(float(report.total_ms), 3),
                "generation_ms": round(float(report.generation_ms), 3),
                "viewport_ms": round(float(report.viewport_ms), 3),
                "host_phases_ms": dict(phase_times),
            }
        )
        if str(mode) == "settled":
            interaction._close_parameter_undo()

    scheduler.request_started.connect(request_started)
    scheduler.request_finished.connect(request_finished)
    scheduler.request_failed.connect(
        lambda revision, message: metrics["failures"].append(
            {"revision": int(revision), "message": str(message)}
        )
    )
    begin_undo = backend.begin_undo_chunk
    end_undo = backend.end_undo_chunk

    def measured_begin_undo(*begin_args, **begin_kwargs):
        metrics["undo_open"] += 1
        return begin_undo(*begin_args, **begin_kwargs)

    def measured_end_undo(*end_args, **end_kwargs):
        metrics["undo_close"] += 1
        return end_undo(*end_args, **end_kwargs)

    backend.begin_undo_chunk = measured_begin_undo
    backend.end_undo_chunk = measured_end_undo

    initial_value = float(settings["size"])
    metrics["initial_size"] = initial_value
    initial = int(control.slider.value())
    maximum = int(control.slider.maximum())
    minimum = int(control.slider.minimum())
    direction = -1 if initial + 40 > maximum else 1
    positions = [
        max(minimum, min(maximum, initial + direction * offset))
        for offset in (10, 20, 30, 40)
    ]

    control.slider.sliderPressed.emit()
    _mark("drag_started")
    for position in positions:
        control.slider.setValue(position)
        app.processEvents()
        time.sleep(0.02)

    interactive_deadline = time.monotonic() + args.timeout
    while not any(item["mode"] == "interactive" for item in metrics["requests"]):
        if metrics["failures"]:
            raise RuntimeError(metrics["failures"][-1]["message"])
        if time.monotonic() >= interactive_deadline:
            raise TimeoutError("Interactive evaluation did not complete")
        app.processEvents()
        time.sleep(0.005)

    control.slider.sliderReleased.emit()
    _mark("drag_released")
    settled_deadline = time.monotonic() + args.timeout
    while not any(item["mode"] == "settled" for item in metrics["requests"]):
        if time.monotonic() >= settled_deadline:
            raise TimeoutError("Settled evaluation did not complete")
        app.processEvents()
        time.sleep(0.005)

    metrics["interactive_requests"] = sum(
        item["mode"] == "interactive" for item in metrics["requests"]
    )
    metrics["settled_requests"] = sum(
        item["mode"] == "settled" for item in metrics["requests"]
    )
    expected_statuses = (
        "Editing",
        "Interactive pending",
        "Interactive evaluating",
        "Interactive ready",
        "Settled pending",
        "Settled evaluating",
        "Settled complete",
    )
    status_index = 0
    for status in metrics["statuses"]:
        if status.startswith(expected_statuses[status_index]):
            status_index += 1
            if status_index == len(expected_statuses):
                break
    metrics["status_contract"] = status_index == len(expected_statuses)
    metrics["max_main_thread_block_ms"] = max(
        item["main_thread_block_ms"] for item in metrics["requests"]
    )
    metrics["final_size"] = float(backend.read_settings().size)
    metrics["final_output"] = output_snapshot()
    metrics["undo_value_restored"] = False
    if metrics["undo_open"] == 1 and metrics["undo_close"] == 1:
        metrics["undo_name"] = str(cmds.undoInfo(query=True, undoName=True) or "")
        cmds.undo()
        restored = float(backend.read_settings().size)
        metrics["undo_restored_size"] = restored
        metrics["undo_value_restored"] = abs(restored - initial_value) <= 1.0e-12
        undo_deadline = time.monotonic() + args.timeout
        while True:
            app.processEvents()
            undo_output = output_snapshot()
            if (
                undo_output["payload_sha256"]
                == metrics["initial_output"]["payload_sha256"]
                and undo_output["success"]
                and undo_output["execution_counter"] is not None
                and undo_output["execution_counter"]
                > metrics["final_output"]["execution_counter"]
            ):
                break
            if time.monotonic() >= undo_deadline:
                break
            time.sleep(0.005)
        metrics["undo_output"] = undo_output
        metrics["undo_output_restored"] = (
            undo_output["payload_sha256"]
            == metrics["initial_output"]["payload_sha256"]
            and undo_output["success"]
            and undo_output["execution_counter"] is not None
            and undo_output["execution_counter"]
            > metrics["final_output"]["execution_counter"]
            and undo_output["scales"] == metrics["initial_output"]["scales"]
            and undo_output["points"] == metrics["initial_output"]["points"]
            and undo_output["faces"] == metrics["initial_output"]["faces"]
        )
    if args.stable_id_probe:
        ids = []
        for start in range(0, metrics["initial_output"]["scales"], 4096):
            metadata = backend.cell_metadata_for_indices(
                tuple(range(start, min(start + 4096, metrics["initial_output"]["scales"]))),
                settings=backend.read_settings(),
            )
            ids.extend(item.cell_id for item in metadata)
        encoded_ids = "\n".join("{:016x}".format(value) for value in ids).encode("ascii")
        metrics["stable_id_probe"] = {
            "count": len(ids),
            "unique": len(set(ids)),
            "sha256": hashlib.sha256(encoded_ids).hexdigest(),
        }
    result = json.dumps(metrics, ensure_ascii=False, sort_keys=True)
    if args.output:
        args.output.resolve().write_text(result + "\n", encoding="utf-8")
    print(result, flush=True)
    _mark("complete")
    control.close()
    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
    except Exception as exc:
        failure = {
            "schema": "bifrost-scales/maya-slider-drag/1",
            "error": "{}: {}".format(type(exc).__name__, exc),
            "traceback": traceback.format_exc(),
        }
        if "--output" in sys.argv:
            output_index = sys.argv.index("--output") + 1
            if output_index < len(sys.argv):
                Path(sys.argv[output_index]).resolve().write_text(
                    json.dumps(failure, ensure_ascii=False, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
        traceback.print_exc()
        exit_code = 1
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exit_code)
