"""Standalone Bifrost Scales Maya UI."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, replace
from typing import Any

from . import draw_context
from . import i18n
from .backend import NativeMayaBackend
from .diagnostics import probe_environment
from .guides import GuideKind
from .parameter_controls import FloatParameterControl, IntParameterControl
from .qt_compat import QtCore, QtGui, QtWidgets
from .qt_scheduler import QtPreviewScheduler
from .scheduler import ChangeCategory
from .settings import ScaleSettings, ScaleTypeSettings
from .version import VERSION
from .ui_theme import STUDIO_STYLE, ui_icon, add_depth

_WINDOW = None
_GUIDE_NODE_ROLE = int(QtCore.Qt.UserRole)
_GUIDE_ITEM_KIND_ROLE = _GUIDE_NODE_ROLE + 1
_RETIRED_SHAPE_FIELDS = ("lift", "inset", "squash", "expand", "tip_roundness", "tip_offset", "forward_offset")


class _GuideItemDelegate(QtWidgets.QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        # Keep checkbox events enabled; only names get a text editor.
        if index.column() == 0:
            return super().createEditor(parent, option, index)
        return None


class _GuideTreeWidget(QtWidgets.QTreeWidget):
    """QTreeWidget that reports cross-parent InternalMove drops reliably.

    Qt does not consistently emit ``rowsMoved`` when an item is moved between
    two different parents.  The visible Tree can therefore diverge from the
    Maya DAG/group attribute unless the completed drop itself is observed.
    """

    dropCompleted = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setItemDelegate(_GuideItemDelegate(self))

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt virtual name
        super().dropEvent(event)
        self.dropCompleted.emit()


class BifrostScalesWindow(QtWidgets.QDialog):
    def __init__(self, parent: Any | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("BifrostScalesStandaloneWindow")
        self.setWindowTitle("Bifrost Scales {}".format(VERSION))
        self.resize(760, 900)
        self.backend = NativeMayaBackend()
        self.scheduler = QtPreviewScheduler(self.backend, parent=self)
        self._inactivity = QtCore.QTimer(self)
        self._inactivity.setSingleShot(True)
        self._inactivity.setInterval(180)
        self._inactivity.timeout.connect(self._finish_interaction)
        self._updating_widgets = False
        self._scale_types = list(ScaleSettings().scale_types)
        self._sculpt_surface = {}
        self._legacy_curves = {"width_curve": ScaleSettings().width_curve, "profile_curve": ScaleSettings().profile_curve}
        self._legacy_cell_shape = {"cell_growth": 0.85, "cell_shape_divisions": 2}
        self._retained_shape_values = {name: getattr(ScaleSettings(), name) for name in _RETIRED_SHAPE_FIELDS}
        self._guide_nodes: list[str] = []
        self._guide_data_by_node = {}
        self._guide_group_nodes: list[str] = []
        self._guide_group_data_by_node = {}
        self._guide_tree_items_by_node = {}
        self._active_draw_kind: GuideKind | None = None
        defaults = ScaleSettings()
        self._preview_color = (defaults.color_r, defaults.color_g, defaults.color_b)
        self._pending_interactive_budget: int | None = None
        self._pending_interactive_budget_reason = ""
        self._scene_selected_guide_item = ""
        self._scene_selected_guide_items: tuple[str, ...] = ()
        self._syncing_guide_selection = False
        self._guide_tree_drop_pending = False
        self._parameter_undo_open = False
        self._guide_undo_open = False
        self._guide_link_undo_sync = False
        self._guide_callback_ids = []
        self._scene_callback_ids = []
        self._polling_guide_changes = False
        self._build_ui()
        self._connect_ui()
        application = QtWidgets.QApplication.instance()
        if application is not None:
            application.installEventFilter(self)
        self._guide_poll = QtCore.QTimer(self)
        self._guide_poll.setSingleShot(True)
        self._guide_poll.setInterval(180)
        self._guide_poll.timeout.connect(self._poll_guide_changes)
        self._scene_poll = QtCore.QTimer(self)
        self._scene_poll.setSingleShot(True)
        self._scene_poll.setInterval(0)
        self._scene_poll.timeout.connect(self._poll_scene_selection_and_tool)
        self._watch_scene_events()
        self._refresh_systems()
        self._change_language()

    def eventFilter(self, watched, event):  # noqa: N802 - Qt API
        if (
            event.type() == QtCore.QEvent.KeyPress
            and event.key() == QtCore.Qt.Key_G
            and event.modifiers() & QtCore.Qt.ControlModifier
            and not event.isAutoRepeat()
            and self._group_selected_guides_from_shortcut()
        ):
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def _build_ui(self) -> None:
        self.setStyleSheet(STUDIO_STYLE)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)
        language_row = QtWidgets.QHBoxLayout()
        brand = QtWidgets.QLabel("BIFROST SCALES")
        brand.setObjectName("brand")
        language_row.addWidget(brand)
        language_row.addStretch()
        self.language_switch = QtWidgets.QComboBox()
        self.language_switch.addItem("日本語", "ja")
        self.language_switch.addItem("English", "en")
        self.language_switch.setAccessibleName("Language / 言語")
        self.language_switch.setCurrentIndex(max(0, self.language_switch.findData(i18n.language())))
        self.language_switch.currentIndexChanged.connect(self._change_language)
        language_row.addWidget(self.language_switch)
        layout.addLayout(language_row)

        system_group = QtWidgets.QWidget()
        system_layout = QtWidgets.QGridLayout(system_group)
        system_layout.setContentsMargins(0, 0, 0, 0)
        system_layout.setVerticalSpacing(4)
        self.system_combo = QtWidgets.QComboBox()
        self.refresh_systems_button = QtWidgets.QPushButton("再検索")
        self.create_system_button = QtWidgets.QPushButton("New System")
        self.create_system_button.setToolTip("Create from Selected Mesh")
        self.set_target_button = QtWidgets.QPushButton("選択メッシュへ変更")
        self.refresh_target_button = QtWidgets.QPushButton("Target形状を再読込")
        self.target_label = QtWidgets.QLabel("Target: 未設定")
        self.target_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.target_label.setWordWrap(True)
        system_layout.addWidget(QtWidgets.QLabel("System"), 0, 0)
        system_layout.addWidget(self.system_combo, 0, 1)
        system_layout.addWidget(self.refresh_systems_button, 0, 2)
        system_layout.addWidget(self.create_system_button, 0, 3)
        system_layout.addWidget(self.target_label, 1, 0, 1, 3)
        system_layout.setColumnStretch(1, 1)
        target_menu_button = QtWidgets.QToolButton()
        target_menu_button.setText("Target Actions")
        target_menu_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        target_menu = QtWidgets.QMenu(target_menu_button)
        for button in (self.set_target_button, self.refresh_target_button):
            button.setParent(self)
            button.hide()
            target_menu.addAction(button.text(), button.click)
        target_menu_button.setMenu(target_menu)
        system_layout.addWidget(target_menu_button, 1, 3)
        layout.addWidget(system_group)

        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs, 1)
        self._build_global_tab()
        self._build_guides_tab()
        self._build_scale_types_tab()
        self._build_preview_tab()
        self._build_maintenance_tab()
        for index, name in enumerate(("parameters", "guides", "types", "display")):
            self.tabs.setTabIcon(index, ui_icon(name))
        self.tabs.setIconSize(QtCore.QSize(16, 16))
        self.tabs.tabBar().setExpanding(False)
        self.edit_sculpt.setIcon(ui_icon("sculpt"))

        action_layout = QtWidgets.QHBoxLayout()
        self.create_mesh_button = QtWidgets.QPushButton("Create Mesh")
        self.create_mesh_button.setIcon(ui_icon("mesh"))
        self.create_mesh_button.setProperty("primary", True)
        self.create_mesh_button.setToolTip("Create an independent Maya mesh from the current preview. The source system is preserved.")
        self.create_mesh_button.clicked.connect(self._create_maya_mesh)
        self.delete_system_button = QtWidgets.QPushButton("System削除")
        self.delete_system_button.setProperty("danger", True)
        action_layout.addWidget(self.delete_system_button)
        action_layout.addStretch()
        action_layout.addWidget(self.create_mesh_button)
        self.maintenance_button = QtWidgets.QToolButton()
        self.maintenance_button.setIcon(ui_icon("parameters"))
        self.maintenance_button.setToolTip("Maintenance / メンテナンス")
        self.maintenance_button.setAccessibleName("Maintenance / メンテナンス")
        self.maintenance_button.clicked.connect(self._show_maintenance)
        action_layout.addWidget(self.maintenance_button)
        layout.addLayout(action_layout)

        status_group = QtWidgets.QWidget()
        status_layout = QtWidgets.QVBoxLayout(status_group)
        status_layout.setContentsMargins(0, 0, 0, 0)
        self.status_label = QtWidgets.QLabel("Idle")
        self.preview_limit_warning = QtWidgets.QLabel()
        self.preview_limit_warning.setWordWrap(True)
        self.preview_limit_warning.hide()
        status_layout.addWidget(self.preview_limit_warning)
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        self.log.setMinimumHeight(130)
        status_layout.addWidget(self.status_label)
        self.maintenance_dialog.layout().addWidget(self.log)
        layout.addWidget(status_group)
        add_depth(self)

    def _global_section(self, title: str, parent_layout):
        group = QtWidgets.QGroupBox(title)
        form = QtWidgets.QFormLayout(group)
        form.setContentsMargins(0, 8, 0, 4)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(4)
        form.setLabelAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        parent_layout.addWidget(group)
        return form

    def _change_language(self, *_args) -> None:
        locale = self.language_switch.currentData()
        i18n.set_language(locale)
        i18n.translate_window(self, locale)
        labels = [form.itemAt(row, QtWidgets.QFormLayout.LabelRole).widget()
                  for form in self._global_forms for row in range(form.rowCount())
                  if form.itemAt(row, QtWidgets.QFormLayout.LabelRole) is not None]
        label_width = max(label.sizeHint().width() for label in labels)
        for label in labels:
            label.setFixedWidth(label_width)
        # Only static choice captions; system/guide/type names are authored data.
        for combo in (self.guide_symmetry_space, self.guide_group_symmetry_space):
            blocked = combo.blockSignals(True)
            try:
                for index in range(combo.count()):
                    combo.setItemText(index, i18n.translate(combo.itemText(index), locale))
            finally:
                combo.blockSignals(blocked)
        header = self.guide_tree.headerItem()
        for index in range(self.guide_tree.columnCount()):
            header.setText(index, i18n.translate(header.text(index), locale))
        self._update_preview_limit_warning()

    def _update_preview_limit_warning(self) -> None:
        # Budget estimation needs only topology metadata, not copied sculpt samples.
        settings = ScaleSettings(
            target_count=self.target_count.value(), cell_mode="auto",
            cell_settled_resolution=self.cell_settled_resolution.value(),
            cell_shape_divisions=self._legacy_cell_shape["cell_shape_divisions"],
            cell_projection_rings=self.cell_projection_rings.value(),
            sculpt_settled_resolution=self.sculpt_settled_resolution.value(),
            sculpt_surface=self._sculpt_surface, scale_types=self._scale_types)
        limited = settings.settled_budget < settings.target_count
        self.preview_limit_warning.setVisible(limited)
        template = (
            "Warning: preview limited to {limit:,} of {target:,} scales to limit estimated geometry load. Reduce subdivisions to show more."
            if i18n.language() == "en" else
            "警告: 推定生成量が大きいため、プレビューを {target:,} 枚中 {limit:,} 枚に制限しています。分割数を下げると表示可能枚数が増えます。"
        )
        self.preview_limit_warning.setText(template.format(limit=settings.settled_budget, target=settings.target_count) if limited else "")

    def _build_global_tab(self) -> None:
        """Build one ordered Global tab for placement, cells, and base shape."""

        tab = QtWidgets.QWidget()
        tab_layout = QtWidgets.QVBoxLayout(tab)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        content = QtWidgets.QWidget()
        content.setObjectName("settingsContent")
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        self.show_advanced_parameters = QtWidgets.QCheckBox("詳細パラメータを表示")
        self.show_advanced_parameters.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.show_advanced_parameters.setToolTip(
            "高度な調整項目だけを表示します。この表示状態はSceneへ保存しません。"
        )
        layout.addWidget(self.show_advanced_parameters)

        distribution = self._global_section("1. 配置", layout)
        self.target_count = IntParameterControl(1, 50000, 512)
        distribution.addRow("鱗の数", self.target_count)
        self.seed = QtWidgets.QSpinBox()
        self.seed.setRange(-2147483647, 2147483647)
        self.seed.setValue(1)
        self.seed.setKeyboardTracking(True)
        distribution.addRow("ランダムシード", self.seed)
        self.spacing_factor = FloatParameterControl(
            0.15, 2.5, 0.82, decimals=3, single_step=0.05
        )
        distribution.addRow("配置間隔", self.spacing_factor)
        self.relax_iterations = IntParameterControl(0, 64, 0)
        distribution.addRow("配置の均し回数", self.relax_iterations)
        self.relax_strength = FloatParameterControl(
            0.0, 1.0, 0.45, decimals=3, single_step=0.05
        )
        distribution.addRow("配置の均し強度", self.relax_strength)
        self.reset_distribution_button = QtWidgets.QPushButton("配置を既定値へ戻す")
        distribution.addRow(self.reset_distribution_button)

        orientation = self._global_section("2. 向き・流れ", layout)
        self.direction = FloatParameterControl(
            -360.0, 360.0, 0.0, decimals=2, single_step=5.0, suffix=" deg"
        )
        orientation.addRow("全体の向き", self.direction)
        self.random_rotation = FloatParameterControl(
            0.0, 180.0, 8.0, decimals=2, single_step=2.0, suffix=" deg"
        )
        orientation.addRow("向きのランダム幅", self.random_rotation)
        self.direction_relax_iterations = IntParameterControl(0, 64, 0)
        orientation.addRow(
            "向きの均し回数", self.direction_relax_iterations
        )
        self.direction_relax_strength = FloatParameterControl(
            0.0, 1.0, 0.35, decimals=3, single_step=0.05
        )
        orientation.addRow("向きの均し強度", self.direction_relax_strength)
        orientation_note = QtWidgets.QLabel(
            "ガイドの描画方向で鱗の前後を指定します。逆向きに描くと180°反転します。"
        )
        orientation_note.setWordWrap(True)
        orientation.addRow(orientation_note)
        self.reset_orientation_button = QtWidgets.QPushButton("向きを既定値へ戻す")
        orientation.addRow(self.reset_orientation_button)

        cells = self._global_section("3. 鱗の境界・表面", layout)
        self.cell_gap = FloatParameterControl(
            0.0, 0.49, 0.06, decimals=3, single_step=0.01
        )
        cells.addRow("鱗の隙間", self.cell_gap)
        self.cell_collision_margin = FloatParameterControl(
            0.0, 0.49, 0.02, decimals=3, single_step=0.01
        )
        cells.addRow("衝突余白", self.cell_collision_margin)
        self.cell_radius_multiplier = FloatParameterControl(
            0.35, 6.0, 1.65, decimals=3, single_step=0.05
        )
        cells.addRow("開いた境界の範囲", self.cell_radius_multiplier)
        self.cell_direction_anisotropy = FloatParameterControl(
            0.0, 1.0, 0.4, decimals=3, single_step=0.05
        )
        self.cell_direction_anisotropy.setToolTip(
            "0は従来の等方Cell、1はGuide効果内で最大2.25倍の方向性を与えます。"
        )
        cells.addRow("流れ方向への伸び", self.cell_direction_anisotropy)
        self.cell_settled_resolution = QtWidgets.QSpinBox()
        self.cell_settled_resolution.setRange(4, 32)
        self.cell_settled_resolution.setValue(10)
        cells.addRow("境界の分割数", self.cell_settled_resolution)
        self.cell_projection_rings = QtWidgets.QSpinBox()
        self.cell_projection_rings.setRange(0, 16)
        self.cell_projection_rings.setValue(2)
        cells.addRow("表面追従リング", self.cell_projection_rings)
        self.cell_project_to_surface = QtWidgets.QCheckBox(
            "Cell境界をTargetへ再投影"
        )
        self.cell_project_to_surface.setChecked(True)
        cells.addRow(self.cell_project_to_surface)
        self.reset_cells_button = QtWidgets.QPushButton("境界を既定値へ戻す")
        cells.addRow(self.reset_cells_button)

        shape = self._global_section("4. 鱗の基本形状", layout)
        self.edit_sculpt = QtWidgets.QPushButton("鱗をスカルプト")
        self.edit_sculpt.setProperty("primary", True)
        self.edit_sculpt.clicked.connect(lambda: self._open_sculpt_editor())
        shape.addRow(self.edit_sculpt)
        self.size = FloatParameterControl(
            0.000001,
            1000000.0,
            0.1,
            decimals=6,
            single_step=0.001,
            mapping="log",
            slider_minimum=0.001,
            slider_maximum=1.0,
        )
        shape.addRow("形状の強さ", self.size)
        self.size.setToolTip("鱗の外周サイズではなく、反り・厚み・スカルプト変位の基準強度。")
        self.normal_offset = FloatParameterControl(-1.0e8, 1.0e8, 0.0, decimals=3,
            single_step=0.01, slider_minimum=-100.0, slider_maximum=100.0, suffix=" %")
        self.normal_offset.setToolTip("内部の厚み。外周は固定。Typeの厚み補正を加算します。")
        shape.addRow("内部の厚み", self.normal_offset)
        self.curvature = FloatParameterControl(
            -1.0e6, 1.0e6, 0.22, decimals=3, single_step=0.05,
            slider_minimum=-4.0, slider_maximum=4.0
        )
        shape.addRow("反り", self.curvature)
        self.sculpt_settled_resolution = QtWidgets.QSpinBox()
        for control, value, label in (
            (self.sculpt_settled_resolution, 8, "内側の分割数"),
        ):
            control.setRange(4, 32)
            control.setValue(value)
            control.valueChanged.connect(lambda: self._parameter_changed(ChangeCategory.SHAPE))
            shape.addRow(label, control)
        self.random_size = FloatParameterControl(
            0.0, 0.95, 0.12, decimals=3, single_step=0.05
        )
        shape.addRow("形状の強さのばらつき", self.random_size)
        shape_note = QtWidgets.QLabel(
            "外周・Gapを保持し、内部の形状と厚みを調整します。厚みは形状の強さを基準にした%表示です。\n"
            "色はScale TypesごとのVertex Colorで管理します。"
        )
        shape_note.setWordWrap(True)
        shape.addRow(shape_note)
        self.reset_shape_button = QtWidgets.QPushButton("形状を既定値へ戻す")
        shape.addRow(self.reset_shape_button)

        for button in (
            self.reset_distribution_button,
            self.reset_orientation_button,
            self.reset_cells_button,
            self.reset_shape_button,
        ):
            button.setProperty("quiet", True)
            button.setToolTip("このSectionだけを既定値へ戻します。1回のUndoで復元できます。")

        for widget, tooltip in (
            (self.target_count, "生成する鱗の目標数。既定値: 512 / 影響: 配置"),
            (self.seed, "配置のランダム系列。既定値: 1 / 影響: 配置"),
            (self.spacing_factor, "鱗同士の配置間隔。既定値: 0.82 / 影響: 配置"),
            (self.relax_iterations, "配置を近傍で均す回数。既定値: 0 / 影響: 配置"),
            (self.relax_strength, "配置を均す強さ。既定値: 0.45 / 影響: 配置"),
            (self.direction, "全体の回転角度。既定値: 0 deg / 影響: 向き"),
            (self.random_rotation, "鱗ごとの回転幅。既定値: 8 deg / 影響: 向き"),
            (self.direction_relax_iterations, "向きを近傍で均す回数。既定値: 0 / 影響: 向き"),
            (self.direction_relax_strength, "向きを均す強さ。既定値: 0.35 / 影響: 向き"),
            (self.cell_gap, "隣接する鱗の隙間。既定値: 0.06 / 影響: 境界"),
            (self.cell_collision_margin, "鱗同士の衝突を避ける余白。既定値: 0.02 / 影響: 境界"),
            (self.cell_radius_multiplier, "開いた境界を探索する範囲。既定値: 1.65 / 影響: 境界"),
            (self.cell_direction_anisotropy, "Guideの流れ方向へ境界を伸ばす量。既定値: 0.4 / 影響: 境界"),
            (self.cell_settled_resolution, "停止後の境界分割数。既定値: 10 / 影響: 境界"),
            (self.cell_projection_rings, "Target表面へ追従させる内側リング数。既定値: 2 / 影響: 境界"),
            (self.cell_project_to_surface, "境界をTarget表面へ再投影します。既定値: On / 影響: 境界"),
            (self.size, "形状の強さ。外周サイズではなく反り・厚み・スカルプト変位の基準。"),
            (self.curvature, "RootからTipまでの反り。既定値: 0.22 / 影響: 形状"),
            (self.random_size, "鱗ごとのサイズ幅。既定値: 0.12 / 影響: 形状"),
        ):
            widget.setToolTip(tooltip)

        self._global_forms = (distribution, orientation, cells, shape)
        for control in content.findChildren(FloatParameterControl) + content.findChildren(IntParameterControl):
            control.spin.setFixedWidth(140)
        self._advanced_parameter_rows = (
            (distribution, self.relax_iterations),
            (distribution, self.relax_strength),
            (orientation, self.direction_relax_iterations),
            (orientation, self.direction_relax_strength),
            (cells, self.cell_collision_margin),
            (cells, self.cell_radius_multiplier),
            (cells, self.cell_direction_anisotropy),
            (cells, self.cell_project_to_surface),
        )
        self._set_advanced_parameters_visible(False)
        self._sync_parameter_dependencies()

        layout.addStretch(1)
        scroll.setWidget(content)
        tab_layout.addWidget(scroll)
        self.tabs.addTab(tab, "Placement & Shape")

    def _set_advanced_parameters_visible(self, visible: bool) -> None:
        for form, field in self._advanced_parameter_rows:
            label = form.labelForField(field)
            if label is not None:
                label.setVisible(bool(visible))
            field.setVisible(bool(visible))

    def _sync_parameter_dependencies(self, *_args) -> None:
        density_enabled = self.relax_iterations.value() > 0
        direction_enabled = self.direction_relax_iterations.value() > 0
        projection_enabled = self.cell_project_to_surface.isChecked()
        self.relax_strength.setEnabled(density_enabled)
        self.direction_relax_strength.setEnabled(direction_enabled)
        self.cell_projection_rings.setEnabled(projection_enabled)
        self.relax_strength.setToolTip(
            "配置を均す強さ。既定値: 0.45 / 影響: 配置"
            + ("" if density_enabled else " / 均し回数が0のため無効")
        )
        self.direction_relax_strength.setToolTip(
            "向きを均す強さ。既定値: 0.35 / 影響: 向き"
            + ("" if direction_enabled else " / 均し回数が0のため無効")
        )
        self.cell_projection_rings.setToolTip(
            "Target表面へ追従させる内側リング数。既定値: 2 / 影響: 境界"
            + ("" if projection_enabled else " / 表面への再投影がOffのため無効")
        )

    def _reset_global_section(self, section: str) -> None:
        defaults = ScaleSettings()
        sections = {
            "distribution": (
                "配置",
                ChangeCategory.DISTRIBUTION,
                (
                    (self.target_count, defaults.target_count),
                    (self.seed, defaults.seed),
                    (self.spacing_factor, defaults.spacing_factor),
                    (self.relax_iterations, defaults.relax_iterations),
                    (self.relax_strength, defaults.relax_strength),
                ),
            ),
            "orientation": (
                "向き",
                ChangeCategory.ORIENTATION,
                (
                    (self.direction, defaults.direction_degrees),
                    (self.random_rotation, defaults.random_rotation_degrees),
                    (
                        self.direction_relax_iterations,
                        defaults.direction_relax_iterations,
                    ),
                    (
                        self.direction_relax_strength,
                        defaults.direction_relax_strength,
                    ),
                ),
            ),
            "cells": (
                "境界",
                ChangeCategory.CELL,
                (
                    (self.cell_gap, defaults.cell_gap),
                    (self.cell_collision_margin, defaults.cell_collision_margin),
                    (self.cell_radius_multiplier, defaults.cell_radius_multiplier),
                    (
                        self.cell_direction_anisotropy,
                        defaults.cell_direction_anisotropy,
                    ),
                    (
                        self.cell_settled_resolution,
                        defaults.cell_settled_resolution,
                    ),
                    (self.cell_projection_rings, defaults.cell_projection_rings),
                ),
            ),
            "shape": (
                "形状",
                ChangeCategory.SHAPE,
                (
                    (self.size, defaults.size),
                    (self.normal_offset, defaults.normal_offset*100.0),
                    (self.curvature, defaults.curvature),
                    (self.random_size, defaults.random_size),
                ),
            ),
        }
        reset = sections.get(str(section))
        if reset is None:
            return
        label, category, fields = reset
        before = self._snapshot()
        self._updating_widgets = True
        try:
            for field, value in fields:
                field.setValue(value)
            if section == "cells":
                self.cell_project_to_surface.setChecked(
                    defaults.cell_project_to_surface
                )
        finally:
            self._updating_widgets = False
        self._sync_parameter_dependencies()
        if self._snapshot() == before:
            return
        self._parameter_changed(category, settle=True)
        self._append("{}を既定値へ戻しました".format(label))

    def _build_guides_tab(self) -> None:
        tab = QtWidgets.QWidget()
        self.guides_tab = tab
        layout = QtWidgets.QVBoxLayout(tab)

        self.guide_search = QtWidgets.QLineEdit()
        self.guide_search.setPlaceholderText("Search Guides and Groups")
        self.guide_search.setClearButtonEnabled(True)
        layout.addWidget(self.guide_search)

        self.guide_tree = _GuideTreeWidget()
        self.guide_tree.setColumnCount(5)
        self.guide_tree.setHeaderLabels(("Name", "Info", "Visible", "Lock", "Scale Types"))
        header = self.guide_tree.header()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(4, QtWidgets.QHeaderView.Stretch)
        for column in (1, 2, 3):
            header.setSectionResizeMode(
                column,
                QtWidgets.QHeaderView.ResizeToContents,
            )
        self.guide_tree.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked
            | QtWidgets.QAbstractItemView.EditKeyPressed
            | QtWidgets.QAbstractItemView.SelectedClicked
        )
        self.guide_tree.setMinimumHeight(220)
        self.guide_tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
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

        self.guide_type_editor = QtWidgets.QGroupBox("Scale Type Link")
        link_layout = QtWidgets.QHBoxLayout(self.guide_type_editor)
        self.guide_type_combo = QtWidgets.QComboBox()
        self.assign_guide_type_button = QtWidgets.QPushButton("Assign Here")
        self.unassign_guide_type_button = QtWidgets.QPushButton("Unassign")
        link_layout.addWidget(self.guide_type_combo, 1)
        link_layout.addWidget(self.assign_guide_type_button)
        link_layout.addWidget(self.unassign_guide_type_button)
        layout.addWidget(self.guide_type_editor)

        self.guide_editor.setVisible(False)
        self.guide_group_editor.setVisible(False)
        self.guide_type_editor.setVisible(False)
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
        self.tabs.addTab(tab, "Guide Editor")

    def _build_scale_types_tab(self) -> None:
        tab = QtWidgets.QWidget()
        self.scale_types_tab = tab
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
        editor.setObjectName("settingsContent")
        form = QtWidgets.QFormLayout(editor)
        self.type_name = QtWidgets.QLineEdit()
        form.addRow("Name", self.type_name)
        self.type_enabled = QtWidgets.QCheckBox("Enabled")
        form.addRow(self.type_enabled)
        self.type_size = FloatParameterControl(0.05, 8.0, 1.0, decimals=3, mapping="log")
        form.addRow("形状の強さ倍率", self.type_size)
        self.type_curvature = FloatParameterControl(-4.0, 4.0, 1.0, decimals=3)
        form.addRow("Curvature", self.type_curvature)
        self.edit_type_sculpt = QtWidgets.QPushButton("鱗をスカルプト")
        self.edit_type_sculpt.setProperty("primary", True)
        self.edit_type_sculpt.setIcon(ui_icon("sculpt"))
        self.edit_type_sculpt.clicked.connect(lambda: self._open_sculpt_editor(per_type=True))
        form.addRow(self.edit_type_sculpt)
        self.type_offset = FloatParameterControl(-1.0e8, 1.0e8, 0.0, decimals=3,
            single_step=0.01, slider_minimum=-100.0, slider_maximum=100.0, suffix=" %")
        self.type_offset.setToolTip("Globalの内部厚みに加算する補正値。外周は固定します。")
        form.addRow("内部の厚み補正", self.type_offset)
        self.type_random_offset = FloatParameterControl(0.0, 1.0, 0.0, decimals=3)
        form.addRow("Random Offset", self.type_random_offset)
        self.type_guide_combo = QtWidgets.QComboBox()
        form.addRow("Guide Link", self.type_guide_combo)
        link_actions = QtWidgets.QHBoxLayout()
        self.filter_type_link_button = QtWidgets.QPushButton("Show Linked")
        self.jump_type_link_button = QtWidgets.QPushButton("Jump to Link")
        link_actions.addWidget(self.filter_type_link_button)
        link_actions.addWidget(self.jump_type_link_button)
        form.addRow(link_actions)
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
        self.interactive_budget.setEnabled(False)
        form.addRow("Interactive上限", self.interactive_budget)

        self.auto_preview_budget = QtWidgets.QCheckBox("上限を自動調整")
        self.auto_preview_budget.setChecked(True)
        form.addRow(self.auto_preview_budget)
        self.auto_preview_budget_label = QtWidgets.QLabel(
            "Auto: 128（次の操作から直近時間に合わせて調整）"
        )
        self.auto_preview_budget_label.setWordWrap(True)
        form.addRow("選択理由", self.auto_preview_budget_label)

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

        self.tabs.addTab(tab, "Display & Updates")

    def _build_maintenance_tab(self) -> None:
        tab = self.maintenance_dialog = QtWidgets.QDialog(self)
        tab.setWindowTitle("Maintenance / メンテナンス")
        tab.resize(640, 600)
        layout = QtWidgets.QVBoxLayout(tab)
        buttons = QtWidgets.QHBoxLayout()
        self.diagnostics_button = QtWidgets.QPushButton("環境診断")
        buttons.addWidget(self.diagnostics_button)
        layout.addLayout(buttons)
        self.maintenance_text = QtWidgets.QPlainTextEdit()
        self.maintenance_text.setReadOnly(True)
        layout.addWidget(self.maintenance_text, 1)

    def _show_maintenance(self) -> None:
        self.maintenance_dialog.show()
        self.maintenance_dialog.raise_()
        self.maintenance_dialog.activateWindow()

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
        self.delete_system_button.clicked.connect(self._delete_system)
        self.auto_preview.toggled.connect(self._auto_preview_toggled)
        self.auto_preview_budget.toggled.connect(self._auto_preview_budget_toggled)
        self.interactive_budget.valueChanged.connect(self._interactive_budget_changed)
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
        self.native_probe_button.clicked.connect(self._probe_native_backend)
        self.native_rebuild_graph_button.clicked.connect(self._rebuild_native_graph)
        self.native_delete_graph_button.clicked.connect(self._delete_native_graph)
        self.show_advanced_parameters.toggled.connect(
            self._set_advanced_parameters_visible
        )
        self.relax_iterations.valueChanged.connect(self._sync_parameter_dependencies)
        self.direction_relax_iterations.valueChanged.connect(
            self._sync_parameter_dependencies
        )
        self.cell_project_to_surface.toggled.connect(
            self._sync_parameter_dependencies
        )
        self.reset_distribution_button.clicked.connect(
            lambda: self._reset_global_section("distribution")
        )
        self.reset_orientation_button.clicked.connect(
            lambda: self._reset_global_section("orientation")
        )
        self.reset_cells_button.clicked.connect(
            lambda: self._reset_global_section("cells")
        )
        self.reset_shape_button.clicked.connect(
            lambda: self._reset_global_section("shape")
        )
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
        for widget in (
            self.cell_gap,
            self.cell_collision_margin,
            self.cell_radius_multiplier,
            self.cell_direction_anisotropy,
            self.cell_settled_resolution,
            self.cell_projection_rings,
        ):
            self._connect_parameter(widget, ChangeCategory.CELL)
        self.cell_project_to_surface.toggled.connect(
            lambda *_args: self._parameter_changed(ChangeCategory.CELL, settle=True)
        )
        for widget in (
            self.size,
            self.normal_offset,
            self.curvature,
            self.random_size,
        ):
            self._connect_parameter(widget, ChangeCategory.SHAPE)
        self._connect_parameter(self.interactive_budget, ChangeCategory.DISTRIBUTION)
        self.guide_tree.currentItemChanged.connect(self._guide_selection_changed)
        self.guide_tree.itemSelectionChanged.connect(
            self._guide_tree_selection_changed
        )
        self.guide_search.textChanged.connect(self._filter_guide_tree)
        self.guide_tree.itemChanged.connect(self._guide_tree_item_changed)
        self.guide_tree.itemCollapsed.connect(self._guide_group_collapsed)
        self.guide_tree.itemExpanded.connect(self._guide_group_expanded)
        self.guide_tree.model().rowsMoved.connect(self._guide_tree_rows_moved)
        self.guide_tree.dropCompleted.connect(self._guide_tree_rows_moved)
        self.guide_type_combo.currentIndexChanged.connect(
            self._guide_type_selection_changed
        )
        self.assign_guide_type_button.clicked.connect(
            self._assign_current_scale_type
        )
        self.unassign_guide_type_button.clicked.connect(
            self._unassign_current_scale_type
        )
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
        self.filter_type_link_button.clicked.connect(
            self._filter_guides_for_scale_type
        )
        self.jump_type_link_button.clicked.connect(
            self._jump_to_scale_type_link
        )
        for widget in (
            self.type_size,
            self.type_curvature,
            self.type_offset,
            self.type_random_offset,
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
            **self._retained_shape_values,
            "curvature": self.curvature.value(),
            **self._legacy_curves,
            "normal_offset": self.normal_offset.value()/100.0,
            "sculpt_surface": self._sculpt_surface,
            "sculpt_interactive_resolution": 4,
            "sculpt_settled_resolution": self.sculpt_settled_resolution.value(),
            "direction_degrees": self.direction.value(),
            "direction_relax_iterations": self.direction_relax_iterations.value(),
            "direction_relax_strength": self.direction_relax_strength.value(),
            "random_size": self.random_size.value(),
            "random_rotation_degrees": self.random_rotation.value(),
            "cell_mode": "auto",
            **self._legacy_cell_shape,
            "cell_gap": self.cell_gap.value(),
            "cell_collision_margin": self.cell_collision_margin.value(),
            "cell_radius_multiplier": self.cell_radius_multiplier.value(),
            "cell_direction_anisotropy": self.cell_direction_anisotropy.value(),
            "cell_interactive_resolution": 6,
            "cell_settled_resolution": self.cell_settled_resolution.value(),
            "cell_projection_rings": self.cell_projection_rings.value(),
            "cell_project_to_surface": self.cell_project_to_surface.isChecked(),
            "scale_types": [asdict(item) for item in self._scale_types],
            "interactive_budget": self.interactive_budget.value(),
            "settled_budget": self.target_count.value(),
            "interactive_delay_ms": self.interactive_delay.value(),
            "settled_delay_ms": self.settled_delay.value(),
            "visible": self.visible.isChecked(),
            "color_r": self._preview_color[0],
            "color_g": self._preview_color[1],
            "color_b": self._preview_color[2],
        }

    def _load_settings(
        self,
        settings: ScaleSettings,
        *,
        refresh_scene: bool = True,
    ) -> None:
        self._updating_widgets = True
        try:
            self.target_count.setValue(settings.target_count)
            self.seed.setValue(settings.seed)
            self.spacing_factor.setValue(settings.spacing_factor)
            self.relax_iterations.setValue(settings.relax_iterations)
            self.relax_strength.setValue(settings.relax_strength)
            self.size.setValue(settings.size)
            self._retained_shape_values = {name: getattr(settings, name) for name in _RETIRED_SHAPE_FIELDS}
            self.curvature.setValue(settings.curvature)
            self._legacy_curves = {"width_curve": settings.width_curve, "profile_curve": settings.profile_curve}
            self.normal_offset.setValue(settings.normal_offset*100.0)
            self._sculpt_surface = settings.sculpt_surface
            self.sculpt_settled_resolution.setValue(settings.sculpt_settled_resolution)
            self.direction.setValue(settings.direction_degrees)
            self.direction_relax_iterations.setValue(
                settings.direction_relax_iterations
            )
            self.direction_relax_strength.setValue(
                settings.direction_relax_strength
            )
            self.random_size.setValue(settings.random_size)
            self.random_rotation.setValue(settings.random_rotation_degrees)
            self._legacy_cell_shape = {"cell_growth": settings.cell_growth,
                                       "cell_shape_divisions": settings.cell_shape_divisions}
            self.cell_gap.setValue(settings.cell_gap)
            self.cell_collision_margin.setValue(settings.cell_collision_margin)
            self.cell_radius_multiplier.setValue(settings.cell_radius_multiplier)
            self.cell_direction_anisotropy.setValue(
                settings.cell_direction_anisotropy
            )
            self.cell_settled_resolution.setValue(settings.cell_settled_resolution)
            self.cell_projection_rings.setValue(settings.cell_projection_rings)
            self.cell_project_to_surface.setChecked(settings.cell_project_to_surface)
            self._scale_types = list(settings.scale_types)
            self._guide_link_undo_sync = False
            self._pending_interactive_budget = None
            self._pending_interactive_budget_reason = ""
            self.interactive_budget.setValue(settings.interactive_budget)
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
        self._sync_parameter_dependencies()
        self._update_preview_budget_label()
        self._update_preview_limit_warning()
        if refresh_scene:
            self._refresh_guides()
        self._inactivity.setInterval(self.settled_delay.value())
        self.scheduler.configure_delays(
            self.interactive_delay.value(),
            self.settled_delay.value(),
        )

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
        return guide.name

    @staticmethod
    def _guide_info(guide) -> str:
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
        return "{} | {}{}".format(form, role_text, active)

    @staticmethod
    def _guide_group_label(group) -> str:
        return group.name

    def _guide_group_info(self, group) -> str:
        member_count = sum(
            1
            for guide in self._guide_data_by_node.values()
            if guide.group_id == group.group_id
        )
        active = "" if group.enabled else " [OFF]"
        return "Group ({}){}".format(member_count, active)

    def _set_guide_item_label(self, node: str) -> None:
        item = self._guide_tree_items_by_node.get(node)
        if item is None:
            return
        blocked = self.guide_tree.blockSignals(True)
        try:
            guide = self._guide_data_by_node.get(node)
            if guide is not None:
                item.setText(0, self._guide_label(guide))
                item.setText(1, self._guide_info(guide))
                return
            group = self._guide_group_data_by_node.get(node)
            if group is not None:
                item.setText(0, self._guide_group_label(group))
                item.setText(1, self._guide_group_info(group))
        finally:
            self.guide_tree.blockSignals(blocked)

    def _refresh_guide_type_links(self) -> None:
        links = {}
        for scale_type in self._scale_types:
            if scale_type.guide_id:
                links.setdefault(scale_type.guide_id, []).append(scale_type)
        blocked = self.guide_tree.blockSignals(True)
        try:
            for node, item in self._guide_tree_items_by_node.items():
                guide = self._guide_data_by_node.get(node)
                group = self._guide_group_data_by_node.get(node)
                if guide is None and group is None:
                    continue
                identifier = guide.guide_id if guide is not None else group.group_id
                direct = links.get(identifier, [])
                inherited = links.get(guide.group_id, []) if guide is not None else []
                labels = [
                    entry.name + ("" if entry.enabled else " [OFF]")
                    for entry in direct
                ]
                labels.extend(
                    entry.name + " [Group]" + ("" if entry.enabled else " [OFF]")
                    for entry in inherited
                )
                label = ", ".join(labels) or "Unassigned"
                if item.text(4) != label:
                    item.setText(4, label)
                item.setToolTip(4, label)
                linked = direct + inherited
                colors = {entry.color(self._preview_color) for entry in linked}
                brush = QtGui.QBrush()
                if len(colors) == 1:
                    brush = QtGui.QBrush(QtGui.QColor.fromRgbF(*next(iter(colors))))
                item.setData(4, QtCore.Qt.ForegroundRole, brush)
        finally:
            self.guide_tree.blockSignals(blocked)
        self._filter_guide_tree(self.guide_search.text())
        self._refresh_guide_type_combo()

    def _guide_item_node_for_id(self, identifier: str) -> str:
        for node, guide in self._guide_data_by_node.items():
            if guide.guide_id == identifier:
                return node
        for node, group in self._guide_group_data_by_node.items():
            if group.group_id == identifier:
                return node
        return ""

    def _refresh_guide_type_combo(self) -> None:
        target_id = self._current_guide_item_id()
        guide = self._guide_data_by_node.get(
            self._guide_item_node(self._current_guide_item())
        )
        group_id = guide.group_id if guide is not None else ""
        previous = (
            int(self.guide_type_combo.currentData())
            if self.guide_type_combo.count()
            and self.guide_type_combo.currentData() is not None
            else self.scale_type_list.currentRow()
        )
        selected = previous if 0 <= previous < len(self._scale_types) else 0
        direct = []
        inherited = []
        self.guide_type_combo.blockSignals(True)
        try:
            self.guide_type_combo.clear()
            for row, scale_type in enumerate(self._scale_types):
                if scale_type.guide_id == target_id and target_id:
                    state = "Linked here"
                    direct.append(row)
                elif scale_type.guide_id == group_id and group_id:
                    state = "Via group"
                    inherited.append(row)
                elif scale_type.guide_id:
                    state = "Linked elsewhere"
                else:
                    state = "Unassigned"
                self.guide_type_combo.addItem(
                    "{} — {}".format(scale_type.name, state),
                    row,
                )
            if direct or inherited:
                selected = (direct or inherited)[0]
            if self._scale_types:
                self.guide_type_combo.setCurrentIndex(selected)
        finally:
            self.guide_type_combo.blockSignals(False)
        self._guide_type_selection_changed()

    def _guide_type_selection_changed(self, *_args) -> None:
        row = self.guide_type_combo.currentData()
        target_id = self._current_guide_item_id()
        valid = isinstance(row, int) and 0 <= row < len(self._scale_types)
        linked_here = valid and self._scale_types[row].guide_id == target_id
        self.assign_guide_type_button.setEnabled(
            bool(target_id and valid and not linked_here)
        )
        self.unassign_guide_type_button.setEnabled(bool(target_id and linked_here))

    def _set_scale_type_link(self, row: int, identifier: str) -> bool:
        if not (0 <= row < len(self._scale_types)):
            return False
        current = self._scale_types[row]
        if current.guide_id == identifier:
            return False
        self._guide_link_undo_sync = False
        self._scale_types[row] = replace(current, guide_id=identifier)
        self._refresh_scale_type_list(select_row=row)
        self._parameter_changed(ChangeCategory.SHAPE, settle=True)
        return True

    @QtCore.Slot()
    def _assign_current_scale_type(self) -> None:
        row = self.guide_type_combo.currentData()
        target_id = self._current_guide_item_id()
        if isinstance(row, int) and target_id and self._set_scale_type_link(
            row, target_id
        ):
            self._append("Scale Type assigned: {}".format(self._scale_types[row].name))

    @QtCore.Slot()
    def _unassign_current_scale_type(self) -> None:
        row = self.guide_type_combo.currentData()
        target_id = self._current_guide_item_id()
        if (
            isinstance(row, int)
            and target_id
            and self._scale_types[row].guide_id == target_id
            and self._set_scale_type_link(row, "")
        ):
            self._append(
                "Scale Type unassigned: {}".format(self._scale_types[row].name)
            )

    def _set_guide_item_presentation(
        self,
        item,
        kind: str,
        visible: bool,
        locked: bool,
    ) -> None:
        flags = (
            QtCore.Qt.ItemIsEnabled
            | QtCore.Qt.ItemIsSelectable
            | QtCore.Qt.ItemIsUserCheckable
        )
        if not locked:
            flags |= QtCore.Qt.ItemIsEditable | QtCore.Qt.ItemIsDragEnabled
            if kind == "group":
                flags |= QtCore.Qt.ItemIsDropEnabled
        blocked = self.guide_tree.blockSignals(True)
        try:
            item.setFlags(flags)
            item.setCheckState(
                2,
                QtCore.Qt.Checked if visible else QtCore.Qt.Unchecked,
            )
            item.setCheckState(
                3,
                QtCore.Qt.Checked if locked else QtCore.Qt.Unchecked,
            )
            item.setToolTip(2, i18n.translate("Show or hide the guide; scale generation is unchanged."))
            item.setToolTip(3, i18n.translate("Prevent deleting, renaming or reparenting the guide. This is not a transform lock."))
        finally:
            self.guide_tree.blockSignals(blocked)
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
            self._clear_guide_callbacks()
            self._guide_nodes = []
            self._guide_data_by_node = {}
            self._guide_group_nodes = []
            self._guide_group_data_by_node = {}
            self._guide_tree_items_by_node = {}
            self._scene_selected_guide_item = ""
            self._scene_selected_guide_items = ()
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
            group_layout = self.backend.guide_group_layout_state()
            presentation = self.backend.guide_item_presentation_state()
            guide_data = {node: self.backend.read_guide(node) for node in guide_nodes}
            maya_selected_items = self.backend.selected_guide_items()
            maya_selected = maya_selected_items[0] if maya_selected_items else ""
        except Exception as exc:
            self._append("Guide refresh failed: {}".format(exc))
            return

        self._guide_group_nodes = list(group_nodes)
        self._guide_group_data_by_node = group_data
        self._guide_nodes = list(guide_nodes)
        self._guide_data_by_node = guide_data
        self._guide_tree_items_by_node = {}
        self._scene_selected_guide_item = maya_selected
        self._scene_selected_guide_items = tuple(maya_selected_items)

        self._updating_widgets = True
        self.guide_tree.blockSignals(True)
        try:
            self.guide_tree.clear()
            ungrouped_item = QtWidgets.QTreeWidgetItem(["Ungrouped", "", "", ""])
            ungrouped_item.setData(0, _GUIDE_ITEM_KIND_ROLE, "ungrouped")
            ungrouped_item.setData(0, _GUIDE_NODE_ROLE, "")
            ungrouped_item.setFlags(
                QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsDropEnabled
            )
            self.guide_tree.addTopLevelItem(ungrouped_item)

            group_items_by_id = {}
            group_items_by_node = {}
            for group_node in self._guide_group_nodes:
                group = self._guide_group_data_by_node.get(group_node)
                if group is None:
                    continue
                item = QtWidgets.QTreeWidgetItem(
                    [
                        self._guide_group_label(group),
                        self._guide_group_info(group),
                        "",
                        "",
                    ]
                )
                item.setData(0, _GUIDE_ITEM_KIND_ROLE, "group")
                item.setData(0, _GUIDE_NODE_ROLE, group_node)
                visible, locked = presentation.get(group_node, (True, False))
                self._set_guide_item_presentation(
                    item,
                    "group",
                    visible,
                    locked,
                )
                group_items_by_node[group_node] = item
                group_items_by_id[group.group_id] = item
                self._guide_tree_items_by_node[group_node] = item

            for group_node in self._guide_group_nodes:
                item = group_items_by_node.get(group_node)
                if item is None:
                    continue
                parent_node = group_layout.get(group_node, ("", False))[0]
                parent_item = group_items_by_node.get(parent_node)
                if parent_item is None:
                    self.guide_tree.addTopLevelItem(item)
                else:
                    parent_item.addChild(item)

            for guide_node in self._guide_nodes:
                guide = self._guide_data_by_node.get(guide_node)
                if guide is None:
                    continue
                parent = group_items_by_id.get(guide.group_id, ungrouped_item)
                item = QtWidgets.QTreeWidgetItem(
                    [
                        self._guide_label(guide),
                        self._guide_info(guide),
                        "",
                        "",
                    ]
                )
                item.setData(0, _GUIDE_ITEM_KIND_ROLE, "guide")
                item.setData(0, _GUIDE_NODE_ROLE, guide_node)
                visible, locked = presentation.get(guide_node, (True, False))
                self._set_guide_item_presentation(
                    item,
                    "guide",
                    visible,
                    locked,
                )
                parent.addChild(item)
                self._guide_tree_items_by_node[guide_node] = item

            ungrouped_item.setExpanded(True)
            for group_node, item in group_items_by_node.items():
                collapsed = bool(group_layout.get(group_node, ("", False))[1])
                item.setExpanded(not collapsed)
            selected_node = self._preferred_guide_node(current or "", maya_selected)
            selected_item = self._guide_tree_items_by_node.get(selected_node)
            self.guide_tree.clearSelection()
            if selected_item is not None:
                self.guide_tree.setCurrentItem(selected_item)
                for selected in maya_selected_items:
                    item = self._guide_tree_items_by_node.get(selected)
                    if item is not None:
                        item.setSelected(True)
                selected_item.setSelected(True)
                self.guide_tree.scrollToItem(selected_item)
            else:
                self.guide_tree.setCurrentItem(None)
        finally:
            self.guide_tree.blockSignals(False)
            self._updating_widgets = False

        self._refresh_guide_type_links()
        self._refresh_guide_group_combo()
        self._refresh_scale_type_guide_combo()
        self._show_guide_item(self.guide_tree.currentItem(), sync_scene=False)
        self._watch_guide_changes()

    @QtCore.Slot(str)
    def _filter_guide_tree(self, text: str) -> None:
        query = " ".join(str(text).lower().split())

        def update_visibility(item, ancestor_matches: bool = False) -> bool:
            own_text = "{} {} {}".format(item.text(0), item.text(1), item.text(4)).lower()
            own_matches = bool(query and query in own_text)
            descendant_matches = False
            for child_index in range(item.childCount()):
                child = item.child(child_index)
                descendant_matches = (
                    update_visibility(
                        child,
                        ancestor_matches or own_matches,
                    )
                    or descendant_matches
                )
            shown = not query or ancestor_matches or own_matches or descendant_matches
            item.setHidden(not shown)
            return shown

        for top_index in range(self.guide_tree.topLevelItemCount()):
            update_visibility(self.guide_tree.topLevelItem(top_index))

    @QtCore.Slot(object, int)
    def _guide_tree_item_changed(self, item, column: int) -> None:
        if self._updating_widgets or self.backend.binding is None:
            return
        kind = self._guide_item_kind(item)
        node = self._guide_item_node(item)
        if kind not in {"guide", "group"} or not node:
            return

        if column == 1:
            self._set_guide_item_label(node)
            return

        self._updating_widgets = True
        try:
            if column == 0:
                requested = item.text(0).strip()
                if kind == "guide":
                    previous = self._guide_data_by_node.get(node)
                    if previous is None or requested == previous.name:
                        self._set_guide_item_label(node)
                        return
                    actual = self.backend.rename_guide(node, requested)
                    updated = self.backend.read_guide(node)
                    self._guide_data_by_node[node] = updated
                    if self._current_guide_node() == node:
                        self.guide_name.setText(updated.name)
                    self._append("Guide renamed: {}".format(actual))
                else:
                    previous = self._guide_group_data_by_node.get(node)
                    if previous is None or requested == previous.name:
                        self._set_guide_item_label(node)
                        return
                    self.backend.update_guide_group(node, name=requested)
                    updated = self.backend.read_guide_group(node)
                    self._guide_group_data_by_node[node] = updated
                    if self._current_guide_group_node() == node:
                        self.guide_group_name.setText(updated.name)
                    self._append("Guide Group renamed: {}".format(updated.name))
                self._set_guide_item_label(node)
                self._refresh_guide_group_combo()
                self._refresh_scale_type_guide_combo()
                self._filter_guide_tree(self.guide_search.text())
                return

            if column == 2:
                visible = item.checkState(2) == QtCore.Qt.Checked
                self.backend.set_guide_item_visible(node, visible)
            elif column == 3:
                locked = item.checkState(3) == QtCore.Qt.Checked
                self.backend.set_guide_item_locked(node, locked)
            else:
                return

            visible, locked = self.backend.guide_item_presentation_state().get(
                node,
                (True, False),
            )
            self._set_guide_item_presentation(item, kind, visible, locked)
        except Exception as exc:
            self._set_guide_item_label(node)
            try:
                visible, locked = self.backend.guide_item_presentation_state().get(
                    node,
                    (True, False),
                )
                self._set_guide_item_presentation(
                    item,
                    kind,
                    visible,
                    locked,
                )
            except Exception:
                pass
            self._append("Guide Outliner update failed: {}".format(exc))
        finally:
            self._updating_widgets = False
    def _set_guide_group_collapsed(self, item, collapsed: bool) -> None:
        if self._updating_widgets or self._guide_item_kind(item) != "group":
            return
        node = self._guide_item_node(item)
        if not node:
            return
        self._updating_widgets = True
        try:
            self.backend.set_guide_group_collapsed(node, collapsed)
        except Exception as exc:
            self._append("Guide Group collapse state failed: {}".format(exc))
        finally:
            self._updating_widgets = False

    @QtCore.Slot(object)
    def _guide_group_collapsed(self, item) -> None:
        self._set_guide_group_collapsed(item, True)

    @QtCore.Slot(object)
    def _guide_group_expanded(self, item) -> None:
        self._set_guide_group_collapsed(item, False)
    def _clear_guide_callbacks(self) -> None:
        if not self._guide_callback_ids:
            return
        try:
            from maya.api import OpenMaya as om  # type: ignore

            om.MMessage.removeCallbacks(self._guide_callback_ids)
        except Exception:
            pass
        self._guide_callback_ids = []

    def _watch_guide_changes(self) -> None:
        self._clear_guide_callbacks()
        binding = self.backend.binding
        if binding is None:
            return
        try:
            from maya.api import OpenMaya as om  # type: ignore

            cmds = self.backend.scene.cmds
            nodes = set(self._guide_nodes + self._guide_group_nodes)
            if binding.guide_root:
                nodes.add(binding.guide_root)
            for node in tuple(nodes):
                nodes.update(
                    cmds.listRelatives(node, allDescendents=True, fullPath=True) or []
                )
            for node in nodes:
                selection = om.MSelectionList()
                selection.add(node)
                self._guide_callback_ids.append(
                    om.MNodeMessage.addAttributeChangedCallback(
                        selection.getDependNode(0), self._guide_attribute_changed
                    )
                )
        except Exception:
            self._clear_guide_callbacks()

    def _guide_attribute_changed(self, message, *_args) -> None:
        from maya.api import OpenMaya as om  # type: ignore

        authored_change = (
            om.MNodeMessage.kAttributeSet
            | om.MNodeMessage.kConnectionMade
            | om.MNodeMessage.kConnectionBroken
            | om.MNodeMessage.kAttributeArrayAdded
            | om.MNodeMessage.kAttributeArrayRemoved
            | om.MNodeMessage.kAttributeLocked
            | om.MNodeMessage.kAttributeUnlocked
        )
        if message & authored_change:
            self._guide_node_dirtied()

    def _guide_node_dirtied(self, *_args) -> None:
        if (
            not self._polling_guide_changes
            and not self._updating_widgets
            and not self._guide_undo_open
        ):
            self._guide_poll.start()

    def _show_guide_item(self, item, *, sync_scene: bool) -> None:
        kind = self._guide_item_kind(item)
        node = self._guide_item_node(item)
        guide = self._guide_data_by_node.get(node) if kind == "guide" else None
        group = (
            self._guide_group_data_by_node.get(node) if kind == "group" else None
        )

        self.guide_editor.setVisible(guide is not None)
        self.guide_group_editor.setVisible(group is not None)
        self.guide_type_editor.setVisible(guide is not None or group is not None)
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
        self._refresh_guide_type_combo()

        if sync_scene and node and not self._syncing_guide_selection:
            try:
                self.backend.select_guide_item(node)
                self._scene_selected_guide_item = node
                self._scene_selected_guide_items = (node,)
            except Exception as exc:
                self._append("Guide selection failed: {}".format(exc))

    def _selected_guide_item_nodes(self) -> list[str]:
        current = self._guide_item_node(self.guide_tree.currentItem())
        selected: list[str] = []
        for item in self.guide_tree.selectedItems():
            if self._guide_item_kind(item) not in {"guide", "group"}:
                continue
            node = self._guide_item_node(item)
            if node and node not in selected:
                selected.append(node)
        if current in selected:
            selected.remove(current)
            selected.insert(0, current)
        return selected

    @QtCore.Slot(object, object)
    def _guide_selection_changed(self, current, _previous) -> None:
        if self._updating_widgets:
            return
        self._show_guide_item(current, sync_scene=False)

    @QtCore.Slot()
    def _guide_tree_selection_changed(self) -> None:
        if self._updating_widgets:
            return
        item = self.guide_tree.currentItem()
        selected = self._selected_guide_item_nodes()
        self._show_guide_item(item if selected else None, sync_scene=False)
        if self._syncing_guide_selection or not selected:
            return
        try:
            self.backend.select_guide_items(selected)
            self._scene_selected_guide_item = selected[0]
            self._scene_selected_guide_items = tuple(selected)
        except Exception as exc:
            self._append("Guide selection failed: {}".format(exc))

    def _sync_guide_selection_from_maya(self) -> None:
        if self.backend.binding is None or self._updating_widgets:
            return
        try:
            selected = self.backend.selected_guide_items()
        except Exception:
            return
        missing = [
            node for node in selected if node not in self._guide_tree_items_by_node
        ]
        if missing:
            self._refresh_guides(preferred=missing[0])
            return
        current = self._selected_guide_item_nodes()
        if (
            set(selected) == set(current)
            and tuple(selected) == self._scene_selected_guide_items
        ):
            return
        self._scene_selected_guide_item = selected[0] if selected else ""
        self._scene_selected_guide_items = tuple(selected)
        items = [
            self._guide_tree_items_by_node[node]
            for node in selected
            if node in self._guide_tree_items_by_node
        ]
        item = items[0] if items else None
        self._syncing_guide_selection = True
        self.guide_tree.blockSignals(True)
        try:
            self.guide_tree.clearSelection()
            if item is None:
                self.guide_tree.setCurrentItem(None)
            else:
                self.guide_tree.setCurrentItem(item)
                for selected_item in items:
                    selected_item.setSelected(True)
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
            updated = self.backend.read_guide(node)
            self._guide_data_by_node[node] = updated
            self._updating_widgets = True
            try:
                self.guide_name.setText(updated.name)
                self._set_guide_item_label(node)
            finally:
                self._updating_widgets = False
            self._refresh_guide_group_combo()
            self._refresh_scale_type_guide_combo()
            self._filter_guide_tree(self.guide_search.text())
            self._append("Guide renamed: {}".format(actual))
        except Exception as exc:
            self._updating_widgets = True
            try:
                self.guide_name.setText(guide.name)
                self._set_guide_item_label(node)
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
            group_parents: dict[str, str] = {}
            guides_by_group: dict[str, list[str]] = {"": []}
            seen_groups: set[str] = set()
            seen_guides: set[str] = set()

            def add_guide(item, group_node: str) -> None:
                node = self._guide_item_node(item)
                if (
                    self._guide_item_kind(item) != "guide"
                    or not node
                    or node in seen_guides
                    or item.childCount() != 0
                ):
                    raise ValueError("Only Guides may be placed in a Guide container")
                guides_by_group[group_node].append(node)
                seen_guides.add(node)

            def add_group(item, parent_node: str) -> None:
                node = self._guide_item_node(item)
                if (
                    self._guide_item_kind(item) != "group"
                    or not node
                    or node in seen_groups
                ):
                    raise ValueError("Guide Group hierarchy is invalid")
                seen_groups.add(node)
                ordered_groups.append(node)
                group_parents[node] = parent_node
                guides_by_group[node] = []
                for child_index in range(item.childCount()):
                    child = item.child(child_index)
                    if self._guide_item_kind(child) == "group":
                        add_group(child, node)
                    else:
                        add_guide(child, node)

            for child_index in range(ungrouped.childCount()):
                add_guide(ungrouped.child(child_index), "")
            for top_index in range(1, self.guide_tree.topLevelItemCount()):
                add_group(self.guide_tree.topLevelItem(top_index), "")

            if seen_groups != set(self._guide_group_nodes):
                raise ValueError("Guide Group layout is incomplete")
            if seen_guides != set(self._guide_nodes):
                raise ValueError("Guide layout is incomplete")

            category = self.backend.apply_guide_tree_layout(
                ordered_groups,
                guides_by_group,
                group_parents,
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

    def _create_guide_group_with_guides(self, guides: list[str]) -> None:
        try:
            node = self.backend.create_guide_group(guide_nodes=guides)
            self._refresh_guides(preferred=node)
            try:
                self.backend.select_guide_item(node)
                self._scene_selected_guide_item = node
                self._scene_selected_guide_items = (node,)
            except Exception:
                pass
            self._append("Guide Group created: {}".format(node))
        except Exception as exc:
            self._append("Guide Group creation failed: {}".format(exc))

    def _group_selected_guides_from_shortcut(self) -> bool:
        if self.backend.binding is None:
            return False
        try:
            guides, has_guide_items, mixed = self.backend.guide_grouping_selection()
        except Exception:
            return False
        if not has_guide_items:
            return False
        if mixed:
            message = (
                "Guideと通常オブジェクト、またはGuide Groupは同時に"
                "グループ化できません。Guideだけを選択してください。"
            )
            self.status_label.setText("Guide grouping cancelled")
            self._append(message)
            try:
                self.backend.scene.cmds.warning(message)
            except Exception:
                pass
            return True
        self._create_guide_group_with_guides(guides)
        return True

    @QtCore.Slot()
    def _create_guide_group(self) -> None:
        if self.backend.binding is None:
            self._append("Systemを先に作成してください")
            return
        selected_guides = [
            node
            for node in self._selected_guide_item_nodes()
            if node in self._guide_data_by_node
        ]
        self._create_guide_group_with_guides(selected_guides)

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
        self._scene_selected_guide_items = ()
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

    def _watch_scene_events(self) -> None:
        self._clear_scene_callbacks()
        try:
            from maya.api import OpenMaya as om  # type: ignore

            for event in ("SelectionChanged", "ToolChanged"):
                self._scene_callback_ids.append(
                    om.MEventMessage.addEventCallback(event, self._scene_event_changed)
                )
            for event in ("Undo", "Redo"):
                try:
                    self._scene_callback_ids.append(
                        om.MEventMessage.addEventCallback(
                            event,
                            self._guide_undo_redo_changed,
                        )
                    )
                except Exception:
                    # Keep selection sync on Maya versions missing an optional event.
                    pass
        except Exception:
            self._clear_scene_callbacks()
            self._scene_poll.setSingleShot(False)
            self._scene_poll.setInterval(250)
            self._scene_poll.start()

    def _clear_scene_callbacks(self) -> None:
        if not self._scene_callback_ids:
            return
        try:
            from maya.api import OpenMaya as om  # type: ignore

            om.MMessage.removeCallbacks(self._scene_callback_ids)
        except Exception:
            pass
        self._scene_callback_ids = []

    def _guide_undo_redo_changed(self, *_args) -> None:
        if not self._updating_widgets:
            QtCore.QTimer.singleShot(0, self._sync_guide_item_presentation)
            QtCore.QTimer.singleShot(0, self._sync_settings_from_scene)

    def _sync_settings_from_scene(self) -> None:
        if self.backend.binding is None or self._updating_widgets:
            return
        try:
            settings = self.backend.read_settings()
            current = ScaleSettings.from_mapping(self._snapshot())
        except Exception:
            return
        if settings == current:
            return
        self._load_settings(settings, refresh_scene=False)

    def _sync_guide_item_presentation(self) -> None:
        if self.backend.binding is None or self._updating_widgets:
            return
        try:
            presentation = self.backend.guide_item_presentation_state()
        except Exception:
            return
        self._updating_widgets = True
        try:
            for node, (visible, locked) in presentation.items():
                item = self._guide_tree_items_by_node.get(node)
                if item is not None:
                    self._set_guide_item_presentation(
                        item,
                        self._guide_item_kind(item),
                        visible,
                        locked,
                    )
        finally:
            self._updating_widgets = False
    def _scene_event_changed(self, *_args) -> None:
        self._scene_poll.start()

    def _poll_guide_changes(self) -> None:
        if (
            self.backend.binding is None
            or self._updating_widgets
            or self._guide_undo_open
        ):
            return
        self._polling_guide_changes = True
        try:
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
        finally:
            self._polling_guide_changes = False

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

    def _filter_guides_for_scale_type(self) -> None:
        row = self.scale_type_list.currentRow()
        if not (0 <= row < len(self._scale_types)):
            return
        scale_type = self._scale_types[row]
        if not scale_type.guide_id:
            self._append("Scale Type has no Guide Link: {}".format(scale_type.name))
            return
        self.guide_search.setText(scale_type.name)
        self.tabs.setCurrentWidget(self.guides_tab)

    def _jump_to_scale_type_link(self) -> None:
        row = self.scale_type_list.currentRow()
        if not (0 <= row < len(self._scale_types)):
            return
        scale_type = self._scale_types[row]
        node = self._guide_item_node_for_id(scale_type.guide_id)
        item = self._guide_tree_items_by_node.get(node)
        if item is None:
            self._append("Scale Type link target is missing: {}".format(scale_type.name))
            return
        self.guide_search.clear()
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        self.guide_tree.clearSelection()
        self.guide_tree.setCurrentItem(item)
        item.setSelected(True)
        self.guide_tree.scrollToItem(item)
        self.tabs.setCurrentWidget(self.guides_tab)

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
        self._refresh_guide_type_links()

    @QtCore.Slot(int)
    def _scale_type_selection_changed(self, row: int) -> None:
        if not (0 <= row < len(self._scale_types)):
            self.filter_type_link_button.setEnabled(False)
            self.jump_type_link_button.setEnabled(False)
            return
        item = self._scale_types[row]
        has_link = bool(item.guide_id)
        self.filter_type_link_button.setEnabled(has_link)
        self.jump_type_link_button.setEnabled(
            bool(self._guide_item_node_for_id(item.guide_id))
        )
        self._updating_widgets = True
        try:
            self.type_name.setText(item.name)
            self.type_enabled.setChecked(item.enabled)
            self.type_size.setValue(item.size_multiplier)
            self.type_curvature.setValue(item.curvature_multiplier)
            self.type_offset.setValue(item.offset*100.0)
            self.type_random_offset.setValue(item.random_offset)
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
            curvature_multiplier=self.type_curvature.value(),
            offset=self.type_offset.value()/100.0,
            random_offset=self.type_random_offset.value(),
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
        if (
            self.backend.binding is not None
            and not self._guide_undo_open
            and not self._parameter_undo_open
        ):
            try:
                self.backend.begin_undo_chunk("Bifrost Scales Parameter Edit")
                self._parameter_undo_open = True
            except Exception:
                self._parameter_undo_open = False
        if not self.scheduler.core.status.dragging:
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

    def _open_sculpt_editor(self, per_type=False):
        from .sculpt_editor import SculptEditor
        from maya import cmds
        if self.backend.binding is None:
            return
        owner = self.backend.binding.settings_node
        owner_uuid = cmds.ls(owner, uuid=True)
        row = self.scale_type_list.currentRow()
        if per_type and not 0 <= row < len(self._scale_types):
            return
        type_id = self._scale_types[row].type_id if per_type else None
        original = self._scale_types[row].sculpt_surface if per_type else self._sculpt_surface
        initial = original or (self._sculpt_surface if per_type else {})

        def apply(surface):
            nonlocal original
            if self.backend.binding is None or self.backend.binding.settings_node != owner:
                raise ValueError("編集開始時のSystemを選択してから適用してください。")
            if cmds.ls(owner, uuid=True) != owner_uuid:
                raise ValueError("編集先のSystemが削除または再作成されています。")
            index = next((i for i, item in enumerate(self._scale_types) if item.type_id == type_id), None)
            if per_type and index is None:
                raise ValueError("編集先のScale Typeが存在しません。")
            current = self._scale_types[index].sculpt_surface if per_type else self._sculpt_surface
            if current != original:
                raise ValueError("保存先の形状が別の操作で変更されました。編集を開き直してください。")
            self._finish_interaction()
            self.backend.begin_undo_chunk("Bifrost Scales Interior Sculpt")
            try:
                if per_type:
                    self._scale_types[index] = replace(self._scale_types[index], sculpt_surface=surface)
                else:
                    self._sculpt_surface = surface
                try:
                    self.backend.persist_settings(self._snapshot())
                except Exception:
                    if per_type:
                        self._scale_types[index] = replace(self._scale_types[index], sculpt_surface=current)
                    else:
                        self._sculpt_surface = current
                    raise
                original = surface
                self._sync_parameter_dependencies()
                self._parameter_changed(ChangeCategory.SHAPE, settle=True)
            finally:
                self.backend.end_undo_chunk()

        previous = getattr(self, "_sculpt_editor", None)
        if previous is not None:
            previous.close()
        dialog = SculptEditor(initial, apply, self, owner_key=owner_uuid[0]+":"+str(type_id))
        self._sculpt_editor = dialog
        dialog.destroyed.connect(lambda: setattr(self, "_sculpt_editor", None)
                                 if getattr(self, "_sculpt_editor", None) is dialog else None)
        dialog.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        dialog.show()

    def _parameter_changed(self, category: ChangeCategory, settle: bool = False) -> None:
        if not self._updating_widgets:
            self._update_preview_limit_warning()
        if self._updating_widgets or not self.auto_preview.isChecked() or self.backend.binding is None:
            return
        self._begin_interaction()
        self.scheduler.queue_change(category, self._snapshot())
        if settle:
            self._finish_interaction()
        else:
            self._inactivity.start(self.settled_delay.value())

    @QtCore.Slot()
    def _finish_interaction(self) -> None:
        self._inactivity.stop()
        if self._parameter_undo_open:
            try:
                if self.backend.binding is not None:
                    self.backend.persist_settings(self._snapshot())
            except Exception:
                self._close_parameter_undo()
                raise
        if not self.auto_preview.isChecked():
            self._close_parameter_undo()
            return
        self.scheduler.end_interaction()
        status = self.scheduler.core.status
        if not status.pending and status.inflight_revision is None:
            self._close_parameter_undo()

    def _close_parameter_undo(self) -> None:
        if not self._parameter_undo_open:
            return
        try:
            self.backend.end_undo_chunk()
        finally:
            self._parameter_undo_open = False

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
            self._close_parameter_undo()

    @QtCore.Slot(bool)
    def _auto_preview_budget_toggled(self, enabled: bool) -> None:
        self._pending_interactive_budget = None
        self._pending_interactive_budget_reason = ""
        self.interactive_budget.setEnabled(not enabled)
        self._update_preview_budget_label()

    @QtCore.Slot(int)
    def _interactive_budget_changed(self, value: int) -> None:
        if not self.auto_preview_budget.isChecked():
            self._update_preview_budget_label()

    def _update_preview_budget_label(self) -> None:
        value = self.interactive_budget.value()
        if not self.auto_preview_budget.isChecked():
            self.auto_preview_budget_label.setText("Manual: {}（固定）".format(value))
        elif self._pending_interactive_budget is not None:
            self.auto_preview_budget_label.setText(
                "Auto: {} → 次回 {}（{}）".format(
                    value,
                    self._pending_interactive_budget,
                    self._pending_interactive_budget_reason,
                )
            )
        elif self._pending_interactive_budget_reason:
            self.auto_preview_budget_label.setText(
                "Auto: {}（{}）".format(
                    value,
                    self._pending_interactive_budget_reason,
                )
            )
        else:
            self.auto_preview_budget_label.setText(
                "Auto: {}（次の操作まで固定）".format(value)
            )

    def _update_auto_preview_budget(self, mode: str, report: Any) -> None:
        if not self.auto_preview_budget.isChecked():
            return
        if mode == "interactive":
            next_budget = int(report.next_interactive_budget)
            self._pending_interactive_budget = next_budget
            if next_budget < report.effective_budget:
                reason = "直近 {:.1f} ms > 120 ms".format(report.total_ms)
            elif next_budget > report.effective_budget:
                reason = "直近 {:.1f} ms < 60 ms".format(report.total_ms)
            elif report.total_ms > 120.0:
                reason = "Interactive上限 8 が下限"
            elif report.total_ms < 60.0:
                reason = "目標鱗数 {} が上限".format(self.target_count.value())
            else:
                reason = "直近 {:.1f} ms は安定範囲".format(report.total_ms)
            self._pending_interactive_budget_reason = reason
            self._update_preview_budget_label()
        elif mode == "settled" and self._pending_interactive_budget is not None:
            self._updating_widgets = True
            try:
                self.interactive_budget.setValue(self._pending_interactive_budget)
            finally:
                self._updating_widgets = False
            self._pending_interactive_budget = None
            self._update_preview_budget_label()

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
    def _create_maya_mesh(self) -> None:
        status = self.scheduler.core.status
        if status.pending or status.inflight_revision is not None:
            QtWidgets.QMessageBox.information(self, "Bifrost Scales", i18n.translate("Wait for the preview to finish before creating a mesh."))
            return
        self._close_parameter_undo()
        try:
            result = self.backend.create_maya_mesh()
            self.status_label.setText(i18n.translate("Mesh created") + ": " + result)
            self._append("Mesh created: " + result)
        except Exception as exc:
            self._append("Create mesh failed: " + str(exc))
            QtWidgets.QMessageBox.warning(self, "Bifrost Scales", str(exc))

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
        self._update_auto_preview_budget(mode, report)
        if mode == "settled":
            self._close_parameter_undo()
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
                    "\nGPU Compute: {} samples | upload {:.2f} / kernel {:.2f} / "
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
                "neighborCache={} guideSurface={:.2f}({}/{}) meshSample={} projectorCache={} "
                "payload={:.2f} source={:.2f} distribution={:.2f}({}/d{}/c{}/b{}/x{}/g{:.3f}) "
                "orientation={:.2f} orientParts={:.2f}/{:.2f}/{:.2f}/{:.2f} "
                "gpuParts={:.2f}/{:.2f}/{:.2f} "
                "relaxParts={:.2f}/{:.2f}/{:.2f} "
                "cells={:.2f} "
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
                    (
                        "hit"
                        if report.native_direction_neighbors_cache_hit
                        else "miss"
                    ),
                    report.native_guide_surface_ms,
                    report.native_guide_surface_cache_hits,
                    report.native_guide_surface_cache_misses,
                    (
                        "n/a"
                        if report.mode != "interactive"
                        else (
                            "hit"
                            if report.native_interactive_surface_cache_hit
                            else "miss"
                        )
                    ),
                    (
                        "n/a"
                        if report.mode != "interactive"
                        else (
                            "hit"
                            if report.native_global_projection_cache_hit
                            else "miss"
                        )
                    ),
                    report.native_payload_decode_ms,
                    report.native_source_decode_ms,
                    report.native_distribution_ms,
                    report.native_distribution_attempts,
                    report.native_distribution_density_rejected,
                    report.native_distribution_conflict_rejected,
                    report.native_distribution_bucket_queries,
                    report.native_distribution_distance_tests,
                    report.native_distribution_grid_density_reference,
                    report.native_orientation_ms,
                    report.native_orientation_prepare_ms,
                    report.native_direction_neighbors_ms,
                    report.native_direction_relax_ms,
                    report.native_orientation_finalize_ms,
                    report.native_gpu_upload_ms,
                    report.native_gpu_kernel_ms,
                    report.native_gpu_readback_ms,
                    report.native_direction_relax_pack_ms,
                    report.native_direction_relax_gpu_call_ms,
                    report.native_direction_relax_unpack_ms,
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
        self._close_parameter_undo()
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

    def _cancel_preview_queue(self) -> None:
        self._inactivity.stop()
        self._close_parameter_undo()
        self.scheduler.clear_error()
        if not self.auto_preview.isChecked():
            self.scheduler.pause()

    def _append(self, text: str) -> None:
        self.log.appendPlainText(str(text))

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.maintenance_dialog.close()
        sculpt_editor = getattr(self, "_sculpt_editor", None)
        if sculpt_editor is not None:
            sculpt_editor.close()
        application = QtWidgets.QApplication.instance()
        if application is not None:
            application.removeEventFilter(self)
        self._finish_guide_interaction()
        draw_context.stop_draw(cancel=True, reason="UIを閉じたためGuide描画を終了しました")
        self._guide_poll.stop()
        self._clear_guide_callbacks()
        self._scene_poll.stop()
        self._clear_scene_callbacks()
        self._inactivity.stop()
        self.scheduler.pause()
        self._close_parameter_undo()
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
