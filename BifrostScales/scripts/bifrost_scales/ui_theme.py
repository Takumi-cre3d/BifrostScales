"""Compact desktop styling, scoped to tool windows (not Maya's application)."""
from pathlib import Path
from .qt_compat import QtGui, QtWidgets


def ui_icon(name):
    return QtGui.QIcon(str(Path(__file__).with_name("icons") / (name + ".svg")))


def add_depth(root):
    # One shadow per panel or standalone button; never stack nested effects.
    for widget in (root.findChildren(QtWidgets.QGroupBox) +
                   root.findChildren(QtWidgets.QPushButton) + root.findChildren(QtWidgets.QToolButton)):
        parent = widget.parentWidget()
        while parent is not None and parent.graphicsEffect() is None:
            parent = parent.parentWidget()
        if parent is not None:
            continue
        shadow = QtWidgets.QGraphicsDropShadowEffect(widget)
        shadow.setBlurRadius(6)
        shadow.setOffset(0, 2)
        shadow.setColor(QtGui.QColor(0, 0, 0, 85))
        widget.setGraphicsEffect(shadow)


STUDIO_STYLE = """
QDialog { background: #252525; color: #dddddd; }
QWidget { font-family: 'Segoe UI', 'Yu Gothic UI'; font-size: 12px; color: #dddddd; }
QWidget#settingsContent { background: #252525; }
QLabel { background: transparent; }
QLabel#brand { font-size: 14px; font-weight: 600; color: #eeeeee; }
QGroupBox { background: transparent; border: 0; border-top: 1px solid #484848;
    border-radius: 0; margin-top: 14px; padding: 6px 0 0 0; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 0; padding: 0 8px 0 0; color: #eeeeee; }
QTabWidget::pane { border: 1px solid #505050; top: -1px; }
QTabBar::tab { background: #303030; color: #aaaaaa; padding: 6px 12px;
    border: 1px solid #505050; border-bottom: 0; margin-right: -1px; }
QTabBar::tab:selected { background: #252525; color: #ffffff; border-top: 2px solid #ee603e; }
QTabBar::tab:hover { background: #3b3b3b; color: #ffffff; }
QPushButton, QToolButton { background: #383838; border: 1px solid #555555;
    border-radius: 2px; padding: 3px 8px; min-height: 18px; }
QPushButton:hover, QToolButton:hover { background: #464646; border-color: #888888; }
QPushButton:pressed, QToolButton:pressed { background: #202020; }
QPushButton:focus, QToolButton:focus, QComboBox:focus, QLineEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus { border: 1px solid #ee603e; }
QPushButton[primary="true"] { background: #b83e24; color: #ffffff;
    border: 1px solid #ee603e; font-weight: 600; }
QPushButton[primary="true"]:hover { background: #cf492b; }
QPushButton[danger="true"] { background: transparent; color: #bbbbbb; }
QPushButton[quiet="true"] { background: transparent; border: none; color: #aaaaaa; padding: 1px 4px; }
QPushButton[quiet="true"]:hover { color: #ffffff; background: #383838; }
QPushButton:disabled, QToolButton:disabled { background: #2b2b2b; color: #777777; border-color: #404040; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {
    background: #1e1e1e; border: 1px solid #505050; border-radius: 1px;
    padding: 2px 4px; selection-background-color: #555555; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled { color: #777777; border-color: #383838; }
QComboBox::drop-down { border: 0; width: 18px; }
QComboBox QAbstractItemView { background: #292929; border: 1px solid #555555; selection-background-color: #505050; }
QTreeWidget, QListWidget { background: #202020; alternate-background-color: #272727;
    border: 1px solid #484848; selection-background-color: #505050; }
QTreeWidget::item, QListWidget::item { padding: 2px; }
QTreeWidget::item:selected, QListWidget::item:selected { background: #505050; color: #ffffff; }
QHeaderView::section { background: #333333; color: #dddddd; border: 0;
    border-right: 1px solid #484848; border-bottom: 1px solid #484848; padding: 4px; }
QSlider::groove:horizontal { height: 3px; background: #505050; }
QSlider::sub-page:horizontal { background: #777777; }
QSlider::handle:horizontal { background: #ee603e; border: 1px solid #ff8866;
    width: 7px; margin: -5px 0; border-radius: 1px; }
QSlider::handle:horizontal:disabled { background: #666666; border-color: #777777; }
QCheckBox { spacing: 5px; padding: 1px 0; }
QScrollArea { border: 0; background: transparent; }
QScrollBar:vertical { background: #242424; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #606060; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QMenu { background: #303030; border: 1px solid #606060; padding: 3px; }
QMenu::item { padding: 4px 20px; }
QMenu::item:selected { background: #505050; }
QToolTip { color: #eeeeee; background: #333333; border: 1px solid #777777; padding: 4px; }
"""

# No frame outlines; keyboard focus remains visible through the fill color.
STUDIO_STYLE += """
QGroupBox, QTabWidget::pane, QTabBar::tab, QTabBar::tab:selected,
QPushButton, QToolButton, QPushButton[primary="true"],
QPushButton:focus, QToolButton:focus, QComboBox:focus, QLineEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus,
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit,
QComboBox QAbstractItemView, QTreeWidget, QListWidget, QHeaderView::section,
QSlider::handle:horizontal, QMenu, QToolTip { border: 0; outline: 0; }
QTabBar::tab:selected { background: #454545; color: #ffffff; }
QGroupBox { background: #292929; }
QPushButton:focus, QToolButton:focus, QComboBox:focus, QLineEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus { background: #494949; }
QComboBox::drop-down { border: 0; width: 22px; }
QComboBox::down-arrow { image: url(DROPDOWN_ICON); width: 10px; height: 7px; }
""".replace("DROPDOWN_ICON", (Path(__file__).with_name("icons") / "dropdown.svg").as_posix())
