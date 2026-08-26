"""Standalone Bifrost Scales Maya UI."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, replace
from typing import Any

from . import draw_context
from .backend import NativeMayaBackend
from .diagnostics import probe_environment
from .guides import GuideKind
from .legacy_cleanup import remove_legacy_installations, scan_legacy_installations
from .parameter_controls import FloatParameterControl, IntParameterControl
from .qt_compat import QtCore, QtWidgets
from .qt_scheduler import QtPreviewScheduler
from .scheduler import ChangeCategory
from .settings import ScaleSettings, ScaleTypeSettings
from .version import VERSION

_WINDOW = None
_GUIDE_NODE_ROLE = int(QtCore.Qt.UserRole)
_GUIDE_ITEM_KIND_ROLE = _GUIDE_NODE_ROLE + 1


class _GuideTreeWidget(QtWidgets.QTreeWidget):
    """QTreeWidget that reports cross-parent InternalMove drops reliably.

    Qt does not consistently emit ``rowsMoved`` when an item is moved between
    two different parents.  The visible Tree can therefore diverge from the
    Maya DAG/group attribute unless the completed drop itself is observed.
    """

    dropCompleted = QtCore.Signal()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt virtual name
        super().dropEvent(event)
        self.dropCompleted.emit()


class BifrostScalesWindow(QtWidgets.QDialog):
    def __init__(self, parent: Any | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("BifrostScalesStandaloneWindow")
        self.setWindowTitle("Bifrost Scales {}".format(VERSION))
        self.resize(780, 900)
        self.backend = NativeMayaBackend()
        self.scheduler = QtPreviewScheduler(self.backend, parent=self)
        self._inactivity = QtCore.QTimer(self)
        self._inactivity.setSingleShot(True)
        self._inactivity.setInterval(180)
        self._inactivity.timeout.connect(self._finish_interaction)
        self._updating_widgets = False
        self._scale_types = list(ScaleSettings().scale_types)
        self._guide_nodes: list[str] = []
        self._guide_data_by_node = {}
        self._guide_group_nodes: list[str] = []
        self._guide_group_data_by_node = {}
        self._guide_tree_items_by_node = {}
        self._active_draw_kind: GuideKind | None = None
        defaults = ScaleSettings()
        self._preview_color = (defaults.color_r, defaults.color_g, defaults.color_b)
        self._scene_selected_guide_item = ""
        self._syncing_guide_selection = False
        self._guide_tree_drop_pending = False
        self._guide_undo_open = False
        self._guide_link_undo_sync = False
        self._build_ui()
        self._connect_ui()
        self._guide_poll = QtCore.QTimer(self)
        self._guide_poll.setInterval(180)
        self._guide_poll.timeout.connect(self._poll_guide_changes)
        self._guide_poll.start()
        self._scene_poll = QtCore.QTimer(self)
        self._scene_poll.setInterval(80)
        self._scene_poll.timeout.connect(self._poll_scene_selection_and_tool)
        self._scene_poll.start()
        self._refresh_systems()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        title = QtWidgets.QLabel(
            "Native Bifrost engine / Python Reference生成機能は0.10.0で廃止されました"
        )
        title.setWordWrap(True)
        layout.addWidget(title)

        system_group = QtWidgets.QGroupBox("System / Target")
        system_layout = QtWidgets.QGridLayout(system_group)
        self.system_combo = QtWidgets.QComboBox()
        self.refresh_systems_button = QtWidgets.QPushButton("再検索")
        self.create_system_button = QtWidgets.QPushButton("選択メッシュから新規作成（Bifrost Previewまで）")
        self.set_target_button = QtWidgets.QPushButton("選択メッシュへ変更")
        self.refresh_target_button = QtWidgets.QPushButton("Target形状を再読込")
        self.target_label = QtWidgets.QLabel("Target: 未設定")
        self.target_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.target_label.setWordWrap(True)
        system_layout.addWidget(QtWidgets.QLabel("System"), 0, 0)
        system_layout.addWidget(self.system_combo, 0, 1)
        system_layout.addWidget(self.refresh_systems_button, 0, 2)
        system_layout.addWidget(self.create_system_button, 1, 0, 1, 2)
        system_layout.addWidget(self.set_target_button, 1, 2)
        system_layout.addWidget(self.refresh_target_button, 2, 0)
        system_layout.addWidget(self.target_label, 2, 1, 1, 2)
        layout.addWidget(system_group)

        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs, 1)
        self._build_global_tab()
        self._build_guides_tab()
        self._build_scale_types_tab()
        self._build_preview_tab()
        self._build_maintenance_tab()

        action_layout = QtWidgets.QHBoxLayout()
        self.preview_now_button = QtWidgets.QPushButton("Settled Preview")
        self.delete_system_button = QtWidgets.QPushButton("System削除")
        action_layout.addWidget(self.preview_now_button)
        action_layout.addWidget(self.delete_system_button)
        layout.addLayout(action_layout)

        status_group = QtWidgets.QGroupBox("Status")
        status_layout = QtWidgets.QVBoxLayout(status_group)
        self.status_label = QtWidgets.QLabel("Idle")
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        self.log.setMinimumHeight(130)
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.log)
        layout.addWidget(status_group)

    def _global_section(self, title: str, parent_layout):
        group = QtWidgets.QGroupBox(title)
        form = QtWidgets.QFormLayout(group)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        parent_layout.addWidget(group)
        return form

    def _build_global_tab(self) -> None:
        """Build one ordered Global tab for placement, cells, and base shape."""

        tab = QtWidgets.QWidget()
        tab_layout = QtWidgets.QVBoxLayout(tab)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        distribution = self._global_section("1. Distribution / Placement", layout)
        self.target_count = IntParameterControl(1, 50000, 512)
        distribution.addRow("Target Count", self.target_count)
        self.seed = QtWidgets.QSpinBox()
        self.seed.setRange(-2147483647, 2147483647)
        self.seed.setValue(1)
        self.seed.setKeyboardTracking(True)
        distribution.addRow("Seed", self.seed)
        self.spacing_factor = FloatParameterControl(
            0.15, 2.5, 0.82, decimals=3, single_step=0.05
        )
        distribution.addRow("Spacing", self.spacing_factor)
        self.relax_iterations = IntParameterControl(0, 64, 0)
        distribution.addRow("Density Relax Iterations", self.relax_iterations)
        self.relax_strength = FloatParameterControl(
            0.0, 1.0, 0.45, decimals=3, single_step=0.05
        )
        distribution.addRow("Density Relax Strength", self.relax_strength)

        orientation = self._global_section("2. Direction / Flow", layout)
        self.direction = FloatParameterControl(
            -360.0, 360.0, 0.0, decimals=2, single_step=5.0, suffix=" deg"
        )
        orientation.addRow("Global Direction", self.direction)
        self.random_rotation = FloatParameterControl(
            0.0, 180.0, 8.0, decimals=2, single_step=2.0, suffix=" deg"
        )
        orientation.addRow("Random Rotation", self.random_rotation)
        self.direction_relax_iterations = IntParameterControl(0, 64, 0)
        orientation.addRow(
            "Direction Relax Iterations", self.direction_relax_iterations
        )
        self.direction_relax_strength = FloatParameterControl(
            0.0, 1.0, 0.35, decimals=3, single_step=0.05
        )
        orientation.addRow("Direction Relax Strength", self.direction_relax_strength)
        orientation_note = QtWidgets.QLabel(
            "Flow CurveのCV[0]からCV[n]への接線方向を、ウロコの向きへ使用します。"
        )
        orientation_note.setWordWrap(True)
        orientation.addRow(orientation_note)

        cells = self._global_section("3. Cell Partition / Surface", layout)
        self.cell_mode = QtWidgets.QComboBox()
        self.cell_mode.addItem("Auto: 操作中Card / 停止後Cell", "auto")
        self.cell_mode.addItem("Cards only", "cards")
        self.cell_mode.addItem("Cells while dragging", "cells")
        cells.addRow("Preview Geometry", self.cell_mode)
        self.cell_growth = FloatParameterControl(
            0.0, 1.0, 0.85, decimals=3, single_step=0.05
        )
        cells.addRow("Growth", self.cell_growth)
        self.cell_gap = FloatParameterControl(
            0.0, 0.49, 0.06, decimals=3, single_step=0.01
        )
        cells.addRow("Gap / Spacing", self.cell_gap)
        self.cell_collision_margin = FloatParameterControl(
            0.0, 0.49, 0.02, decimals=3, single_step=0.01
        )
        cells.addRow("Collision Margin", self.cell_collision_margin)
        self.cell_radius_multiplier = FloatParameterControl(
            0.35, 6.0, 1.65, decimals=3, single_step=0.05
        )
        cells.addRow("Open Cell Radius Limit", self.cell_radius_multiplier)
        self.cell_direction_anisotropy = FloatParameterControl(
            0.0, 1.0, 0.4, decimals=3, single_step=0.05
        )
        self.cell_direction_anisotropy.setToolTip(
            "0は従来の等方Cell、1はGuide効果内で最大2.25倍の方向性を与えます。"
        )
        cells.addRow("Cell Direction Anisotropy", self.cell_direction_anisotropy)
        self.cell_interactive_resolution = QtWidgets.QSpinBox()
        self.cell_interactive_resolution.setRange(4, 16)
        self.cell_interactive_resolution.setValue(6)
        cells.addRow("Interactive Cell Sides", self.cell_interactive_resolution)
        self.cell_settled_resolution = QtWidgets.QSpinBox()
        self.cell_settled_resolution.setRange(4, 32)
        self.cell_settled_resolution.setValue(10)
        cells.addRow("Settled Cell Sides", self.cell_settled_resolution)
        self.cell_shape_divisions = QtWidgets.QSpinBox()
        self.cell_shape_divisions.setRange(1, 6)
        self.cell_shape_divisions.setValue(2)
        cells.addRow("Interior Divisions", self.cell_shape_divisions)
        self.cell_projection_rings = QtWidgets.QSpinBox()
        self.cell_projection_rings.setRange(0, 16)
        self.cell_projection_rings.setValue(2)
        cells.addRow("Surface Projection Rings", self.cell_projection_rings)
        self.cell_project_to_surface = QtWidgets.QCheckBox(
            "Cell境界をTargetへ再投影"
        )
        self.cell_project_to_surface.setChecked(True)
        cells.addRow(self.cell_project_to_surface)

        shape = self._global_section("4. Base Scale Shape / Appearance", layout)
        self.size = FloatParameterControl(
            0.000001,
            1000000.0,
            0.1,
            decimals=6,
            single_step=0.01,
            mapping="log",
        )
        shape.addRow("Scale Size", self.size)
        self.lift = QtWidgets.QDoubleSpinBox()
        self.lift.setRange(-1000000.0, 1000000.0)
        self.lift.setDecimals(6)
        self.lift.setSingleStep(0.001)
        self.lift.setValue(0.002)
        self.lift.setKeyboardTracking(True)
        shape.addRow("Surface Lift", self.lift)
        self.curvature = FloatParameterControl(
            -4.0, 4.0, 0.22, decimals=3, single_step=0.05
        )
        shape.addRow("Curvature", self.curvature)
        self.inset = FloatParameterControl(
            0.0, 0.9, 0.0, decimals=3, single_step=0.05
        )
        shape.addRow("Inset", self.inset)
        self.squash = FloatParameterControl(
            -0.9, 0.9, 0.0, decimals=3, single_step=0.05
        )
        shape.addRow("Squash", self.squash)
        self.expand = FloatParameterControl(
            -0.75, 2.0, 0.0, decimals=3, single_step=0.05
        )
        shape.addRow("Expand", self.expand)
        self.tip_roundness = FloatParameterControl(
            0.0, 1.0, 0.15, decimals=3, single_step=0.05
        )
        shape.addRow("Tip Roundness", self.tip_roundness)
        self.tip_offset = FloatParameterControl(
            -1.0, 1.0, 0.0, decimals=3, single_step=0.05
        )
        shape.addRow("Tip Offset", self.tip_offset)
        self.forward_offset = FloatParameterControl(
            -2.0, 2.0, 0.0, decimals=3, single_step=0.05
        )
        shape.addRow("Forward Offset", self.forward_offset)
        self.random_size = FloatParameterControl(
            0.0, 0.95, 0.12, decimals=3, single_step=0.05
        )
        shape.addRow("Random Size", self.random_size)
        shape_note = QtWidgets.QLabel(
            "各Cell固有の外周を保持し、対応するInterior Ringと中心だけをShapeパラメータで変形します。\n"
            "色はScale TypesごとのVertex Colorで管理します。"
        )
        shape_note.setWordWrap(True)
        shape.addRow(shape_note)

        layout.addStretch(1)
        scroll.setWidget(content)
        tab_layout.addWidget(scroll)
        self.tabs.addTab(tab, "Global")

    def _build_distribution_tab(self) -> None:
        tab = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(tab)
        self.target_count = IntParameterControl(1, 50000, 512)
        form.addRow("Target Count", self.target_count)

        self.seed = QtWidgets.QSpinBox()
        self.seed.setRange(-2147483647, 2147483647)
        self.seed.setValue(1)
        self.seed.setKeyboardTracking(True)
        form.addRow("Seed", self.seed)

        self.spacing_factor = FloatParameterControl(
            0.15,
            2.5,
            0.82,
            decimals=3,
            single_step=0.05,
        )
        form.addRow("Spacing", self.spacing_factor)

        self.relax_iterations = IntParameterControl(0, 64, 0)
        form.addRow("Density Relax Iterations", self.relax_iterations)
        self.relax_strength = FloatParameterControl(
            0.0, 1.0, 0.45, decimals=3, single_step=0.05
        )
        form.addRow("Density Relax Strength", self.relax_strength)

        info = QtWidgets.QLabel(
            "面積加重サンプリングと空間ハッシュで配置します。\n"
            "Count / Seed / Spacing変更時のみ配置キャッシュを更新します。"
        )
        info.setWordWrap(True)
        form.addRow(info)
        self.tabs.addTab(tab, "Distribution")

    def _build_orientation_tab(self) -> None:
        tab = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(tab)
        self.direction = FloatParameterControl(
            -360.0,
            360.0,
            0.0,
            decimals=2,
            single_step=5.0,
            suffix=" deg",
        )
        form.addRow("Global Direction", self.direction)
        self.random_rotation = FloatParameterControl(
            0.0,
            180.0,
            8.0,
            decimals=2,
            single_step=2.0,
            suffix=" deg",
        )
        form.addRow("Random Rotation", self.random_rotation)
        self.direction_relax_iterations = IntParameterControl(0, 64, 0)
        form.addRow("Direction Relax Iterations", self.direction_relax_iterations)
        self.direction_relax_strength = FloatParameterControl(
            0.0, 1.0, 0.35, decimals=3, single_step=0.05
        )
        form.addRow("Direction Relax Strength", self.direction_relax_strength)
        note = QtWidgets.QLabel(
            "Direction Curveは始点から終点への接線方向を使い、近傍平均で滑らかにします。"
        )
        note.setWordWrap(True)
        form.addRow(note)
        self.tabs.addTab(tab, "Orientation")

    def _build_cells_tab(self) -> None:
        tab = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(tab)

        self.cell_mode = QtWidgets.QComboBox()
        self.cell_mode.addItem("Auto: \u64cd\u4f5c\u4e2dCard / \u505c\u6b62\u5f8cCell", "auto")
        self.cell_mode.addItem("Cards only", "cards")
        self.cell_mode.addItem("Cells while dragging", "cells")
        form.addRow("Preview Geometry", self.cell_mode)

        self.cell_growth = FloatParameterControl(
            0.0, 1.0, 0.85, decimals=3, single_step=0.05
        )
        form.addRow("Growth", self.cell_growth)
        self.cell_gap = FloatParameterControl(
            0.0, 0.49, 0.06, decimals=3, single_step=0.01
        )
        form.addRow("Gap / Spacing", self.cell_gap)
        self.cell_collision_margin = FloatParameterControl(
            0.0, 0.49, 0.02, decimals=3, single_step=0.01
        )
        form.addRow("Collision Margin", self.cell_collision_margin)
        self.cell_radius_multiplier = FloatParameterControl(
            0.35, 6.0, 1.65, decimals=3, single_step=0.05
        )
        form.addRow("Open Cell Radius Limit", self.cell_radius_multiplier)
        self.cell_direction_anisotropy = FloatParameterControl(
            0.0, 1.0, 0.4, decimals=3, single_step=0.05
        )
        self.cell_direction_anisotropy.setToolTip(
            "0は従来の等方Cell、1はGuide効果内で最大2.25倍の方向性を与えます。"
        )
        form.addRow("Cell Direction Anisotropy", self.cell_direction_anisotropy)

        self.cell_interactive_resolution = QtWidgets.QSpinBox()
        self.cell_interactive_resolution.setRange(4, 16)
        self.cell_interactive_resolution.setValue(6)
        form.addRow("Interactive Cell Sides", self.cell_interactive_resolution)
        self.cell_settled_resolution = QtWidgets.QSpinBox()
        self.cell_settled_resolution.setRange(4, 32)
        self.cell_settled_resolution.setValue(10)
        form.addRow("Settled Cell Sides", self.cell_settled_resolution)
        self.cell_shape_divisions = QtWidgets.QSpinBox()
        self.cell_shape_divisions.setRange(1, 6)
        self.cell_shape_divisions.setValue(2)
        form.addRow("Interior Divisions", self.cell_shape_divisions)
        self.cell_projection_rings = QtWidgets.QSpinBox()
        self.cell_projection_rings.setRange(0, 16)
        self.cell_projection_rings.setValue(2)
        form.addRow("Surface Projection Rings", self.cell_projection_rings)
        self.cell_project_to_surface = QtWidgets.QCheckBox("Cell\u5883\u754c\u3092Target\u3078\u518d\u6295\u5f71")
        self.cell_project_to_surface.setChecked(True)
        form.addRow(self.cell_project_to_surface)

        note = QtWidgets.QLabel(
            "Direction Point / CurveはOrientationとCell Direction Anisotropyを制御します。\n"
            "Direction CurveはStrengthが0より大きい場合だけ、DensityとPoisson間隔に従うCell中心候補列を維持し、補助のペア種点は作成しません。\n"
            "Cell固有の外周点列は共通形状へ置き換えず、Interior Divisionsで対応する内側リングと中心を生成します。\n"
            "ShapeパラメータはこのCell由来トポロジの内部を変形し、各Cellの不規則な境界形状を保持します。"
        )
        note.setWordWrap(True)
        form.addRow(note)
        self.tabs.addTab(tab, "Cells")

    def _build_guides_tab(self) -> None:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)

        self.guide_tree = _GuideTreeWidget()
        self.guide_tree.setHeaderHidden(True)
        self.guide_tree.setMinimumHeight(220)
        self.guide_tree.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.guide_tree.setDragEnabled(True)
        self.guide_tree.setAcceptDrops(True)
        self.guide_tree.setDropIndicatorShown(True)
        self.guide_tree.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.guide_tree.setDefaultDropAction(QtCore.Qt.MoveAction)
        layout.addWidget(self.guide_tree)

        action_grid = QtWidgets.QGridLayout()
        self.create_guide_point_button = QtWidgets.QPushButton("Create Guide Point")
        self.draw_guide_curve_button = QtWidgets.QPushButton("Draw Guide Curve")
        self.draw_guide_curve_button.setCheckable(True)
        self.delete_guide_button = QtWidgets.QPushButton("Delete")
        self.rebuild_guides_button = QtWidgets.QPushButton("Rebuild")
        action_grid.addWidget(self.create_guide_point_button, 0, 0)
        action_grid.addWidget(self.draw_guide_curve_button, 0, 1)
        action_grid.addWidget(self.delete_guide_button, 1, 0)
        action_grid.addWidget(self.rebuild_guides_button, 1, 1)
        layout.addLayout(action_grid)

        group_action_row = QtWidgets.QHBoxLayout()
        self.create_guide_group_button = QtWidgets.QPushButton("New Guide Group")
        group_action_row.addWidget(self.create_guide_group_button)
        group_action_row.addStretch(1)
        layout.addLayout(group_action_row)

        self.guide_editor = QtWidgets.QGroupBox("Selected Guide")
        form = QtWidgets.QFormLayout(self.guide_editor)
        self.guide_name = QtWidgets.QLineEdit()
        self.guide_name.setMaxLength(64)
        form.addRow("Name", self.guide_name)
        self.guide_group_combo = QtWidgets.QComboBox()
        form.addRow("Group", self.guide_group_combo)
        self.guide_enabled = QtWidgets.QCheckBox("Active")
        self.guide_enabled.setChecked(True)
        form.addRow(self.guide_enabled)

        role_widget = QtWidgets.QWidget()
        role_layout = QtWidgets.QHBoxLayout(role_widget)
        role_layout.setContentsMargins(0, 0, 0, 0)
        self.guide_use_density = QtWidgets.QCheckBox("Density")
        self.guide_use_size = QtWidgets.QCheckBox("Size")
        self.guide_use_direction = QtWidgets.QCheckBox("Direction")
        self.guide_use_mask = QtWidgets.QCheckBox("Mask")
        self.guide_use_mask.setToolTip(
            "Range内の完成Cellからメッシュ出力だけを除外します。"
            "FalloffはRangeに対する減衰幅です。"
            "Mask GuideはViewportでマゼンタ表示されます。"
        )
        role_layout.addWidget(self.guide_use_density)
        role_layout.addWidget(self.guide_use_size)
        role_layout.addWidget(self.guide_use_direction)
        role_layout.addWidget(self.guide_use_mask)
        role_layout.addStretch(1)
        form.addRow("Effects", role_widget)

        self.guide_radius = FloatParameterControl(
            0.000001, 1000000.0, 1.0, decimals=5, mapping="log"
        )
        form.addRow("Range", self.guide_radius)
        self.guide_falloff = FloatParameterControl(0.0, 1.0, 1.0, decimals=3)
        self.guide_falloff.setToolTip(
            "0: Range全域で完全効果。1: 中心からRange外端まで全域で減衰。"
        )
        form.addRow("Falloff", self.guide_falloff)
        self.guide_density_multiplier = FloatParameterControl(
            0.0, 16.0, 1.75, decimals=3
        )
        form.addRow("Density Multiplier", self.guide_density_multiplier)
        self.guide_size_multiplier = FloatParameterControl(
            0.05, 8.0, 1.0, decimals=3, mapping="log"
        )
        form.addRow("Size Multiplier", self.guide_size_multiplier)
        self.guide_strength = FloatParameterControl(0.0, 1.0, 1.0, decimals=3)
        self.guide_strength.setToolTip(
            "鱗のOrientationがPointまたはCurve方向へ沿う強さです。"
            "Cell中心配置とCell境界の異方性には影響しません。"
        )
        form.addRow("Direction Strength", self.guide_strength)
        self.guide_center_alignment = FloatParameterControl(
            0.0, 1.0, 0.35, decimals=3
        )
        self.guide_center_alignment.setToolTip(
            "Direction Curve上へ配置するCell中心候補の量です。"
            "0で中心列なし、1で分布間隔ごとに候補を作成します。"
        )
        form.addRow("Center Alignment", self.guide_center_alignment)
        self.guide_cell_anisotropy = FloatParameterControl(
            0.0, 1.0, 1.0, decimals=3
        )
        self.guide_cell_anisotropy.setToolTip(
            "このGuideがCell境界を方向付ける強さです。"
            "Direction StrengthやCenter Alignmentとは独立しています。"
        )
        form.addRow("Cell Anisotropy", self.guide_cell_anisotropy)
        self.guide_angle = FloatParameterControl(
            -360.0, 360.0, 0.0, decimals=2, suffix=" deg"
        )
        form.addRow("Direction Angle", self.guide_angle)
        self.guide_symmetry_enabled = QtWidgets.QCheckBox("Enabled")
        self.guide_symmetry_enabled.setToolTip(
            "実体Guideを複製せず、評価時だけ鏡像Guideを追加します。"
        )
        form.addRow("Symmetry", self.guide_symmetry_enabled)
        self.guide_symmetry_axis = QtWidgets.QComboBox()
        for label, value in (("X", "x"), ("Y", "y"), ("Z", "z")):
            self.guide_symmetry_axis.addItem(label, value)
        form.addRow("Symmetry Axis", self.guide_symmetry_axis)
        self.guide_symmetry_space = QtWidgets.QComboBox()
        self.guide_symmetry_space.addItem("World", "world")
        self.guide_symmetry_space.addItem("Target Local", "target_local")
        self.guide_symmetry_space.setToolTip(
            "Worldはワールド原点、Target LocalはTarget Transform原点を対称面の中心に使います。"
        )
        form.addRow("Symmetry Space", self.guide_symmetry_space)
        self.guide_closed = QtWidgets.QCheckBox("Closed Curve")
        form.addRow(self.guide_closed)
        layout.addWidget(self.guide_editor)

        self.guide_group_editor = QtWidgets.QGroupBox("Selected Guide Group")
        group_form = QtWidgets.QFormLayout(self.guide_group_editor)
        self.guide_group_name = QtWidgets.QLineEdit()
        self.guide_group_name.setMaxLength(64)
        group_form.addRow("Name", self.guide_group_name)
        self.guide_group_enabled = QtWidgets.QCheckBox("Active")
        self.guide_group_enabled.setChecked(True)
        group_form.addRow(self.guide_group_enabled)
        self.guide_group_radius_multiplier = FloatParameterControl(
            0.05, 20.0, 1.0, decimals=3, mapping="log"
        )
        group_form.addRow("Range", self.guide_group_radius_multiplier)
        self.guide_group_falloff_multiplier = FloatParameterControl(
            0.125, 8.0, 1.0, decimals=3, mapping="log"
        )
        group_form.addRow("Falloff", self.guide_group_falloff_multiplier)
        self.guide_group_density_strength = FloatParameterControl(
            0.0, 4.0, 1.0, decimals=3
        )
        group_form.addRow("Density Effect", self.guide_group_density_strength)
        self.guide_group_size_strength = FloatParameterControl(
            0.0, 4.0, 1.0, decimals=3
        )
        group_form.addRow("Size Effect", self.guide_group_size_strength)
        self.guide_group_direction_strength = FloatParameterControl(
            0.0, 1.0, 1.0, decimals=3
        )
        self.guide_group_direction_strength.setToolTip(
            "所属GuideのDirection Strengthに0〜1の範囲で乗算します。1が個別値をそのまま使う最大値です。"
        )
        group_form.addRow(
            "Direction Strength", self.guide_group_direction_strength
        )
        self.guide_group_angle_offset = FloatParameterControl(
            -360.0, 360.0, 0.0, decimals=2, suffix=" deg"
        )
        group_form.addRow("Direction Angle Offset", self.guide_group_angle_offset)
        self.guide_group_symmetry_enabled = QtWidgets.QCheckBox(
            "Enable for all members"
        )
        self.guide_group_symmetry_enabled.setToolTip(
            "オンの間だけGroupのAxis / Spaceを所属Guideへ非破壊で適用します。"
        )
        group_form.addRow("Symmetry", self.guide_group_symmetry_enabled)
        self.guide_group_symmetry_axis = QtWidgets.QComboBox()
        for label, value in (("X", "x"), ("Y", "y"), ("Z", "z")):
            self.guide_group_symmetry_axis.addItem(label, value)
        group_form.addRow("Symmetry Axis", self.guide_group_symmetry_axis)
        self.guide_group_symmetry_space = QtWidgets.QComboBox()
        self.guide_group_symmetry_space.addItem("World", "world")
        self.guide_group_symmetry_space.addItem("Target Local", "target_local")
        group_form.addRow("Symmetry Space", self.guide_group_symmetry_space)
        layout.addWidget(self.guide_group_editor)

        self.guide_editor.setVisible(False)
        self.guide_group_editor.setVisible(False)
        self.delete_guide_button.setEnabled(False)

        note = QtWidgets.QLabel(
            "Outliner／Viewport／このTreeの選択は相互に同期します。\n"
            "GuideはドラッグでGroupへ移動でき、GuideとGroupの表示順も整理できます。"
            " 表示順を変えても生成評価順と乱数列は変わりません。\n"
            "Group値は各Guideの個別値へ非破壊で合成され、Scale TypesからGuideまたはGroupを参照できます。\n"
            "Direction Pointは鱗をPointへ向け、Direction Curveはカーブ上にCell中心列を作成します。\n"
            "SymmetryはGuideのDAGを複製せず、WorldまたはTarget LocalのX/Y/Z面へ評価時だけ鏡像を追加します。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        self.tabs.addTab(tab, "Guides")

    def _build_shape_tab(self) -> None:
        tab = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(tab)
        self.size = FloatParameterControl(
            0.000001,
            1000000.0,
            0.1,
            decimals=6,
            single_step=0.01,
            mapping="log",
        )
        form.addRow("Scale Size", self.size)


        self.lift = QtWidgets.QDoubleSpinBox()
        self.lift.setRange(-1000000.0, 1000000.0)
        self.lift.setDecimals(6)
        self.lift.setSingleStep(0.001)
        self.lift.setValue(0.002)
        self.lift.setKeyboardTracking(True)
        form.addRow("Surface Lift", self.lift)

        self.curvature = FloatParameterControl(
            -4.0,
            4.0,
            0.22,
            decimals=3,
            single_step=0.05,
        )
        form.addRow("Curvature", self.curvature)

        self.inset = FloatParameterControl(0.0, 0.9, 0.0, decimals=3, single_step=0.05)
        form.addRow("Inset", self.inset)
        self.squash = FloatParameterControl(-0.9, 0.9, 0.0, decimals=3, single_step=0.05)
        form.addRow("Squash", self.squash)
        self.expand = FloatParameterControl(-0.75, 2.0, 0.0, decimals=3, single_step=0.05)
        form.addRow("Expand", self.expand)
        self.tip_roundness = FloatParameterControl(0.0, 1.0, 0.15, decimals=3, single_step=0.05)
        form.addRow("Tip Roundness", self.tip_roundness)
        self.tip_offset = FloatParameterControl(-1.0, 1.0, 0.0, decimals=3, single_step=0.05)
        form.addRow("Tip Offset", self.tip_offset)
        self.forward_offset = FloatParameterControl(-2.0, 2.0, 0.0, decimals=3, single_step=0.05)
        form.addRow("Forward Offset", self.forward_offset)

        self.random_size = FloatParameterControl(
            0.0,
            0.95,
            0.12,
            decimals=3,
            single_step=0.05,
        )
        form.addRow("Random Size", self.random_size)

        note = QtWidgets.QLabel(
            "Cell表示でもScale Size / Inset / Squash / Expand / Tip / Forward Offsetを"
            "HDA風の輪郭としてCell境界内へ最大フィットします。\n"
            "Shape変更ではDistribution / Orientation / Cell Cacheを再利用し、同一解像度なら頂点位置だけを更新します。"
        )
        note.setWordWrap(True)
        form.addRow(note)
        self.tabs.addTab(tab, "Shape")

    def _build_scale_types_tab(self) -> None:
        tab = QtWidgets.QWidget()
        outer = QtWidgets.QHBoxLayout(tab)
        left = QtWidgets.QVBoxLayout()
        self.scale_type_list = QtWidgets.QListWidget()
        self.scale_type_list.setMinimumWidth(180)
        left.addWidget(self.scale_type_list, 1)
        row = QtWidgets.QGridLayout()
        self.add_scale_type_button = QtWidgets.QPushButton("Add")
        self.duplicate_scale_type_button = QtWidgets.QPushButton("Duplicate")
        self.remove_scale_type_button = QtWidgets.QPushButton("Remove")
        self.move_scale_type_up_button = QtWidgets.QPushButton("Up")
        self.move_scale_type_down_button = QtWidgets.QPushButton("Down")
        row.addWidget(self.add_scale_type_button, 0, 0)
        row.addWidget(self.duplicate_scale_type_button, 0, 1)
        row.addWidget(self.remove_scale_type_button, 1, 0)
        row.addWidget(self.move_scale_type_up_button, 1, 1)
        row.addWidget(self.move_scale_type_down_button, 2, 0, 1, 2)
        left.addLayout(row)
        outer.addLayout(left)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        editor = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(editor)
        self.type_name = QtWidgets.QLineEdit()
        form.addRow("Name", self.type_name)
        self.type_enabled = QtWidgets.QCheckBox("Enabled")
        form.addRow(self.type_enabled)
        self.type_size = FloatParameterControl(0.05, 8.0, 1.0, decimals=3, mapping="log")
        form.addRow("Size", self.type_size)
        self.type_width = FloatParameterControl(0.05, 8.0, 1.0, decimals=3, mapping="log")
        form.addRow("Width", self.type_width)
        self.type_length = FloatParameterControl(0.05, 8.0, 1.0, decimals=3, mapping="log")
        form.addRow("Length", self.type_length)
        self.type_curvature = FloatParameterControl(-4.0, 4.0, 1.0, decimals=3)
        form.addRow("Curvature", self.type_curvature)
        self.type_offset = FloatParameterControl(-4.0, 4.0, 0.0, decimals=3)
        form.addRow("Normal Offset", self.type_offset)
        self.type_random_offset = FloatParameterControl(0.0, 1.0, 0.0, decimals=3)
        form.addRow("Random Offset", self.type_random_offset)
        self.type_tip_offset = FloatParameterControl(-1.0, 1.0, 0.0, decimals=3)
        form.addRow("Tip Offset", self.type_tip_offset)
        self.type_guide_combo = QtWidgets.QComboBox()
        form.addRow("Guide Link", self.type_guide_combo)
        type_note = QtWidgets.QLabel(
            "Guide／Group LinkがあるTypeは、その位置で最も強いLinkを確定採用します。"
            "複数Typeを別Guideへ割り当てても相互に抽選競合しません。"
        )
        type_note.setWordWrap(True)
        form.addRow(type_note)
        self.type_custom_color = QtWidgets.QCheckBox("Custom Vertex Color")
        form.addRow(self.type_custom_color)
        color_row = QtWidgets.QHBoxLayout()
        self.type_color_r = self._color_spin(0.34)
        self.type_color_g = self._color_spin(0.58)
        self.type_color_b = self._color_spin(0.82)
        for label, widget in (("R", self.type_color_r), ("G", self.type_color_g), ("B", self.type_color_b)):
            color_row.addWidget(QtWidgets.QLabel(label))
            color_row.addWidget(widget)
        form.addRow("Color", color_row)
        scroll.setWidget(editor)
        outer.addWidget(scroll, 1)
        self.tabs.addTab(tab, "Scale Types")

    def _build_preview_tab(self) -> None:
        tab = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(tab)

        backend_label = QtWidgets.QLabel("Native Bifrost（唯一の生成Backend）")
        backend_label.setWordWrap(True)
        form.addRow("Preview Backend", backend_label)

        native_controls = QtWidgets.QHBoxLayout()
        self.native_probe_button = QtWidgets.QPushButton("Native環境を確認")
        self.native_rebuild_graph_button = QtWidgets.QPushButton("Native Graphを再構築")
        self.native_delete_graph_button = QtWidgets.QPushButton("Native Graphを削除")
        native_controls.addWidget(self.native_probe_button)
        native_controls.addWidget(self.native_rebuild_graph_button)
        native_controls.addWidget(self.native_delete_graph_button)
        form.addRow(native_controls)
        self.native_status_label = QtWidgets.QLabel(
            "新規作成時にSystem、worldMesh接続、Native Graph、初回Previewを自動作成します。"
        )
        self.native_status_label.setWordWrap(True)
        form.addRow("Native Status", self.native_status_label)

        self.auto_preview = QtWidgets.QCheckBox("Auto Preview")
        self.auto_preview.setChecked(True)
        form.addRow(self.auto_preview)
        self.visible = QtWidgets.QCheckBox("Previewを表示")
        self.visible.setChecked(True)
        form.addRow(self.visible)

        self.interactive_budget = QtWidgets.QSpinBox()
        self.interactive_budget.setRange(8, 50000)
        self.interactive_budget.setValue(128)
        form.addRow("Interactive上限", self.interactive_budget)

        self.settled_budget = QtWidgets.QSpinBox()
        self.settled_budget.setRange(8, 50000)
        self.settled_budget.setValue(512)
        form.addRow("Settled上限", self.settled_budget)

        self.interactive_delay = QtWidgets.QSpinBox()
        self.interactive_delay.setRange(16, 1000)
        self.interactive_delay.setValue(50)
        self.interactive_delay.setSuffix(" ms")
        form.addRow("Interactive間隔", self.interactive_delay)

        self.settled_delay = QtWidgets.QSpinBox()
        self.settled_delay.setRange(50, 3000)
        self.settled_delay.setValue(180)
        self.settled_delay.setSuffix(" ms")
        form.addRow("停止後Refine", self.settled_delay)

        controls = QtWidgets.QHBoxLayout()
        self.pause_button = QtWidgets.QPushButton("Pause")
        self.clear_fault_button = QtWidgets.QPushButton("Fault解除")
        controls.addWidget(self.pause_button)
        controls.addWidget(self.clear_fault_button)
        form.addRow(controls)

        self.performance_label = QtWidgets.QLabel("Native performance: -")
        self.performance_label.setWordWrap(True)
        form.addRow("Performance", self.performance_label)

        note = QtWidgets.QLabel(
            "Python Reference Preview、Python Final、Python Bakeは削除されています。\n"
            "現在のPreview Geometryは常にStatic Bifrost GraphとNative C++ Coreから生成されます。"
        )
        note.setWordWrap(True)
        form.addRow(note)
        self.tabs.addTab(tab, "Preview")

    def _build_maintenance_tab(self) -> None:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        note = QtWidgets.QLabel(
            "旧ツールは新ランタイムに不要です。削除対象は既知のmodule登録、\n"
            "旧Pythonパッケージ、旧Published Compound、検証済みWoutScales Packです。\n"
            "シーン内のメッシュや制作データは削除しません。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QtWidgets.QHBoxLayout()
        self.diagnostics_button = QtWidgets.QPushButton("環境診断")
        self.scan_legacy_button = QtWidgets.QPushButton("旧ツール検索")
        self.remove_legacy_button = QtWidgets.QPushButton("旧ツールを削除")
        buttons.addWidget(self.diagnostics_button)
        buttons.addWidget(self.scan_legacy_button)
        buttons.addWidget(self.remove_legacy_button)
        layout.addLayout(buttons)
        self.maintenance_text = QtWidgets.QPlainTextEdit()
        self.maintenance_text.setReadOnly(True)
        layout.addWidget(self.maintenance_text, 1)
        self.tabs.addTab(tab, "Maintenance")

    @staticmethod
    def _color_spin(value: float):
        widget = QtWidgets.QDoubleSpinBox()
        widget.setRange(0.0, 1.0)
        widget.setDecimals(3)
        widget.setSingleStep(0.05)
        widget.setValue(value)
        widget.setKeyboardTracking(True)
        return widget

    def _connect_ui(self) -> None:
        self.refresh_systems_button.clicked.connect(self._refresh_systems)
        self.system_combo.currentIndexChanged.connect(self._bind_selected_system)
        self.create_system_button.clicked.connect(self._create_system)
        self.set_target_button.clicked.connect(self._set_target)
        self.refresh_target_button.clicked.connect(self._refresh_target)
        self.preview_now_button.clicked.connect(self._preview_now)
        self.delete_system_button.clicked.connect(self._delete_system)
        self.auto_preview.toggled.connect(self._auto_preview_toggled)
        self.visible.toggled.connect(
            lambda *_: self._parameter_changed(ChangeCategory.DISPLAY, settle=True)
        )
        self.pause_button.clicked.connect(self._toggle_pause)
        self.clear_fault_button.clicked.connect(self._clear_fault)
        self.interactive_delay.valueChanged.connect(self._configure_delays)
        self.settled_delay.valueChanged.connect(self._configure_delays)
        self.scheduler.status_changed.connect(self.status_label.setText)
        self.scheduler.request_finished.connect(self._request_finished)
        self.scheduler.request_failed.connect(self._request_failed)
        self.diagnostics_button.clicked.connect(self._diagnose)
        self.scan_legacy_button.clicked.connect(self._scan_legacy)
        self.remove_legacy_button.clicked.connect(self._remove_legacy)
        self.native_probe_button.clicked.connect(self._probe_native_backend)
        self.native_rebuild_graph_button.clicked.connect(self._rebuild_native_graph)
        self.native_delete_graph_button.clicked.connect(self._delete_native_graph)
        for widget in (
            self.target_count,
            self.seed,
            self.spacing_factor,
            self.relax_iterations,
            self.relax_strength,
        ):
            self._connect_parameter(widget, ChangeCategory.DISTRIBUTION)
        for widget in (
            self.direction,
            self.random_rotation,
            self.direction_relax_iterations,
            self.direction_relax_strength,
        ):
            self._connect_parameter(widget, ChangeCategory.ORIENTATION)
        self.cell_mode.currentIndexChanged.connect(
            lambda *_args: self._parameter_changed(ChangeCategory.CELL, settle=True)
        )
        self._connect_parameter(self.cell_growth, ChangeCategory.SHAPE)
        for widget in (
            self.cell_gap,
            self.cell_collision_margin,
            self.cell_radius_multiplier,
            self.cell_direction_anisotropy,
            self.cell_interactive_resolution,
            self.cell_settled_resolution,
            self.cell_projection_rings,
        ):
            self._connect_parameter(widget, ChangeCategory.CELL)
        self._connect_parameter(self.cell_shape_divisions, ChangeCategory.SHAPE)
        self.cell_project_to_surface.toggled.connect(
            lambda *_args: self._parameter_changed(ChangeCategory.CELL, settle=True)
        )
        for widget in (
            self.size,
            self.lift,
            self.curvature,
            self.inset,
            self.squash,
            self.expand,
            self.tip_roundness,
            self.tip_offset,
            self.forward_offset,
            self.random_size,
        ):
            self._connect_parameter(widget, ChangeCategory.SHAPE)
        for widget in (self.interactive_budget, self.settled_budget):
            self._connect_parameter(widget, ChangeCategory.DISTRIBUTION)
        self.guide_tree.currentItemChanged.connect(self._guide_selection_changed)
        self.guide_tree.itemSelectionChanged.connect(
            self._guide_tree_selection_changed
        )
        self.guide_tree.model().rowsMoved.connect(self._guide_tree_rows_moved)
        self.guide_tree.dropCompleted.connect(self._guide_tree_rows_moved)
        self.rebuild_guides_button.clicked.connect(self._rebuild_guides)
        self.delete_guide_button.clicked.connect(self._delete_current_guide_item)
        self.create_guide_group_button.clicked.connect(self._create_guide_group)
        self.create_guide_point_button.clicked.connect(
            lambda: self._create_guide(GuideKind.DENSITY_POINT)
        )
        self.draw_guide_curve_button.clicked.connect(
            self._curve_draw_button_clicked
        )
        self.guide_name.editingFinished.connect(self._guide_name_changed)
        self.guide_group_combo.currentIndexChanged.connect(
            self._guide_group_assignment_changed
        )
        self.guide_enabled.toggled.connect(self._guide_editor_changed)
        self.guide_closed.toggled.connect(self._guide_editor_changed)
        self.guide_use_density.toggled.connect(self._guide_editor_changed)
        self.guide_use_size.toggled.connect(self._guide_editor_changed)
        self.guide_use_direction.toggled.connect(self._guide_editor_changed)
        self.guide_use_mask.toggled.connect(self._guide_editor_changed)
        self.guide_symmetry_enabled.toggled.connect(self._guide_editor_changed)
        self.guide_symmetry_axis.currentIndexChanged.connect(
            self._guide_editor_changed
        )
        self.guide_symmetry_space.currentIndexChanged.connect(
            self._guide_editor_changed
        )
        for widget in (
            self.guide_radius,
            self.guide_falloff,
            self.guide_density_multiplier,
            self.guide_size_multiplier,
            self.guide_strength,
            self.guide_center_alignment,
            self.guide_cell_anisotropy,
            self.guide_angle,
        ):
            self._connect_guide_parameter(widget)

        self.guide_group_name.editingFinished.connect(
            self._guide_group_editor_changed
        )
        self.guide_group_enabled.toggled.connect(
            self._guide_group_editor_changed
        )
        self.guide_group_symmetry_enabled.toggled.connect(
            self._guide_group_editor_changed
        )
        self.guide_group_symmetry_axis.currentIndexChanged.connect(
            self._guide_group_editor_changed
        )
        self.guide_group_symmetry_space.currentIndexChanged.connect(
            self._guide_group_editor_changed
        )
        for widget in (
            self.guide_group_radius_multiplier,
            self.guide_group_falloff_multiplier,
            self.guide_group_density_strength,
            self.guide_group_size_strength,
            self.guide_group_direction_strength,
            self.guide_group_angle_offset,
        ):
            self._connect_guide_group_parameter(widget)

        self.scale_type_list.currentRowChanged.connect(
            self._scale_type_selection_changed
        )
        self.add_scale_type_button.clicked.connect(self._add_scale_type)
        self.duplicate_scale_type_button.clicked.connect(self._duplicate_scale_type)
        self.remove_scale_type_button.clicked.connect(self._remove_scale_type)
        self.move_scale_type_up_button.clicked.connect(
            lambda: self._move_scale_type(-1)
        )
        self.move_scale_type_down_button.clicked.connect(
            lambda: self._move_scale_type(1)
        )
        self.type_name.editingFinished.connect(self._scale_type_editor_changed)
        self.type_enabled.toggled.connect(self._scale_type_editor_changed)
        self.type_custom_color.toggled.connect(self._scale_type_editor_changed)
        self.type_guide_combo.currentIndexChanged.connect(
            self._scale_type_editor_changed
        )
        for widget in (
            self.type_size,
            self.type_width,
            self.type_length,
            self.type_curvature,
            self.type_offset,
            self.type_random_offset,
            self.type_tip_offset,
            self.type_color_r,
            self.type_color_g,
            self.type_color_b,
        ):
            self._connect_scale_type_parameter(widget)

    def _connect_parameter(self, widget, category: ChangeCategory) -> None:
        widget.valueChanged.connect(lambda *_args, item=category: self._parameter_changed(item))
        if hasattr(widget, "interactionStarted"):
            widget.interactionStarted.connect(self._begin_interaction)
        if hasattr(widget, "interactionFinished"):
            widget.interactionFinished.connect(self._finish_interaction)
            return
        if hasattr(widget, "editingFinished"):
            widget.editingFinished.connect(self._finish_interaction)

    def _connect_guide_parameter(self, widget) -> None:
        widget.valueChanged.connect(self._guide_editor_changed)
        if hasattr(widget, "interactionStarted"):
            widget.interactionStarted.connect(self._begin_guide_interaction)
        if hasattr(widget, "interactionFinished"):
            widget.interactionFinished.connect(self._finish_guide_interaction)

    def _connect_guide_group_parameter(self, widget) -> None:
        widget.valueChanged.connect(self._guide_group_editor_changed)
        if hasattr(widget, "interactionStarted"):
            widget.interactionStarted.connect(self._begin_guide_interaction)
        if hasattr(widget, "interactionFinished"):
            widget.interactionFinished.connect(self._finish_guide_interaction)

    def _connect_scale_type_parameter(self, widget) -> None:
        widget.valueChanged.connect(self._scale_type_editor_changed)
        if hasattr(widget, "interactionStarted"):
            widget.interactionStarted.connect(self._begin_interaction)
        if hasattr(widget, "interactionFinished"):
            widget.interactionFinished.connect(self._finish_interaction)
        elif hasattr(widget, "editingFinished"):
            widget.editingFinished.connect(self._finish_interaction)

    @QtCore.Slot()
    def _refresh_systems(self, preferred: str | None = None) -> None:
        current = preferred or self.system_combo.currentText()
        systems = self.backend.list_systems()
        self.system_combo.blockSignals(True)
        self.system_combo.clear()
        self.system_combo.addItems(systems)
        if current in systems:
            self.system_combo.setCurrentText(current)
        self.system_combo.blockSignals(False)
        if systems:
            self._bind_selected_system()
        else:
            self.target_label.setText("Target: 未設定 — 選択メッシュから新規作成してください")
            self.status_label.setText("No system")

    @QtCore.Slot()
    def _bind_selected_system(self) -> None:
        self._finish_guide_interaction()
        draw_context.stop_draw(cancel=True, reason="System切替のためGuide描画を終了しました")
        node = self.system_combo.currentText()
        if not node:
            return
        self._cancel_preview_queue()
        try:
            binding = self.backend.bind(node)
            settings = self.backend.read_settings()
        except Exception as exc:
            self._append("Bind error: {}".format(exc))
            self.status_label.setText("Error")
            return
        self.target_label.setText("Target: {}".format(binding.target_mesh))
        self._load_settings(settings)
        self._update_native_status_label()
        self.status_label.setText("Ready")

    @QtCore.Slot()
    def _create_system(self) -> None:
        self._finish_guide_interaction()
        draw_context.stop_draw(cancel=True, reason="System作成のためGuide描画を終了しました")
        self._cancel_preview_queue()
        self.status_label.setText("Creating Native System")
        try:
            target = self.backend.selected_mesh()
            settings = ScaleSettings.from_mapping(self._snapshot())
            binding, report = self.backend.create_system_with_preview(
                target,
                settings,
                mode="settled",
            )
            self._refresh_systems(preferred=binding.settings_node)
            self._update_native_status_label()
            self._append(
                "Native System created: graph={} scales={} points={} faces={} total={:.1f}ms".format(
                    self.backend.native_graph(),
                    report.scale_count,
                    report.vertex_count,
                    report.face_count,
                    report.total_ms,
                )
            )
            self.status_label.setText("Native Preview ready")
        except Exception as exc:
            self._append("Create failed: {}".format(exc))
            self.status_label.setText("Error")

    @QtCore.Slot()
    def _set_target(self) -> None:
        self._finish_guide_interaction()
        draw_context.stop_draw(cancel=True, reason="Target変更のためGuide描画を終了しました")
        if self.backend.binding is None:
            self._append("Systemを先に作成してください")
            return
        self._cancel_preview_queue()
        try:
            target = self.backend.selected_mesh()
            binding, report = self.backend.set_target_with_preview(
                target,
                settings=ScaleSettings.from_mapping(self._snapshot()),
            )
            self.target_label.setText("Target: {}".format(binding.target_mesh))
            self._update_native_status_label()
            self._append(
                "Target changed and Native Preview rebuilt: scales={} points={} faces={}".format(
                    report.scale_count, report.vertex_count, report.face_count
                )
            )
        except Exception as exc:
            self._append("Target change failed: {}".format(exc))

    @QtCore.Slot()
    def _refresh_target(self) -> None:
        self._finish_guide_interaction()
        draw_context.stop_draw(cancel=True, reason="Target再読込のためGuide描画を終了しました")
        if self.backend.binding is None:
            self._append("Systemを先に作成してください")
            return
        self._cancel_preview_queue()
        try:
            self.backend.refresh_target_cache()
            self._append("Target geometry cache cleared")
            self._preview_now()
        except Exception as exc:
            self._append("Target refresh failed: {}".format(exc))

    def _snapshot(self) -> dict[str, Any]:
        return {
            "target_count": self.target_count.value(),
            "seed": self.seed.value(),
            "spacing_factor": self.spacing_factor.value(),
            "relax_iterations": self.relax_iterations.value(),
            "relax_strength": self.relax_strength.value(),
            "size": self.size.value(),
            "lift": self.lift.value(),
            "curvature": self.curvature.value(),
            "direction_degrees": self.direction.value(),
            "direction_relax_iterations": self.direction_relax_iterations.value(),
            "direction_relax_strength": self.direction_relax_strength.value(),
            "random_size": self.random_size.value(),
            "random_rotation_degrees": self.random_rotation.value(),
            "inset": self.inset.value(),
            "squash": self.squash.value(),
            "expand": self.expand.value(),
            "tip_roundness": self.tip_roundness.value(),
            "tip_offset": self.tip_offset.value(),
            "forward_offset": self.forward_offset.value(),
            "cell_mode": str(self.cell_mode.currentData() or "auto"),
            "cell_growth": self.cell_growth.value(),
            "cell_gap": self.cell_gap.value(),
            "cell_collision_margin": self.cell_collision_margin.value(),
            "cell_radius_multiplier": self.cell_radius_multiplier.value(),
            "cell_direction_anisotropy": self.cell_direction_anisotropy.value(),
            "cell_shape_divisions": self.cell_shape_divisions.value(),
            "cell_interactive_resolution": self.cell_interactive_resolution.value(),
            "cell_settled_resolution": self.cell_settled_resolution.value(),
            "cell_projection_rings": self.cell_projection_rings.value(),
            "cell_project_to_surface": self.cell_project_to_surface.isChecked(),
            "scale_types": [asdict(item) for item in self._scale_types],
            "interactive_budget": self.interactive_budget.value(),
            "settled_budget": self.settled_budget.value(),
            "interactive_delay_ms": self.interactive_delay.value(),
            "settled_delay_ms": self.settled_delay.value(),
            "visible": self.visible.isChecked(),
            "color_r": self._preview_color[0],
            "color_g": self._preview_color[1],
            "color_b": self._preview_color[2],
        }

    def _load_settings(self, settings: ScaleSettings) -> None:
        self._updating_widgets = True
        try:
            self.target_count.setValue(settings.target_count)
            self.seed.setValue(settings.seed)
            self.spacing_factor.setValue(settings.spacing_factor)
            self.relax_iterations.setValue(settings.relax_iterations)
            self.relax_strength.setValue(settings.relax_strength)
            self.size.setValue(settings.size)
            self.lift.setValue(settings.lift)
            self.curvature.setValue(settings.curvature)
            self.direction.setValue(settings.direction_degrees)
            self.direction_relax_iterations.setValue(
                settings.direction_relax_iterations
            )
            self.direction_relax_strength.setValue(
                settings.direction_relax_strength
            )
            self.random_size.setValue(settings.random_size)
            self.random_rotation.setValue(settings.random_rotation_degrees)
            self.inset.setValue(settings.inset)
            self.squash.setValue(settings.squash)
            self.expand.setValue(settings.expand)
            self.tip_roundness.setValue(settings.tip_roundness)
            self.tip_offset.setValue(settings.tip_offset)
            self.forward_offset.setValue(settings.forward_offset)
            cell_mode_index = self.cell_mode.findData(settings.cell_mode)
            self.cell_mode.setCurrentIndex(max(0, cell_mode_index))
            self.cell_growth.setValue(settings.cell_growth)
            self.cell_gap.setValue(settings.cell_gap)
            self.cell_collision_margin.setValue(settings.cell_collision_margin)
            self.cell_radius_multiplier.setValue(settings.cell_radius_multiplier)
            self.cell_direction_anisotropy.setValue(
                settings.cell_direction_anisotropy
            )
            self.cell_shape_divisions.setValue(settings.cell_shape_divisions)
            self.cell_interactive_resolution.setValue(
                settings.cell_interactive_resolution
            )
            self.cell_settled_resolution.setValue(settings.cell_settled_resolution)
            self.cell_projection_rings.setValue(settings.cell_projection_rings)
            self.cell_project_to_surface.setChecked(settings.cell_project_to_surface)
            self._scale_types = list(settings.scale_types)
            self._guide_link_undo_sync = False
            self.interactive_budget.setValue(settings.interactive_budget)
            self.settled_budget.setValue(settings.settled_budget)
            self.interactive_delay.setValue(settings.interactive_delay_ms)
            self.settled_delay.setValue(settings.settled_delay_ms)
            self.visible.setChecked(settings.visible)
            self._preview_color = (
                settings.color_r,
                settings.color_g,
                settings.color_b,
            )
            self._refresh_scale_type_list(select_row=0)
        finally:
            self._updating_widgets = False
        self._refresh_guides()
        self._configure_delays()

    def _current_guide_item(self):
        return self.guide_tree.currentItem()

    @staticmethod
    def _guide_item_kind(item) -> str:
        if item is None:
            return ""
        try:
            return str(item.data(0, _GUIDE_ITEM_KIND_ROLE) or "")
        except Exception:
            return ""

    @staticmethod
    def _guide_item_node(item) -> str:
        if item is None:
            return ""
        try:
            return str(item.data(0, _GUIDE_NODE_ROLE) or "")
        except Exception:
            return ""

    def _current_guide_node(self) -> str:
        item = self._current_guide_item()
        return (
            self._guide_item_node(item)
            if self._guide_item_kind(item) == "guide"
            else ""
        )

    def _current_guide_group_node(self) -> str:
        item = self._current_guide_item()
        return (
            self._guide_item_node(item)
            if self._guide_item_kind(item) == "group"
            else ""
        )

    def _current_guide_item_id(self) -> str:
        node = self._guide_item_node(self._current_guide_item())
        guide = self._guide_data_by_node.get(node)
        if guide is not None:
            return guide.guide_id
        group = self._guide_group_data_by_node.get(node)
        if group is not None:
            return group.group_id
        return ""

    @staticmethod
    def _guide_label(guide) -> str:
        effects = []
        if guide.affects_density:
            effects.append("D")
        if guide.affects_size:
            effects.append("S")
        if guide.affects_direction:
            effects.append("R")
        if guide.affects_mask:
            effects.append("M")
        role_text = "/".join(effects) or "-"
        form = "Curve" if guide.kind.is_curve else "Point"
        active = "" if guide.enabled else " [OFF]"
        return "{} | {} | {}{}".format(guide.name, form, role_text, active)

    def _guide_group_label(self, group) -> str:
        member_count = sum(
            1
            for guide in self._guide_data_by_node.values()
            if guide.group_id == group.group_id
        )
        active = "" if group.enabled else " [OFF]"
        return "Group | {} ({}){}".format(group.name, member_count, active)

    def _set_guide_item_label(self, node: str) -> None:
        item = self._guide_tree_items_by_node.get(node)
        if item is None:
            return
        guide = self._guide_data_by_node.get(node)
        if guide is not None:
            item.setText(0, self._guide_label(guide))
            return
        group = self._guide_group_data_by_node.get(node)
        if group is not None:
            item.setText(0, self._guide_group_label(group))

    def _refresh_guide_group_combo(self, current_group_id: str = "") -> None:
        self.guide_group_combo.blockSignals(True)
        try:
            self.guide_group_combo.clear()
            self.guide_group_combo.addItem("Ungrouped", "")
            selected_index = 0
            for group_node in self._guide_group_nodes:
                group = self._guide_group_data_by_node.get(group_node)
                if group is None:
                    continue
                self.guide_group_combo.addItem(group.name, group_node)
                if group.group_id == current_group_id:
                    selected_index = self.guide_group_combo.count() - 1
            self.guide_group_combo.setCurrentIndex(selected_index)
        finally:
            self.guide_group_combo.blockSignals(False)

    def _preferred_guide_node(self, preferred: str, maya_selected: str) -> str:
        if preferred in self._guide_tree_items_by_node:
            return preferred
        if preferred:
            for node, guide in self._guide_data_by_node.items():
                if guide.guide_id == preferred:
                    return node
            for node, group in self._guide_group_data_by_node.items():
                if group.group_id == preferred:
                    return node
        if maya_selected in self._guide_tree_items_by_node:
            return maya_selected
        return ""

    @QtCore.Slot()
    def _refresh_guides(self, preferred: str | None = None) -> None:
        current = preferred or self._guide_item_node(self._current_guide_item())
        if self.backend.binding is None:
            self._guide_nodes = []
            self._guide_data_by_node = {}
            self._guide_group_nodes = []
            self._guide_group_data_by_node = {}
            self._guide_tree_items_by_node = {}
            self._scene_selected_guide_item = ""
            self.guide_tree.clear()
            self._refresh_guide_group_combo()
            self._refresh_scale_type_guide_combo()
            self._show_guide_item(None, sync_scene=False)
            return
        try:
            group_nodes = self.backend.list_guide_groups()
            guide_nodes = self.backend.list_guides()
            group_data = {
                node: self.backend.read_guide_group(node) for node in group_nodes
            }
            guide_data = {node: self.backend.read_guide(node) for node in guide_nodes}
            maya_selected = self.backend.selected_guide_item()
        except Exception as exc:
            self._append("Guide refresh failed: {}".format(exc))
            return

        self._guide_group_nodes = list(group_nodes)
        self._guide_group_data_by_node = group_data
        self._guide_nodes = list(guide_nodes)
        self._guide_data_by_node = guide_data
        self._guide_tree_items_by_node = {}
        self._scene_selected_guide_item = maya_selected

        self._updating_widgets = True
        self.guide_tree.blockSignals(True)
        try:
            self.guide_tree.clear()
            ungrouped_item = QtWidgets.QTreeWidgetItem(["Ungrouped"])
            ungrouped_item.setData(0, _GUIDE_ITEM_KIND_ROLE, "ungrouped")
            ungrouped_item.setData(0, _GUIDE_NODE_ROLE, "")
            ungrouped_item.setFlags(
                QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsDropEnabled
            )
            self.guide_tree.addTopLevelItem(ungrouped_item)

            group_items_by_id = {}
            for group_node in self._guide_group_nodes:
                group = self._guide_group_data_by_node.get(group_node)
                if group is None:
                    continue
                item = QtWidgets.QTreeWidgetItem([self._guide_group_label(group)])
                item.setData(0, _GUIDE_ITEM_KIND_ROLE, "group")
                item.setData(0, _GUIDE_NODE_ROLE, group_node)
                item.setFlags(
                    QtCore.Qt.ItemIsEnabled
                    | QtCore.Qt.ItemIsSelectable
                    | QtCore.Qt.ItemIsDragEnabled
                    | QtCore.Qt.ItemIsDropEnabled
                )
                self.guide_tree.addTopLevelItem(item)
                self._guide_tree_items_by_node[group_node] = item
                group_items_by_id[group.group_id] = item

            for guide_node in self._guide_nodes:
                guide = self._guide_data_by_node.get(guide_node)
                if guide is None:
                    continue
                parent = group_items_by_id.get(guide.group_id, ungrouped_item)
                item = QtWidgets.QTreeWidgetItem([self._guide_label(guide)])
                item.setData(0, _GUIDE_ITEM_KIND_ROLE, "guide")
                item.setData(0, _GUIDE_NODE_ROLE, guide_node)
                item.setFlags(
                    QtCore.Qt.ItemIsEnabled
                    | QtCore.Qt.ItemIsSelectable
                    | QtCore.Qt.ItemIsDragEnabled
                )
                parent.addChild(item)
                self._guide_tree_items_by_node[guide_node] = item

            self.guide_tree.expandAll()
            selected_node = self._preferred_guide_node(current or "", maya_selected)
            selected_item = self._guide_tree_items_by_node.get(selected_node)
            if selected_item is not None:
                self.guide_tree.setCurrentItem(selected_item)
                self.guide_tree.scrollToItem(selected_item)
            else:
                self.guide_tree.clearSelection()
                self.guide_tree.setCurrentItem(None)
        finally:
            self.guide_tree.blockSignals(False)
            self._updating_widgets = False

        self._refresh_guide_group_combo()
        self._refresh_scale_type_guide_combo()
        self._show_guide_item(self.guide_tree.currentItem(), sync_scene=False)

    def _show_guide_item(self, item, *, sync_scene: bool) -> None:
        kind = self._guide_item_kind(item)
        node = self._guide_item_node(item)
        guide = self._guide_data_by_node.get(node) if kind == "guide" else None
        group = (
            self._guide_group_data_by_node.get(node) if kind == "group" else None
        )

        self.guide_editor.setVisible(guide is not None)
        self.guide_group_editor.setVisible(group is not None)
        self.delete_guide_button.setEnabled(guide is not None or group is not None)

        self._updating_widgets = True
        try:
            if guide is not None:
                self.guide_name.setText(guide.name)
                self._refresh_guide_group_combo(guide.group_id)
                self.guide_enabled.setChecked(guide.enabled)
                self.guide_use_density.setChecked(guide.affects_density)
                self.guide_use_size.setChecked(guide.affects_size)
                self.guide_use_direction.setChecked(guide.affects_direction)
                self.guide_use_mask.setChecked(guide.affects_mask)
                self.guide_radius.setValue(guide.radius)
                self.guide_falloff.setValue(guide.falloff)
                self.guide_density_multiplier.setValue(guide.density_multiplier)
                self.guide_size_multiplier.setValue(guide.size_multiplier)
                self.guide_strength.setValue(guide.strength)
                self.guide_center_alignment.setValue(guide.center_alignment)
                self.guide_cell_anisotropy.setValue(guide.cell_anisotropy)
                self.guide_angle.setValue(guide.angle_degrees)
                self.guide_symmetry_enabled.setChecked(
                    guide.symmetry_enabled
                )
                self.guide_symmetry_axis.setCurrentIndex(
                    max(0, self.guide_symmetry_axis.findData(guide.symmetry_axis))
                )
                self.guide_symmetry_space.setCurrentIndex(
                    max(
                        0,
                        self.guide_symmetry_space.findData(
                            guide.symmetry_space
                        ),
                    )
                )
                self.guide_closed.setChecked(guide.closed)
                self.guide_density_multiplier.setEnabled(guide.affects_density)
                self.guide_size_multiplier.setEnabled(guide.affects_size)
                self.guide_strength.setEnabled(guide.affects_direction)
                self.guide_center_alignment.setEnabled(
                    guide.affects_direction and guide.kind.is_curve
                )
                self.guide_cell_anisotropy.setEnabled(guide.affects_direction)
                self.guide_angle.setEnabled(guide.affects_direction)
                self.guide_closed.setEnabled(guide.kind.is_curve)
                self.guide_symmetry_axis.setEnabled(guide.symmetry_enabled)
                self.guide_symmetry_space.setEnabled(guide.symmetry_enabled)
            elif group is not None:
                self.guide_group_name.setText(group.name)
                self.guide_group_enabled.setChecked(group.enabled)
                self.guide_group_radius_multiplier.setValue(
                    group.radius_multiplier
                )
                self.guide_group_falloff_multiplier.setValue(
                    group.falloff_multiplier
                )
                self.guide_group_density_strength.setValue(
                    group.density_strength
                )
                self.guide_group_size_strength.setValue(group.size_strength)
                self.guide_group_direction_strength.setValue(
                    group.direction_strength
                )
                self.guide_group_angle_offset.setValue(
                    group.angle_offset_degrees
                )
                self.guide_group_symmetry_enabled.setChecked(
                    group.symmetry_enabled
                )
                self.guide_group_symmetry_axis.setCurrentIndex(
                    max(
                        0,
                        self.guide_group_symmetry_axis.findData(
                            group.symmetry_axis
                        ),
                    )
                )
                self.guide_group_symmetry_space.setCurrentIndex(
                    max(
                        0,
                        self.guide_group_symmetry_space.findData(
                            group.symmetry_space
                        ),
                    )
                )
                self.guide_group_symmetry_axis.setEnabled(
                    group.symmetry_enabled
                )
                self.guide_group_symmetry_space.setEnabled(
                    group.symmetry_enabled
                )
        finally:
            self._updating_widgets = False

        if sync_scene and node and not self._syncing_guide_selection:
            try:
                self.backend.select_guide_item(node)
                self._scene_selected_guide_item = node
            except Exception as exc:
                self._append("Guide selection failed: {}".format(exc))

    @QtCore.Slot(object, object)
    def _guide_selection_changed(self, current, _previous) -> None:
        if self._updating_widgets:
            return
        self._show_guide_item(
            current,
            sync_scene=not self._syncing_guide_selection,
        )

    @QtCore.Slot()
    def _guide_tree_selection_changed(self) -> None:
        if self._updating_widgets:
            return
        item = self.guide_tree.currentItem()
        if item is None:
            self._show_guide_item(None, sync_scene=False)

    def _sync_guide_selection_from_maya(self) -> None:
        if self.backend.binding is None or self._updating_widgets:
            return
        try:
            selected = self.backend.selected_guide_item()
        except Exception:
            return
        current = self._guide_item_node(self.guide_tree.currentItem())
        if selected == current and selected == self._scene_selected_guide_item:
            return
        self._scene_selected_guide_item = selected
        item = self._guide_tree_items_by_node.get(selected)
        self._syncing_guide_selection = True
        self.guide_tree.blockSignals(True)
        try:
            if item is None:
                self.guide_tree.clearSelection()
                self.guide_tree.setCurrentItem(None)
            else:
                self.guide_tree.setCurrentItem(item)
                self.guide_tree.scrollToItem(item)
        finally:
            self.guide_tree.blockSignals(False)
            self._syncing_guide_selection = False
        self._show_guide_item(item, sync_scene=False)

    @QtCore.Slot()
    def _rebuild_guides(self) -> None:
        if self.backend.binding is None:
            return
        selected = self._current_guide_item_id() or self._guide_item_node(
            self._current_guide_item()
        )
        try:
            self.backend.refresh_guide_cache()
            self._refresh_guides(preferred=selected or None)
            self._append("Guide tree rebuilt")
        except Exception as exc:
            self._append("Guide rebuild failed: {}".format(exc))

    @QtCore.Slot()
    def _guide_name_changed(self) -> None:
        if self._updating_widgets:
            return
        node = self._current_guide_node()
        guide = self._guide_data_by_node.get(node)
        if guide is None:
            return
        requested = self.guide_name.text().strip()
        if requested == guide.name:
            return
        try:
            actual = self.backend.rename_guide(node, requested)
            self._refresh_guides(preferred=guide.guide_id)
            self._append("Guide renamed: {}".format(actual))
        except Exception as exc:
            self._updating_widgets = True
            try:
                self.guide_name.setText(guide.name)
            finally:
                self._updating_widgets = False
            self._append("Guide rename failed: {}".format(exc))

    @QtCore.Slot()
    def _guide_tree_rows_moved(self, *_args) -> None:
        if self._updating_widgets or self.backend.binding is None:
            return
        if getattr(self, "_guide_tree_drop_pending", False):
            return
        self._guide_tree_drop_pending = True
        QtCore.QTimer.singleShot(0, self._apply_guide_tree_layout_from_ui)

    @QtCore.Slot()
    def _apply_guide_tree_layout_from_ui(self) -> None:
        self._guide_tree_drop_pending = False
        if self._updating_widgets or self.backend.binding is None:
            return
        selected_id = self._current_guide_item_id()
        selected_node = self._guide_item_node(self._current_guide_item())
        try:
            if self.guide_tree.topLevelItemCount() < 1:
                raise ValueError("Guide tree is empty")
            ungrouped = self.guide_tree.topLevelItem(0)
            if self._guide_item_kind(ungrouped) != "ungrouped":
                raise ValueError("Ungrouped must remain the first root item")

            ordered_groups: list[str] = []
            guides_by_group: dict[str, list[str]] = {"": []}
            seen_groups: set[str] = set()
            seen_guides: set[str] = set()

            for top_index in range(self.guide_tree.topLevelItemCount()):
                top_item = self.guide_tree.topLevelItem(top_index)
                kind = self._guide_item_kind(top_item)
                node = self._guide_item_node(top_item)
                if top_index == 0:
                    if kind != "ungrouped" or node:
                        raise ValueError("Invalid Ungrouped item")
                    group_key = ""
                else:
                    if kind != "group" or not node or node in seen_groups:
                        raise ValueError("Guide Groups must stay at the root level")
                    ordered_groups.append(node)
                    seen_groups.add(node)
                    guides_by_group[node] = []
                    group_key = node

                for child_index in range(top_item.childCount()):
                    child = top_item.child(child_index)
                    child_node = self._guide_item_node(child)
                    if (
                        self._guide_item_kind(child) != "guide"
                        or not child_node
                        or child_node in seen_guides
                        or child.childCount() != 0
                    ):
                        raise ValueError("Only Guides may be placed inside a container")
                    guides_by_group[group_key].append(child_node)
                    seen_guides.add(child_node)

            if seen_groups != set(self._guide_group_nodes):
                raise ValueError("Guide Group layout is incomplete")
            if seen_guides != set(self._guide_nodes):
                raise ValueError("Guide layout is incomplete")

            category = self.backend.apply_guide_tree_layout(
                ordered_groups,
                guides_by_group,
            )
            self._refresh_guides(preferred=selected_id or selected_node or None)
            if category is not ChangeCategory.DISPLAY:
                self._parameter_changed(category, settle=True)
            self._append("Guide tree layout updated")
        except Exception as exc:
            self._append("Guide tree layout rejected: {}".format(exc))
            self._refresh_guides(preferred=selected_id or selected_node or None)

    def _create_guide(self, kind: GuideKind) -> None:
        if self.backend.binding is None:
            self._append("Systemを先に作成してください")
            return
        if kind.is_curve:
            self._start_curve_draw(kind)
            return
        try:
            node = self.backend.create_point_guide(kind)
            self._refresh_guides(preferred=node)
            category = (
                ChangeCategory.DISTRIBUTION
                if kind.default_use_density or kind.default_use_size
                else ChangeCategory.ORIENTATION
            )
            self._parameter_changed(category, settle=True)
            self._append("Guide Point created: {}".format(node))
        except Exception as exc:
            self._append("Guide creation failed: {}".format(exc))

    @QtCore.Slot(bool)
    def _curve_draw_button_clicked(self, checked: bool) -> None:
        if checked:
            self._start_curve_draw(GuideKind.FLOW_CURVE)
        else:
            draw_context.stop_draw(
                cancel=True,
                reason="Guide Curve描画ツールを終了しました",
            )

    def _start_curve_draw(self, kind: GuideKind) -> None:
        if self.backend.binding is None:
            self.draw_guide_curve_button.setChecked(False)
            self._append("Systemを先に作成してください")
            return
        try:
            draw_context.start_draw(
                backend=self.backend,
                kind=kind,
                cmds_module=self.backend.scene.cmds,
                on_created=self._curve_draw_created,
                on_cancelled=self._curve_draw_cancelled,
                on_error=self._curve_draw_error,
                on_state_changed=self._curve_draw_state_changed,
            )
            self._append(
                "Guide Curve描画ツールに切り替えました。ストロークごとにGuideを登録できます。"
            )
        except Exception as exc:
            self._curve_draw_state_changed(False, kind)
            self._curve_draw_error("{}: {}".format(type(exc).__name__, exc))

    def _curve_draw_created(self, node: str, kind: GuideKind) -> None:
        self._refresh_guides(preferred=node)
        category = (
            ChangeCategory.DISTRIBUTION
            if kind.default_use_density or kind.default_use_size
            else ChangeCategory.ORIENTATION
        )
        self._parameter_changed(category, settle=True)
        self._append("Guide Curve created: {}".format(node))

    def _curve_draw_cancelled(self, message: str) -> None:
        self._append(str(message))

    def _curve_draw_error(self, message: str) -> None:
        self._append("Guide Curve draw failed: {}".format(message))
        self.status_label.setText("Guide draw error")

    def _curve_draw_state_changed(self, active: bool, kind: GuideKind) -> None:
        self._active_draw_kind = kind if active else None
        self.draw_guide_curve_button.blockSignals(True)
        try:
            self.draw_guide_curve_button.setChecked(bool(active))
        finally:
            self.draw_guide_curve_button.blockSignals(False)
        if active:
            self.status_label.setText("Drawing Guide Curve")
        elif self.status_label.text().startswith("Drawing "):
            self.status_label.setText("Ready")

    @QtCore.Slot()
    def _stop_curve_draw(self) -> None:
        draw_context.stop_draw(
            cancel=True,
            reason="Guide Curve描画ツールを終了しました",
        )

    @QtCore.Slot()
    def _create_guide_group(self) -> None:
        if self.backend.binding is None:
            self._append("Systemを先に作成してください")
            return
        try:
            node = self.backend.create_guide_group()
            self._refresh_guides(preferred=node)
            try:
                self.backend.select_guide_item(node)
                self._scene_selected_guide_item = node
            except Exception:
                pass
            self._append("Guide Group created: {}".format(node))
        except Exception as exc:
            self._append("Guide Group creation failed: {}".format(exc))

    @QtCore.Slot()
    def _delete_current_guide_item(self) -> None:
        item = self._current_guide_item()
        kind = self._guide_item_kind(item)
        node = self._guide_item_node(item)
        if not node or kind not in {"guide", "group"}:
            return
        undo_open = False
        try:
            self.backend.begin_undo_chunk("Bifrost Scales Delete Guide Item")
            undo_open = True
            if kind == "guide":
                data = self._guide_data_by_node.get(node)
                deleted_id = data.guide_id if data is not None else ""
                category = self.backend.delete_guide(node)
                label = "Guide"
            else:
                data = self._guide_group_data_by_node.get(node)
                deleted_id = data.group_id if data is not None else ""
                category = self.backend.delete_guide_group(node)
                label = "Guide Group"

            links_removed = False
            if deleted_id:
                updated_types = []
                for scale_type in self._scale_types:
                    if scale_type.guide_id == deleted_id:
                        scale_type = replace(scale_type, guide_id="")
                        links_removed = True
                    updated_types.append(scale_type)
                self._scale_types = updated_types
            if links_removed:
                category = max(category, ChangeCategory.SHAPE)
                # Persist the cleared stable ID even when Automatic Preview is off.
                self.backend.persist_settings(self._snapshot())
                # Maya Undo/Redo restores this JSON together with the deleted
                # Guide item.  Keep the Scale Types editor synchronized when
                # the restored/deleted item is observed by the Guide poll.
                self._guide_link_undo_sync = True
        except Exception as exc:
            self._append("Guide deletion failed: {}".format(exc))
            return
        finally:
            if undo_open:
                self.backend.end_undo_chunk()

        self._scene_selected_guide_item = ""
        self._refresh_guides()
        if category is not ChangeCategory.DISPLAY:
            self._parameter_changed(category, settle=True)
        self._append("{} deleted: {}".format(label, node))

    def _guide_group_assignment_changed(self, _index: int) -> None:
        if self._updating_widgets:
            return
        node = self._current_guide_node()
        guide = self._guide_data_by_node.get(node)
        if guide is None:
            return
        group_node = str(
            self.guide_group_combo.itemData(
                self.guide_group_combo.currentIndex()
            )
            or ""
        )
        try:
            category = self.backend.move_guide_to_group(node, group_node)
            self._refresh_guides(preferred=guide.guide_id)
            if category is not ChangeCategory.DISPLAY:
                self._parameter_changed(category, settle=True)
            self._append("Guide group assignment updated")
        except Exception as exc:
            self._append("Guide group assignment failed: {}".format(exc))
            self._refresh_guides(preferred=guide.guide_id)

    def _guide_editor_changed(self, *_args) -> None:
        if self._updating_widgets:
            return
        node = self._current_guide_node()
        if not node:
            return
        try:
            category = self.backend.update_guide(
                node,
                enabled=self.guide_enabled.isChecked(),
                radius=self.guide_radius.value(),
                falloff=self.guide_falloff.value(),
                density_multiplier=self.guide_density_multiplier.value(),
                size_multiplier=self.guide_size_multiplier.value(),
                strength=self.guide_strength.value(),
                center_alignment=self.guide_center_alignment.value(),
                cell_anisotropy=self.guide_cell_anisotropy.value(),
                use_density=self.guide_use_density.isChecked(),
                use_size=self.guide_use_size.isChecked(),
                use_direction=self.guide_use_direction.isChecked(),
                use_mask=self.guide_use_mask.isChecked(),
                angle_degrees=self.guide_angle.value(),
                closed=self.guide_closed.isChecked(),
                symmetry_enabled=self.guide_symmetry_enabled.isChecked(),
                symmetry_axis=str(
                    self.guide_symmetry_axis.itemData(
                        self.guide_symmetry_axis.currentIndex()
                    )
                    or "x"
                ),
                symmetry_space=str(
                    self.guide_symmetry_space.itemData(
                        self.guide_symmetry_space.currentIndex()
                    )
                    or "world"
                ),
            )
            updated = self.backend.read_guide(node)
            self._guide_data_by_node[node] = updated
            self._updating_widgets = True
            try:
                self.guide_density_multiplier.setEnabled(updated.affects_density)
                self.guide_size_multiplier.setEnabled(updated.affects_size)
                self.guide_strength.setEnabled(updated.affects_direction)
                self.guide_center_alignment.setEnabled(
                    updated.affects_direction and updated.kind.is_curve
                )
                self.guide_cell_anisotropy.setEnabled(updated.affects_direction)
                self.guide_angle.setEnabled(updated.affects_direction)
                self.guide_closed.setEnabled(updated.kind.is_curve)
                self.guide_symmetry_axis.setEnabled(updated.symmetry_enabled)
                self.guide_symmetry_space.setEnabled(updated.symmetry_enabled)
                self._set_guide_item_label(node)
                parent = self._guide_tree_items_by_node.get(node)
                if parent is not None and parent.parent() is not None:
                    group_node = self._guide_item_node(parent.parent())
                    if group_node:
                        self._set_guide_item_label(group_node)
            finally:
                self._updating_widgets = False
            if category is not ChangeCategory.DISPLAY:
                self._parameter_changed(category)
        except Exception as exc:
            self._append("Guide update failed: {}".format(exc))

    def _guide_group_editor_changed(self, *_args) -> None:
        if self._updating_widgets:
            return
        node = self._current_guide_group_node()
        if not node:
            return
        group = self._guide_group_data_by_node.get(node)
        try:
            category = self.backend.update_guide_group(
                node,
                name=self.guide_group_name.text().strip(),
                enabled=self.guide_group_enabled.isChecked(),
                radius_multiplier=self.guide_group_radius_multiplier.value(),
                falloff_multiplier=self.guide_group_falloff_multiplier.value(),
                density_strength=self.guide_group_density_strength.value(),
                size_strength=self.guide_group_size_strength.value(),
                direction_strength=self.guide_group_direction_strength.value(),
                angle_offset_degrees=self.guide_group_angle_offset.value(),
                symmetry_enabled=self.guide_group_symmetry_enabled.isChecked(),
                symmetry_axis=str(
                    self.guide_group_symmetry_axis.itemData(
                        self.guide_group_symmetry_axis.currentIndex()
                    )
                    or "x"
                ),
                symmetry_space=str(
                    self.guide_group_symmetry_space.itemData(
                        self.guide_group_symmetry_space.currentIndex()
                    )
                    or "world"
                ),
            )
            updated = self.backend.read_guide_group(node)
            self._guide_group_data_by_node[node] = updated
            self._updating_widgets = True
            try:
                self.guide_group_name.setText(updated.name)
                self.guide_group_symmetry_axis.setEnabled(
                    updated.symmetry_enabled
                )
                self.guide_group_symmetry_space.setEnabled(
                    updated.symmetry_enabled
                )
                self._set_guide_item_label(node)
            finally:
                self._updating_widgets = False
            self._refresh_guide_group_combo()
            self._refresh_scale_type_guide_combo()
            if category is not ChangeCategory.DISPLAY:
                self._parameter_changed(category)
        except Exception as exc:
            if group is not None:
                self._updating_widgets = True
                try:
                    self.guide_group_name.setText(group.name)
                finally:
                    self._updating_widgets = False
            self._append("Guide Group update failed: {}".format(exc))

    def _poll_scene_selection_and_tool(self) -> None:
        draw_context.sync_active_tool()
        self._sync_guide_selection_from_maya()

    def _poll_guide_changes(self) -> None:
        if (
            self.backend.binding is None
            or self._updating_widgets
            or self._guide_undo_open
        ):
            return
        try:
            category, presentation_changed = self.backend.poll_guide_state()
        except Exception:
            return
        if category is None and not presentation_changed:
            return
        selected = self._current_guide_item_id() or self._scene_selected_guide_item
        self._refresh_guides(preferred=selected or None)
        if self._guide_link_undo_sync and presentation_changed:
            try:
                scene_types = list(self.backend.read_settings().scale_types)
            except Exception:
                scene_types = self._scale_types
            if scene_types != self._scale_types:
                row = self.scale_type_list.currentRow()
                self._scale_types = scene_types
                self._refresh_scale_type_list(select_row=max(0, row))
        if category is not None and self.auto_preview.isChecked():
            self._parameter_changed(category)

    def _refresh_scale_type_guide_combo(self) -> None:
        current_id = ""
        if self.type_guide_combo.count() > 0:
            current_id = str(
                self.type_guide_combo.itemData(
                    self.type_guide_combo.currentIndex()
                )
                or ""
            )
        self.type_guide_combo.blockSignals(True)
        try:
            self.type_guide_combo.clear()
            self.type_guide_combo.addItem("None", "")
            for node in self._guide_group_nodes:
                group = self._guide_group_data_by_node.get(node)
                if group is None:
                    continue
                self.type_guide_combo.addItem(
                    "Group | {}".format(group.name),
                    group.group_id,
                )
            for node in self._guide_nodes:
                guide = self._guide_data_by_node.get(node)
                if guide is None:
                    continue
                self.type_guide_combo.addItem(
                    "Guide | {}".format(guide.name),
                    guide.guide_id,
                )
            selected_index = 0
            for index in range(self.type_guide_combo.count()):
                if str(self.type_guide_combo.itemData(index) or "") == current_id:
                    selected_index = index
                    break
            self.type_guide_combo.setCurrentIndex(selected_index)
        finally:
            self.type_guide_combo.blockSignals(False)

    def _refresh_scale_type_list(self, select_row: int | None = None) -> None:
        current = self.scale_type_list.currentRow()
        row = current if select_row is None else select_row
        self.scale_type_list.blockSignals(True)
        try:
            self.scale_type_list.clear()
            for item in self._scale_types:
                state = "" if item.enabled else " [OFF]"
                link_state = " [Guide]" if item.guide_id else ""
                self.scale_type_list.addItem(
                    "{}{}{}".format(item.name, link_state, state)
                )
            if self._scale_types:
                self.scale_type_list.setCurrentRow(
                    max(0, min(len(self._scale_types) - 1, row))
                )
        finally:
            self.scale_type_list.blockSignals(False)
        self._scale_type_selection_changed(self.scale_type_list.currentRow())

    @QtCore.Slot(int)
    def _scale_type_selection_changed(self, row: int) -> None:
        if not (0 <= row < len(self._scale_types)):
            return
        item = self._scale_types[row]
        self._updating_widgets = True
        try:
            self.type_name.setText(item.name)
            self.type_enabled.setChecked(item.enabled)
            self.type_size.setValue(item.size_multiplier)
            self.type_width.setValue(item.width_multiplier)
            self.type_length.setValue(item.length_multiplier)
            self.type_curvature.setValue(item.curvature_multiplier)
            self.type_offset.setValue(item.offset)
            self.type_random_offset.setValue(item.random_offset)
            self.type_tip_offset.setValue(item.tip_offset)
            self._refresh_scale_type_guide_combo()
            guide_index = 0
            for index in range(self.type_guide_combo.count()):
                if str(self.type_guide_combo.itemData(index) or "") == item.guide_id:
                    guide_index = index
                    break
            self.type_guide_combo.setCurrentIndex(guide_index)
            self.type_custom_color.setChecked(item.use_custom_color)
            self.type_color_r.setValue(item.color_r)
            self.type_color_g.setValue(item.color_g)
            self.type_color_b.setValue(item.color_b)
        finally:
            self._updating_widgets = False

    def _scale_type_editor_changed(self, *_args) -> None:
        if self._updating_widgets:
            return
        row = self.scale_type_list.currentRow()
        if not (0 <= row < len(self._scale_types)):
            return
        self._guide_link_undo_sync = False
        current = self._scale_types[row]
        guide_id = str(
            self.type_guide_combo.itemData(self.type_guide_combo.currentIndex())
            or ""
        )
        self._scale_types[row] = replace(
            current,
            name=self.type_name.text().strip() or current.name,
            enabled=self.type_enabled.isChecked(),
            size_multiplier=self.type_size.value(),
            width_multiplier=self.type_width.value(),
            length_multiplier=self.type_length.value(),
            curvature_multiplier=self.type_curvature.value(),
            offset=self.type_offset.value(),
            random_offset=self.type_random_offset.value(),
            tip_offset=self.type_tip_offset.value(),
            guide_id=guide_id,
            use_custom_color=self.type_custom_color.isChecked(),
            color_r=self.type_color_r.value(),
            color_g=self.type_color_g.value(),
            color_b=self.type_color_b.value(),
        )
        self._refresh_scale_type_list(select_row=row)
        self._parameter_changed(ChangeCategory.SHAPE)

    @QtCore.Slot()
    def _add_scale_type(self) -> None:
        self._guide_link_undo_sync = False
        index = len(self._scale_types) + 1
        self._scale_types.append(
            ScaleTypeSettings(
                type_id="type_{}".format(uuid.uuid4().hex[:10]),
                name="Type {}".format(index),
                enabled=True,
            )
        )
        self._refresh_scale_type_list(select_row=len(self._scale_types) - 1)
        self._parameter_changed(ChangeCategory.SHAPE, settle=True)

    @QtCore.Slot()
    def _duplicate_scale_type(self) -> None:
        self._guide_link_undo_sync = False
        row = self.scale_type_list.currentRow()
        if not (0 <= row < len(self._scale_types)):
            return
        source = self._scale_types[row]
        self._scale_types.insert(
            row + 1,
            replace(
                source,
                type_id="type_{}".format(uuid.uuid4().hex[:10]),
                name=source.name + " Copy",
            ),
        )
        self._refresh_scale_type_list(select_row=row + 1)
        self._parameter_changed(ChangeCategory.SHAPE, settle=True)

    @QtCore.Slot()
    def _remove_scale_type(self) -> None:
        self._guide_link_undo_sync = False
        row = self.scale_type_list.currentRow()
        if len(self._scale_types) <= 1 or not (0 <= row < len(self._scale_types)):
            return
        self._scale_types.pop(row)
        self._refresh_scale_type_list(select_row=max(0, row - 1))
        self._parameter_changed(ChangeCategory.SHAPE, settle=True)

    def _move_scale_type(self, offset: int) -> None:
        self._guide_link_undo_sync = False
        row = self.scale_type_list.currentRow()
        destination = row + int(offset)
        if not (0 <= row < len(self._scale_types)) or not (
            0 <= destination < len(self._scale_types)
        ):
            return
        item = self._scale_types.pop(row)
        self._scale_types.insert(destination, item)
        self._refresh_scale_type_list(select_row=destination)
        self._parameter_changed(ChangeCategory.SHAPE, settle=True)

    @QtCore.Slot()
    def _begin_interaction(self) -> None:
        if self._updating_widgets or not self.auto_preview.isChecked():
            return
        self._inactivity.stop()
        self.scheduler.begin_interaction()

    @QtCore.Slot()
    def _begin_guide_interaction(self) -> None:
        if self._updating_widgets:
            return
        if not self._guide_undo_open:
            try:
                self.backend.begin_undo_chunk("Bifrost Scales Guide Edit")
                self._guide_undo_open = True
            except Exception:
                self._guide_undo_open = False
        self._begin_interaction()

    def _parameter_changed(self, category: ChangeCategory, settle: bool = False) -> None:
        if self._updating_widgets or not self.auto_preview.isChecked() or self.backend.binding is None:
            return
        self.scheduler.begin_interaction()
        self.scheduler.queue_change(category, self._snapshot())
        if settle:
            self.scheduler.end_interaction()
        else:
            self._inactivity.start(self.settled_delay.value())

    @QtCore.Slot()
    def _finish_interaction(self) -> None:
        if not self.auto_preview.isChecked():
            return
        self._inactivity.stop()
        self.scheduler.end_interaction()

    @QtCore.Slot()
    def _finish_guide_interaction(self) -> None:
        if self._guide_undo_open:
            try:
                self.backend.end_undo_chunk()
            finally:
                self._guide_undo_open = False
        self._finish_interaction()

    @QtCore.Slot(bool)
    def _auto_preview_toggled(self, enabled: bool) -> None:
        if enabled:
            self.scheduler.clear_error()
            if self.backend.binding is not None:
                self.scheduler.request_settled(
                    ChangeCategory.DISTRIBUTION,
                    self._snapshot(),
                    immediate=True,
                )
        else:
            self.scheduler.pause()

    @QtCore.Slot()
    def _preview_now(self) -> None:
        if self.backend.binding is None:
            self._append("Systemを先に作成してください")
            return
        if self.scheduler.core.status.error:
            self.scheduler.clear_error()
        else:
            self.scheduler.resume()
        self.scheduler.request_settled(
            ChangeCategory.DISTRIBUTION,
            self._snapshot(),
            immediate=True,
        )

    @QtCore.Slot()
    def _delete_system(self) -> None:
        draw_context.stop_draw(cancel=True, reason="System削除のためGuide描画を終了しました")
        if self.backend.binding is None:
            return
        result = QtWidgets.QMessageBox.question(
            self,
            "Bifrost Scales",
            "選択中のSettings、Guide、Native Graphを削除します。Target Meshは残ります。",
        )
        if result != QtWidgets.QMessageBox.Yes:
            return
        self._cancel_preview_queue()
        try:
            self.backend.delete_system()
            self._refresh_systems()
            self._append("System deleted")
        except Exception as exc:
            self._append("Delete failed: {}".format(exc))

    @QtCore.Slot()
    def _toggle_pause(self) -> None:
        if self.scheduler.core.status.state.value == "paused":
            self.scheduler.resume()
            self.pause_button.setText("Pause")
        else:
            self.scheduler.pause()
            self.pause_button.setText("Resume")

    @QtCore.Slot()
    def _clear_fault(self) -> None:
        self.scheduler.clear_error()
        self.status_label.setText("Fault cleared; Previewを明示実行してください")

    @QtCore.Slot()
    def _configure_delays(self, *_args) -> None:
        self._inactivity.setInterval(self.settled_delay.value())
        self.scheduler.configure_delays(
            self.interactive_delay.value(),
            self.settled_delay.value(),
        )
        if (
            not self._updating_widgets
            and self.auto_preview.isChecked()
            and self.backend.binding is not None
        ):
            self.scheduler.request_settled(
                ChangeCategory.APPEARANCE,
                self._snapshot(),
                immediate=False,
            )

    @QtCore.Slot(int, str, object)
    def _request_finished(self, revision: int, mode: str, report: Any) -> None:
        type_summary = ", ".join(
            "{}:{}".format(name, count)
            for name, count in getattr(report, "type_counts", ())
        ) or "-"
        performance_text = (
            "{} | {} | total {:.1f} ms (generate {:.1f} / viewport {:.1f}) | "
            "D:{} O:{} C:{} | guides {}/{} | budget {} → {}".format(
                report.mesh_update,
                getattr(report, "geometry_kind", "card"),
                report.total_ms,
                report.generation_ms,
                report.viewport_ms,
                "hit" if report.cache_hit else "miss",
                "hit" if report.orientation_cache_hit else "miss",
                "hit" if getattr(report, "cell_cache_hit", False) else "miss",
                report.density_guide_count,
                report.direction_guide_count,
                report.effective_budget,
                report.next_interactive_budget,
            )
        )
        if getattr(report, "native_profile_available", False):
            performance_text += (
                "\nNative: {}{} | payload {:.1f} / source {:.1f} / distribution {:.1f} / "
                "orientation {:.1f} / cells {:.1f} / shape {:.1f} / "
                "encode {:.1f} / graph-publish {:.1f} ms | workers D/O/C/S={}/{}/{}/{} | "
                "cell-basis={}{} | cache={} cap={} evict={}".format(
                    report.native_compute_backend or "cpu",
                    " + GPU" if report.native_gpu_compute else "",
                    report.native_payload_decode_ms,
                    report.native_source_decode_ms,
                    report.native_distribution_ms,
                    report.native_orientation_ms,
                    report.native_cells_ms,
                    report.native_shape_ms,
                    report.native_encode_ms,
                    report.native_graph_publish_ms,
                    report.native_distribution_worker_threads,
                    report.native_orientation_worker_threads,
                    report.native_cell_worker_threads,
                    report.native_shape_worker_threads,
                    report.native_cell_cache_basis or "-",
                    " (orientation edit reused)"
                    if report.native_cell_cache_reused_after_orientation_change
                    else "",
                    report.native_stage_cache_scope or "-",
                    report.native_stage_cache_capacity,
                    report.native_stage_cache_evictions,
                )
            )
            if report.native_cells_ms > 0.0:
                performance_text += (
                    "\nCell: setup {:.1f} / neighbors {:.1f} / boundaries {:.1f} / "
                    "projection {:.1f} ms"
                    "\nCell boundary: query {:.1f} / rays {:.1f} ms".format(
                        report.native_cell_setup_ms,
                        report.native_cell_neighbors_ms,
                        report.native_cell_boundaries_ms,
                        report.native_cell_projection_ms,
                        report.native_cell_boundary_query_ms,
                        report.native_cell_boundary_rays_ms,
                    )
                )
            if getattr(report, "native_gpu_compute", False):
                performance_text += (
                    "\nGPU Orientation: {} samples | upload {:.2f} / kernel {:.2f} / "
                    "readback {:.2f} ms | {}".format(
                        report.native_gpu_sample_count,
                        report.native_gpu_upload_ms,
                        report.native_gpu_kernel_ms,
                        report.native_gpu_readback_ms,
                        report.native_gpu_device or "OpenCL GPU",
                    )
                )
            elif getattr(report, "native_gpu_compute_requested", False):
                performance_text += "\nGPU fallback: {}".format(
                    report.native_gpu_fallback_reason or "CPU exact"
                )
            if getattr(report, "native_boundary_density_adapted", False):
                performance_text += "\nBoundary density-adaptive: anchors={}".format(
                    report.native_boundary_anchor_count
                )
        self.performance_label.setText(performance_text)
        self._append(
            "r{} {}: scales={} vtx={} faces={} geometry={} distribution={} orientation={} cell={} "
            "target={} mesh={} attempts={} guides={}/{} relax={}/{} "
            "cellInfo={}/{} clipped={} meanN={:.1f} types=[{}] total={:.1f}ms budget={}→{}".format(
                revision,
                mode,
                report.scale_count,
                report.vertex_count,
                report.face_count,
                getattr(report, "geometry_kind", "card"),
                "hit" if report.cache_hit else "miss",
                "hit" if report.orientation_cache_hit else "miss",
                "hit" if getattr(report, "cell_cache_hit", False) else "miss",
                "hit" if report.target_cache_hit else "miss",
                report.mesh_update,
                report.sampling_attempts,
                report.density_guide_count,
                report.direction_guide_count,
                report.density_relax_iterations,
                report.direction_relax_iterations,
                getattr(report, "cell_count", 0),
                getattr(report, "cell_resolution", 0),
                getattr(report, "cell_clipped_rays", 0),
                getattr(report, "cell_mean_neighbors", 0.0),
                type_summary,
                report.total_ms,
                report.effective_budget,
                report.next_interactive_budget,
            )
        )
        if getattr(report, "native_profile_available", False):
            self._append(
                "r{} native-profile: backend={} gpu={} workers={}/{}/{}/{} cache={}/{} evict={} "
                "payload={:.2f} source={:.2f} distribution={:.2f} "
                "orientation={:.2f} cells={:.2f} "
                "cellParts={:.2f}/{:.2f}/{:.2f}/{:.2f} "
                "boundaryParts={:.2f}/{:.2f} "
                "shape={:.2f} core={:.2f} "
                "encode={:.2f} operator={:.2f} graphPublish={:.2f} ms".format(
                    revision,
                    report.native_compute_backend or "cpu",
                    report.native_gpu_compute,
                    report.native_distribution_worker_threads,
                    report.native_orientation_worker_threads,
                    report.native_cell_worker_threads,
                    report.native_shape_worker_threads,
                    report.native_stage_cache_scope or "-",
                    report.native_stage_cache_capacity,
                    report.native_stage_cache_evictions,
                    report.native_payload_decode_ms,
                    report.native_source_decode_ms,
                    report.native_distribution_ms,
                    report.native_orientation_ms,
                    report.native_cells_ms,
                    report.native_cell_setup_ms,
                    report.native_cell_neighbors_ms,
                    report.native_cell_boundaries_ms,
                    report.native_cell_projection_ms,
                    report.native_cell_boundary_query_ms,
                    report.native_cell_boundary_rays_ms,
                    report.native_shape_ms,
                    report.native_core_total_ms,
                    report.native_encode_ms,
                    report.native_operator_total_ms,
                    report.native_graph_publish_ms,
                )
            )

    @QtCore.Slot(int, str)
    def _request_failed(self, revision: int, message: str) -> None:
        self.auto_preview.blockSignals(True)
        self.auto_preview.setChecked(False)
        self.auto_preview.blockSignals(False)
        self._append("r{} fault: {}".format(revision, message))

    def _update_native_status_label(self, status=None) -> None:
        try:
            status = status or self.backend.native_status()
            graph = self.backend.native_graph() if self.backend.binding is not None else ""
            if status.ready:
                text = "Ready"
                if graph:
                    text += " | Graph: {}".format(graph)
                else:
                    text += " | Graphなし（再構築または新規作成が必要）"
            elif status.rebuild_required:
                text = "Clean rebuild required: {}".format("; ".join(status.reasons))
            elif status.restart_required:
                text = "Restart required: {}".format("; ".join(status.reasons))
            else:
                text = "Not ready: {}".format("; ".join(status.reasons))
            self.native_status_label.setText(text)
            self.native_rebuild_graph_button.setEnabled(bool(status.ready and self.backend.binding is not None))
        except Exception as exc:
            self.native_status_label.setText("Native status error: {}".format(exc))

    @QtCore.Slot()
    def _probe_native_backend(self) -> None:
        status = self.backend.native_status()
        self._update_native_status_label(status)
        self._append(
            "Native probe: {}".format(
                json.dumps(status.to_mapping(), ensure_ascii=False, default=str)
            )
        )

    @QtCore.Slot()
    def _rebuild_native_graph(self) -> None:
        if self.backend.binding is None:
            self._append("Systemを先に作成してください")
            return
        self._cancel_preview_queue()
        result = QtWidgets.QMessageBox.question(
            self,
            "Bifrost Scales",
            "現在のNative Graphを削除して再作成し、Settled Previewを再評価します。",
        )
        if result != QtWidgets.QMessageBox.Yes:
            return
        try:
            graph = self.backend.rebuild_native_graph()
            self._update_native_status_label()
            self._append("Native Graph rebuilt: {}".format(graph))
            self._preview_now()
        except Exception as exc:
            self._append("Native Graph rebuild failed: {}".format(exc))
            self.status_label.setText("Native setup error")

    @QtCore.Slot()
    def _delete_native_graph(self) -> None:
        if self.backend.binding is None:
            return
        self._cancel_preview_queue()
        try:
            deleted = self.backend.delete_native_graph()
            self._update_native_status_label()
            self._append(
                "Native Graph deleted; Previewは停止しています"
                if deleted
                else "Native Graphはありません"
            )
        except Exception as exc:
            self._append("Native Graph delete failed: {}".format(exc))

    @QtCore.Slot()
    def _diagnose(self) -> None:
        try:
            report = probe_environment()
            self.maintenance_text.setPlainText(
                json.dumps(report, ensure_ascii=False, indent=2, default=str)
            )
        except Exception as exc:
            self.maintenance_text.setPlainText("Diagnostics failed: {}".format(exc))

    @QtCore.Slot()
    def _scan_legacy(self) -> None:
        candidates = scan_legacy_installations(cmds_module=self.backend.scene.cmds)
        if not candidates:
            self.maintenance_text.setPlainText("旧ツールのインストールは見つかりませんでした。")
            return
        self.maintenance_text.setPlainText(
            "\n".join(
                "[{}] {}\n  {}".format(item.kind, item.label, item.path)
                for item in candidates
            )
        )

    @QtCore.Slot()
    def _remove_legacy(self) -> None:
        result = QtWidgets.QMessageBox.warning(
            self,
            "旧ツールを削除",
            "旧MayaScales、WoutScales、旧Integrationの既知のインストールを削除します。\n"
            "シーン内データは削除しません。ロード中DLLは再起動後の削除になる場合があります。",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
            QtWidgets.QMessageBox.Cancel,
        )
        if result != QtWidgets.QMessageBox.Yes:
            return
        try:
            report = remove_legacy_installations(
                cmds_module=self.backend.scene.cmds,
                include_external=True,
            )
            self.maintenance_text.setPlainText(
                json.dumps(report.to_mapping(), ensure_ascii=False, indent=2)
            )
        except Exception as exc:
            self.maintenance_text.setPlainText("Cleanup failed: {}".format(exc))


    def _cancel_preview_queue(self) -> None:
        self._inactivity.stop()
        self.scheduler.clear_error()
        if not self.auto_preview.isChecked():
            self.scheduler.pause()

    def _append(self, text: str) -> None:
        self.log.appendPlainText(str(text))

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._finish_guide_interaction()
        draw_context.stop_draw(cancel=True, reason="UIを閉じたためGuide描画を終了しました")
        self._guide_poll.stop()
        self._scene_poll.stop()
        self._inactivity.stop()
        self.scheduler.pause()
        super().closeEvent(event)


def _maya_main_window():
    try:
        from maya import OpenMayaUI  # type: ignore
        from shiboken6 import wrapInstance  # type: ignore

        pointer = OpenMayaUI.MQtUtil.mainWindow()
        return wrapInstance(int(pointer), QtWidgets.QWidget) if pointer else None
    except Exception:
        try:
            from maya import OpenMayaUI  # type: ignore
            from shiboken2 import wrapInstance  # type: ignore

            pointer = OpenMayaUI.MQtUtil.mainWindow()
            return wrapInstance(int(pointer), QtWidgets.QWidget) if pointer else None
        except Exception:
            return None


def show():
    global _WINDOW
    try:
        if _WINDOW is not None:
            _WINDOW.close()
            _WINDOW.deleteLater()
    except Exception:
        pass
    _WINDOW = BifrostScalesWindow(parent=_maya_main_window())
    _WINDOW.show()
    _WINDOW.raise_()
    _WINDOW.activateWindow()
    return _WINDOW
