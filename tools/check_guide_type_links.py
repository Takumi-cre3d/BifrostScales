"""Check the real Outliner Qt methods without opening a Maya scene.

Run with Maya's mayapy.exe. Pass --installed to check the installed runtime.
"""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import sys

if "--installed" not in sys.argv:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "BifrostScales/scripts"))

from bifrost_scales.qt_compat import QtCore, QtWidgets
from bifrost_scales.settings import ScaleTypeSettings
from bifrost_scales.ui import BifrostScalesWindow


def main():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    tree = QtWidgets.QTreeWidget()
    tree.setColumnCount(5)
    group = QtWidgets.QTreeWidgetItem(tree, ["Group"])
    guide = QtWidgets.QTreeWidgetItem(group, ["Guide"])
    other = QtWidgets.QTreeWidgetItem(tree, ["Other"])
    search = QtWidgets.QLineEdit()
    guide_type_combo = QtWidgets.QComboBox()
    scale_type_list = QtWidgets.QListWidget()
    scale_type_list.addItem("Type")
    scale_type_list.setCurrentRow(0)
    tabs = QtWidgets.QTabWidget()
    guides_tab = QtWidgets.QWidget()
    scale_types_tab = QtWidgets.QWidget()
    tabs.addTab(guides_tab, "Guides")
    tabs.addTab(scale_types_tab, "Scale Types")
    tree.setCurrentItem(guide)
    nodes = {group: "group", guide: "guide", other: "other"}
    calls = []
    state = SimpleNamespace(
        guide_tree=tree,
        guide_search=search,
        guide_type_combo=guide_type_combo,
        assign_guide_type_button=QtWidgets.QPushButton(),
        unassign_guide_type_button=QtWidgets.QPushButton(),
        scale_type_list=scale_type_list,
        filter_type_link_button=QtWidgets.QPushButton(),
        jump_type_link_button=QtWidgets.QPushButton(),
        tabs=tabs,
        guides_tab=guides_tab,
        _guide_tree_items_by_node={"group": group, "guide": guide, "other": other},
        _guide_group_data_by_node={"group": SimpleNamespace(group_id="group-id")},
        _guide_data_by_node={
            "guide": SimpleNamespace(guide_id="guide-id", group_id="group-id"),
            "other": SimpleNamespace(guide_id="other-id", group_id=""),
        },
        _preview_color=(0.3, 0.4, 0.5),
        _guide_link_undo_sync=False,
        _append=lambda message: None,
    )
    state._current_guide_item = tree.currentItem
    state._guide_item_node = lambda item: nodes.get(item, "")
    state._current_guide_item_id = lambda: {
        guide: "guide-id", group: "group-id", other: "other-id"
    }.get(tree.currentItem(), "")
    state._guide_item_node_for_id = lambda identifier: (
        BifrostScalesWindow._guide_item_node_for_id(state, identifier)
    )
    state._guide_type_selection_changed = lambda *args: (
        BifrostScalesWindow._guide_type_selection_changed(state, *args)
    )
    state._refresh_guide_type_combo = lambda: (
        BifrostScalesWindow._refresh_guide_type_combo(state)
    )
    state._filter_guide_tree = lambda text: BifrostScalesWindow._filter_guide_tree(
        state, text
    )
    refresh = lambda: BifrostScalesWindow._refresh_guide_type_links(state)
    source = ScaleTypeSettings(
        name="Direct", guide_id="guide-id", use_custom_color=True,
        color_r=0.2, color_g=0.7, color_b=0.4,
    )
    state._scale_types = [source]
    changes = []
    tree.itemChanged.connect(lambda *args: changes.append(args))
    refresh()
    assert guide.text(4) == "Direct"
    assert other.text(4) == "Unassigned"
    assert abs(guide.foreground(4).color().greenF() - 0.7) < 0.001
    search.setText("Direct")
    refresh()
    assert not guide.isHidden() and not group.isHidden() and other.isHidden()
    state._scale_types = [
        replace(source, name="Renamed"),
        replace(source, name="Shared", guide_id="group-id", enabled=False),
    ]
    search.clear()
    refresh()
    assert guide.text(4) == "Renamed, Shared [Group] [OFF]"
    assert group.text(4) == "Shared [OFF]"
    state._scale_types = []
    refresh()
    assert guide.text(4) == "Unassigned"
    assert guide.foreground(4).style() == QtCore.Qt.NoBrush

    state._scale_types = [replace(source, guide_id="")]
    state._refresh_scale_type_list = lambda select_row=0: refresh()
    state._parameter_changed = lambda category, settle=False: calls.append(
        (category, settle)
    )
    state._set_scale_type_link = lambda row, identifier: (
        BifrostScalesWindow._set_scale_type_link(state, row, identifier)
    )
    refresh()
    BifrostScalesWindow._assign_current_scale_type(state)
    assert state._scale_types[0].guide_id == "guide-id"
    BifrostScalesWindow._unassign_current_scale_type(state)
    assert state._scale_types[0].guide_id == ""
    assert len(calls) == 2 and all(settle for _category, settle in calls)

    state._scale_types = [source]
    refresh()
    BifrostScalesWindow._filter_guides_for_scale_type(state)
    assert search.text() == "Direct" and tabs.currentWidget() is guides_tab
    tabs.setCurrentWidget(scale_types_tab)
    BifrostScalesWindow._jump_to_scale_type_link(state)
    assert tree.currentItem() is guide and tabs.currentWidget() is guides_tab
    assert not changes, "Presentation updates must not emit itemChanged"
    print("Guide Type links: display/assign/unassign/filter/jump/signals PASS")
    tree.close()
    app.processEvents()


if __name__ == "__main__":
    main()
