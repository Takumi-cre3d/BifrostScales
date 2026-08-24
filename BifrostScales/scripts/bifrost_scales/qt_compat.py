"""PySide compatibility import used inside Maya 2026."""

try:
    from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore
except Exception:
    from PySide2 import QtCore, QtGui, QtWidgets  # type: ignore

__all__ = ["QtCore", "QtGui", "QtWidgets"]
