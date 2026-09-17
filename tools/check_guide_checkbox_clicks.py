"""Actual Qt mouse events, not setCheckState calls (Maya's bundled Qt)."""
from pathlib import Path
import sys

if "--installed" not in sys.argv:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "BifrostScales/scripts"))
from bifrost_scales.qt_compat import QtCore, QtWidgets
from bifrost_scales.ui import _GuideTreeWidget
try:
    from PySide6 import QtTest
except ImportError:
    from PySide2 import QtTest


def click_checkbox(tree, item, column):
    tree.scrollToItem(item)
    QtWidgets.QApplication.processEvents()
    index = tree.indexFromItem(item, column)
    option = QtWidgets.QStyleOptionViewItem()
    option.initFrom(tree)
    option.rect = tree.visualRect(index)
    option.features |= QtWidgets.QStyleOptionViewItem.HasCheckIndicator
    option.checkState = item.checkState(column)
    rect = tree.style().subElementRect(QtWidgets.QStyle.SE_ItemViewItemCheckIndicator, option, tree)
    QtTest.QTest.mouseClick(tree.viewport(), QtCore.Qt.LeftButton, pos=rect.center())
    QtWidgets.QApplication.processEvents()


def main():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    tree = _GuideTreeWidget()
    tree.setColumnCount(5)
    tree.resize(700, 180)
    item = QtWidgets.QTreeWidgetItem(tree, ["Guide", "", "", "", ""])
    item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable | QtCore.Qt.ItemIsUserCheckable)
    tree.show()
    for column in (2, 3):
        for initial in (QtCore.Qt.Unchecked, QtCore.Qt.Checked):
            item.setCheckState(column, initial)
            app.processEvents()
            click_checkbox(tree, item, column)
            assert item.checkState(column) != initial, (column, initial, "mouse click did not toggle")
    tree.close()
    print("Guide checkbox mouse clicks: 4/4 PASS")


if __name__ == "__main__":
    main()
